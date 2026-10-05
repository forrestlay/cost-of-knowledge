"""Runs the database migrations in src/migrations that the configured database has not had yet.

Each migration is a file named "<from version>_to_<to version>_migration.py" with a migrate(conn) function taking a
sqlite3 or PyMySQL connection. Migrations run in order of the tool version they migrate from, and each one that runs is
recorded in the schema_migrations table so it is not run again.

A database without a projects table is new. Its tables are created with the current schema, which needs no migrations,
so every migration is recorded as applied without running. A database created before migrations were recorded has
every migration run against it, so each migration must check whether it is needed and do nothing if not.

Run it before starting the tool, against the database configured by DATABASE_TYPE (see src/database.py):

    uv run python -m src.migrate

Copyright 2026 Nurul Alam, Ben Lay

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from __future__ import annotations

import importlib.util
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

from src import sql_store

if TYPE_CHECKING:
    from types import ModuleType

    from src.sql_store import Connection

MIGRATIONS_DIR: Path = Path(__file__).parent / "migrations"
MIGRATION_FILE_PATTERN: re.Pattern[str] = re.compile(
    r"^(?P<from_version>\d+(?:\.\d+)*)_to_(?P<to_version>\d+(?:\.\d+)*)_migration\.py$"
)

MIGRATIONS_TABLE_SCHEMA: str = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    -- File name of the migration without its extension, e.g. '0.1_to_0.1.2_migration'.
    name VARCHAR(255) PRIMARY KEY,
    applied_at VARCHAR(32) NOT NULL
)
"""


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def find_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[Path]:
    """Returns the migration files in a directory, in order of the version they migrate from and then to.

    Files whose names do not match "<from version>_to_<to version>_migration.py" are ignored.
    """
    migrations: list[tuple[tuple[int, ...], tuple[int, ...], Path]] = []
    for path in migrations_dir.glob("*_migration.py"):
        match: re.Match[str] | None = MIGRATION_FILE_PATTERN.match(path.name)
        if match is not None:
            migrations.append(
                (_version_key(match["from_version"]), _version_key(match["to_version"]), path),
            )
    return [path for _, _, path in sorted(migrations)]


def load_migration(path: Path) -> ModuleType:
    """Imports a migration file, as names such as "0.1_to_0.1.2_migration" are not valid module names."""
    spec = importlib.util.spec_from_file_location(f"src.migrations.{path.stem.replace('.', '_')}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load the migration {path}.")
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _has_projects_table(conn: Connection) -> bool:
    with closing(conn.cursor()) as cursor:
        if isinstance(conn, sqlite3.Connection):
            cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'projects'")
        else:
            cursor.execute(
                "SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projects'"
            )
        return cursor.fetchone() is not None


def _applied_migrations(conn: Connection) -> set[str]:
    with closing(conn.cursor()) as cursor:
        cursor.execute(MIGRATIONS_TABLE_SCHEMA)
        conn.commit()
        cursor.execute("SELECT name FROM schema_migrations")
        return {row[0] for row in cursor.fetchall()}


def _record_migration(conn: Connection, name: str) -> None:
    with sql_store._transaction(conn) as cursor:
        cursor.execute(
            sql_store._sql(conn, "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)"),
            (name, sql_store._now()),
        )


def run_migrations(conn: Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Runs the migrations that the database has not had yet, then creates any missing tables.

    Args:
        conn: Connection to the database, opened without creating its tables.
        migrations_dir: Directory holding the migration files.

    Returns:
        The names of the migrations that were run, in the order they ran.
    """
    migrations: list[Path] = find_migrations(migrations_dir)
    is_new: bool = not _has_projects_table(conn)
    applied: set[str] = _applied_migrations(conn)
    ran: list[str] = []
    for path in migrations:
        if path.stem in applied:
            continue
        if not is_new:
            load_migration(path).migrate(conn)
            ran.append(path.stem)
        _record_migration(conn, path.stem)
    sql_store.init_db(conn)
    return ran


def main() -> None:
    from src import database

    database_type: database.DatabaseType = database.get_database_type()
    if database_type == "none":
        print(f"No database configured by {database.DATABASE_TYPE_SECRET}, so there is nothing to migrate.")
        return
    with closing(database.connect_without_init()) as conn:
        ran: list[str] = run_migrations(conn)
    if ran:
        print(f"Ran database migrations: {', '.join(ran)}.")
    else:
        print("The database is up to date, no migrations were needed.")


if __name__ == "__main__":
    main()
