"""Tests for the database migrations in src/migrations, and src/migrate.py which runs them."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

from src import migrate, sql_store
from src.calculator_state import CalculatorState

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from types import ModuleType


def load_migration(name: str) -> ModuleType:
    return migrate.load_migration(migrate.MIGRATIONS_DIR / f"{name}.py")


@pytest.fixture
def old_conn() -> Iterator[sqlite3.Connection]:
    """A SQLite database with the 0.1 schema, where projects.version is an INTEGER, holding one saved project."""
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        old_schema: str = sql_store.SCHEMA.replace("version TEXT NOT NULL", "version INTEGER NOT NULL")
        assert old_schema != sql_store.SCHEMA
        conn.executescript(old_schema)
        sql_store.save_project(conn, CalculatorState.default(), 1)  # ty:ignore[invalid-argument-type]
        yield conn


def test_0_1_to_0_1_2_migrates_sqlite(old_conn: sqlite3.Connection) -> None:
    migration: ModuleType = load_migration("0.1_to_0.1.2_migration")
    [project] = sql_store.list_projects(old_conn)
    assert project["version"] == 1

    migration.migrate(old_conn)
    migration.migrate(old_conn)

    [project] = sql_store.list_projects(old_conn)
    assert project["version"] == "0.1"
    assert sql_store.load_project(old_conn, project["public_id"]) == CalculatorState.default()
    sql_store.update_project(old_conn, project["public_id"], CalculatorState.default(), "0.1.2")
    [project] = sql_store.list_projects(old_conn)
    assert project["version"] == "0.1.2"
    # Children still reference the project after the projects table is altered.
    assert old_conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_0_1_to_0_1_2_leaves_new_sqlite_database_unchanged() -> None:
    migration: ModuleType = load_migration("0.1_to_0.1.2_migration")
    with closing(sql_store.connect(":memory:")) as conn:
        public_id: str = sql_store.save_project(conn, CalculatorState.default(), "0.1.2")
        migration.migrate(conn)
        [project] = sql_store.list_projects(conn)
        assert project["public_id"] == public_id
        assert project["version"] == "0.1.2"


def test_0_1_4_to_0_1_5_adds_peer_reviewers_column() -> None:
    migration: ModuleType = load_migration("0.1.4_to_0.1.5_migration")
    with closing(sql_store.connect(":memory:")) as conn:
        public_id: str = sql_store.save_project(conn, CalculatorState.default(), "0.1.4")
        # The 0.1.4 schema has no peer_reviewers column.
        conn.execute("ALTER TABLE activities DROP COLUMN peer_reviewers")

        migration.migrate(conn)
        migration.migrate(conn)

        assert sql_store.load_project(conn, public_id) == CalculatorState.default()
        state: CalculatorState = CalculatorState.default()
        state.peer_review.peer_reviewers = 3
        sql_store.update_project(conn, public_id, state, "0.1.5")
        assert sql_store.load_project(conn, public_id).peer_review.peer_reviewers == 3


def test_find_migrations_orders_by_version(tmp_path: Path) -> None:
    for name in ("0.10_to_0.11_migration.py", "0.2_to_0.10_migration.py", "0.1_to_0.2_migration.py", "notes.py"):
        (tmp_path / name).write_text("", encoding="utf-8")
    assert [path.name for path in migrate.find_migrations(tmp_path)] == [
        "0.1_to_0.2_migration.py",
        "0.2_to_0.10_migration.py",
        "0.10_to_0.11_migration.py",
    ]


def test_run_migrations_migrates_old_database_once(old_conn: sqlite3.Connection) -> None:
    assert migrate.run_migrations(old_conn) == ["0.1_to_0.1.2_migration", "0.1.4_to_0.1.5_migration"]
    [project] = sql_store.list_projects(old_conn)
    assert project["version"] == "0.1"

    assert migrate.run_migrations(old_conn) == []


def test_run_migrations_creates_new_database_without_migrating(tmp_path: Path) -> None:
    with closing(sqlite3.connect(tmp_path / "new.db")) as conn:
        assert migrate.run_migrations(conn) == []
        sql_store.save_project(conn, CalculatorState.default(), "0.1.2")
        applied: list[str] = [row[0] for row in conn.execute("SELECT name FROM schema_migrations")]
        assert sorted(applied) == sorted(path.stem for path in migrate.find_migrations())
        assert migrate.run_migrations(conn) == []


def test_run_migrations_skips_recorded_migrations(tmp_path: Path) -> None:
    for name in ("0.1_to_0.2", "0.2_to_0.3"):
        (tmp_path / f"{name}_migration.py").write_text(
            f"def migrate(conn):\n    conn.execute(\"INSERT INTO log VALUES ('{name}')\")\n", encoding="utf-8"
        )
    with closing(sql_store.connect(":memory:")) as conn:
        conn.execute("CREATE TABLE log (name TEXT)")
        conn.execute(migrate.MIGRATIONS_TABLE_SCHEMA)
        conn.execute("INSERT INTO schema_migrations VALUES ('0.1_to_0.2_migration', '')")
        conn.commit()
        assert migrate.run_migrations(conn, tmp_path) == ["0.2_to_0.3_migration"]
        assert [row[0] for row in conn.execute("SELECT name FROM log")] == ["0.2_to_0.3"]
