"""Tests for SQLite and MySQL persistence of calculator projects.

The MySQL tests run against the database set by the TEST_DATABASE_URL, TEST_DATABASE_USERNAME and
TEST_DATABASE_PASSWORD environment variables, and are skipped when TEST_DATABASE_URL is not set. Its tables are
dropped before and after each test, so use a database for testing only.
"""

from __future__ import annotations

import os
from contextlib import closing
from typing import TYPE_CHECKING

import pytest
import streamlit as st

from src import database, sql_store
from src.calculator_state import CalculatorState
from src.models import Activity, Person, PersonType

if TYPE_CHECKING:
    from collections.abc import Iterator

    from src.sql_store import Connection

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
    project_id: int = sql_store.save_project(conn, state)
    restored: CalculatorState = sql_store.load_project(conn, project_id)
    assert restored == state
    assert restored.total_cost() == pytest.approx(state.total_cost())
    # Integer inputs stay integers, so the int-bounded Streamlit inputs accept them.
    assert isinstance(restored.peer_reviewer.hourly_rate, int)
    assert restored.activities[-1].get_person() is restored.people["2"]


def test_update_project(conn: Connection) -> None:
    project_id: int = sql_store.save_project(conn, CalculatorState.default())
    state: CalculatorState = modified_state()
    sql_store.update_project(conn, project_id, state)
    assert sql_store.load_project(conn, project_id) == state
    assert len(sql_store.list_projects(conn)) == 1


def test_update_missing_project_raises(conn: Connection) -> None:
    with pytest.raises(KeyError):
        sql_store.update_project(conn, 123, CalculatorState.default())


def test_list_projects(conn: Connection) -> None:
    state: CalculatorState = modified_state()
    project_id: int = sql_store.save_project(conn, state)
    [project] = sql_store.list_projects(conn)
    assert project["id"] == project_id
    assert project["project_name"] == "A study"
    assert project["total_cost"] == pytest.approx(state.total_cost())


def test_delete_project_cascades(conn: Connection) -> None:
    project_id: int = sql_store.save_project(conn, modified_state())
    sql_store.delete_project(conn, project_id)
    assert sql_store.list_projects(conn) == []
    for table in ("people", "activities", "direct_costs"):
        assert count_rows(conn, table) == 0
    with pytest.raises(KeyError):
        sql_store.load_project(conn, project_id)
