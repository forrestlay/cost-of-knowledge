"""Tests for SQLite persistence of calculator projects."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import sql_store
from calculator_state import CalculatorState
from models import Activity, Person, PersonType

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection: sqlite3.Connection = sql_store.connect(":memory:")
    yield connection
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


def test_save_and_load(conn: sqlite3.Connection) -> None:
    state: CalculatorState = modified_state()
    project_id: int = sql_store.save_project(conn, state)
    restored: CalculatorState = sql_store.load_project(conn, project_id)
    assert restored == state
    assert restored.total_cost() == pytest.approx(state.total_cost())
    # Integer inputs stay integers, so the int-bounded Streamlit inputs accept them.
    assert isinstance(restored.peer_reviewer.hourly_rate, int)
    assert restored.activities[-1].get_person() is restored.people["2"]


def test_update_project(conn: sqlite3.Connection) -> None:
    project_id: int = sql_store.save_project(conn, CalculatorState.default())
    state: CalculatorState = modified_state()
    sql_store.update_project(conn, project_id, state)
    assert sql_store.load_project(conn, project_id) == state
    assert len(sql_store.list_projects(conn)) == 1


def test_update_missing_project_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(KeyError):
        sql_store.update_project(conn, 123, CalculatorState.default())


def test_list_projects(conn: sqlite3.Connection) -> None:
    state: CalculatorState = modified_state()
    project_id: int = sql_store.save_project(conn, state)
    [project] = sql_store.list_projects(conn)
    assert project["id"] == project_id
    assert project["project_name"] == "A study"
    assert project["total_cost"] == pytest.approx(state.total_cost())


def test_delete_project_cascades(conn: sqlite3.Connection) -> None:
    project_id: int = sql_store.save_project(conn, modified_state())
    sql_store.delete_project(conn, project_id)
    assert sql_store.list_projects(conn) == []
    for table in ("people", "activities", "direct_costs"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)
    with pytest.raises(KeyError):
        sql_store.load_project(conn, project_id)
