"""Tests for SQLite and MySQL persistence of calculator projects.

The MySQL tests run against the database set by the TEST_DATABASE_URL, TEST_DATABASE_USERNAME and
TEST_DATABASE_PASSWORD environment variables, and are skipped when TEST_DATABASE_URL is not set. Its tables are
dropped before and after each test, so use a database for testing only.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Any

import pytest
import streamlit as st

from src import database, sql_store
from src.calculator_state import CalculatorState
from src.models import Activity, Person, PersonType

if TYPE_CHECKING:
    from collections.abc import Iterator

    from src.sql_store import Connection

# The SQLite projects table as it was before the parent_id column was added.
SCHEMA_WITHOUT_PARENT_ID: str = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    public_id VARCHAR(21) NOT NULL UNIQUE,
    schema_version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    user_name TEXT,
    user_country TEXT NOT NULL,
    international_collaborators INTEGER NOT NULL,
    project_name TEXT,
    project_field TEXT NOT NULL,
    tool_step INTEGER NOT NULL,
    total_cost NUMERIC NOT NULL,
    total_hours NUMERIC NOT NULL
);
"""

# Child tables first, as they reference projects.
TABLES: tuple[str, ...] = ("activities", "direct_costs", "people", "projects")


def drop_tables(connection: Connection) -> None:
    with closing(connection.cursor()) as cursor:
        for table in TABLES:
            cursor.execute(f"DROP TABLE IF EXISTS {table}")
    connection.commit()


def count_rows(connection: Connection, table: str) -> int:
    with closing(connection.cursor()) as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        return cursor.fetchone()[0]


@pytest.fixture(params=["sqlite", "mysql"])
def conn(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[Connection]:
    if request.param == "sqlite":
        connection: Connection = sql_store.connect(":memory:")
        yield connection
        connection.close()
        return

    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL is not set.")
    monkeypatch.setattr(st, "secrets", {})
    monkeypatch.setenv(database.DATABASE_TYPE_SECRET, "mysql")
    for secret in (database.DATABASE_URL_SECRET, database.DATABASE_USERNAME_SECRET, database.DATABASE_PASSWORD_SECRET):
        monkeypatch.setenv(secret, os.environ.get(f"TEST_{secret}", ""))
    with closing(database.connect()) as setup:
        drop_tables(setup)
    connection = database.connect()
    yield connection
    drop_tables(connection)
    connection.close()


def modified_state() -> CalculatorState:
    state: CalculatorState = CalculatorState.default()
    state.project_name = "A study"
    state.international_collaborators = True
    second: Person = Person(None, "2", PersonType.RESEARCH_TEAM, 41.2)
    state.people["2"] = second
    state.activities.append(Activity(None, second, "data", 20.5, 11, 11))
    state.direct_costs.pop()
    return state


def test_save_and_load(conn: Connection) -> None:
    state: CalculatorState = modified_state()
    public_id: str = sql_store.save_project(conn, state)
    restored: CalculatorState = sql_store.load_project(conn, public_id)
    assert restored == state
    assert restored.total_cost() == pytest.approx(state.total_cost())
    # Integer inputs stay integers, so the int-bounded Streamlit inputs accept them.
    assert isinstance(restored.peer_reviewer.hourly_rate, int)
    assert restored.activities[-1].get_person() is restored.people["2"]


def test_update_project(conn: Connection) -> None:
    public_id: str = sql_store.save_project(conn, CalculatorState.default())
    state: CalculatorState = modified_state()
    sql_store.update_project(conn, public_id, state)
    assert sql_store.load_project(conn, public_id) == state
    assert len(sql_store.list_projects(conn)) == 1


def test_projects_are_found_by_public_id_only(conn: Connection) -> None:
    public_id: str = sql_store.save_project(conn, CalculatorState.default())
    assert len(public_id) == sql_store.PUBLIC_ID_LENGTH
    assert set(public_id) <= set(sql_store.PUBLIC_ID_ALPHABET)
    [project] = sql_store.list_projects(conn)
    with pytest.raises(KeyError):
        sql_store.load_project(conn, str(project["id"]))


def test_save_project_with_parent(conn: Connection) -> None:
    parent_public_id: str = sql_store.save_project(conn, CalculatorState.default())
    state: CalculatorState = modified_state()
    child_public_id: str = sql_store.save_project(conn, state, parent_public_id)
    projects = {project["public_id"]: project for project in sql_store.list_projects(conn)}
    assert projects[child_public_id]["parent_id"] == projects[parent_public_id]["id"]
    assert projects[parent_public_id]["parent_id"] is None
    assert sql_store.load_project(conn, child_public_id) == state
    assert sql_store.load_project(conn, parent_public_id) == CalculatorState.default()


def test_save_project_with_missing_parent_has_no_parent(conn: Connection) -> None:
    sql_store.save_project(conn, CalculatorState.default(), "missing")
    [project] = sql_store.list_projects(conn)
    assert project["parent_id"] is None


def test_deleting_parent_keeps_child(conn: Connection) -> None:
    parent_public_id: str = sql_store.save_project(conn, CalculatorState.default())
    child_public_id: str = sql_store.save_project(conn, modified_state(), parent_public_id)
    sql_store.delete_project(conn, parent_public_id)
    [project] = sql_store.list_projects(conn)
    assert project["public_id"] == child_public_id
    assert project["parent_id"] is None


def test_init_db_adds_parent_id_to_existing_table() -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        # The projects table as created before parent_id was added.
        connection.executescript(SCHEMA_WITHOUT_PARENT_ID)
        sql_store.init_db(connection)
        parent_public_id: str = sql_store.save_project(connection, CalculatorState.default())
        sql_store.save_project(connection, modified_state(), parent_public_id)
        assert [project["parent_id"] is None for project in sql_store.list_projects(connection)] == [False, True]


def test_update_missing_project_raises(conn: Connection) -> None:
    with pytest.raises(KeyError):
        sql_store.update_project(conn, "missing", CalculatorState.default())


def test_list_projects(conn: Connection) -> None:
    state: CalculatorState = modified_state()
    public_id: str = sql_store.save_project(conn, state)
    [project] = sql_store.list_projects(conn)
    assert project["public_id"] == public_id
    assert project["project_name"] == "A study"
    assert project["total_cost"] == pytest.approx(state.total_cost())


def test_load_projects(conn: Connection) -> None:
    assert sql_store.load_projects(conn) == []
    first_public_id: str = sql_store.save_project(conn, CalculatorState.default())
    state: CalculatorState = modified_state()
    second_public_id: str = sql_store.save_project(conn, state)
    projects: list[tuple[dict[str, Any], CalculatorState]] = sql_store.load_projects(conn)
    # Most recently created first, each with its own people, activities and direct costs.
    assert [project["public_id"] for project, _ in projects] == [second_public_id, first_public_id]
    assert [loaded for _, loaded in projects] == [state, CalculatorState.default()]


def test_delete_project_cascades(conn: Connection) -> None:
    public_id: str = sql_store.save_project(conn, modified_state())
    sql_store.delete_project(conn, public_id)
    assert sql_store.list_projects(conn) == []
    for table in ("people", "activities", "direct_costs"):
        assert count_rows(conn, table) == 0
    with pytest.raises(KeyError):
        sql_store.load_project(conn, public_id)
