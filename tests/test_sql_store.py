"""Tests for SQLite and MySQL persistence of calculator projects.

The MySQL tests run against the database set by the TEST_DATABASE_URL, TEST_DATABASE_USERNAME and
TEST_DATABASE_PASSWORD environment variables, and are skipped when TEST_DATABASE_URL is not set. Its tables are
dropped before and after each test, so use a database for testing only.
"""

from __future__ import annotations

import os
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

# Stands in for main.COST_OF_KNOWLEDGE_VERSION, which cannot be imported as main.py is a script.
COST_OF_KNOWLEDGE_VERSION: str = "0.1.2"

# Child tables first, as they reference projects.
TABLES: tuple[str, ...] = (
    "activities",
    "simplified_hours",
    "simplified_direct_costs",
    "direct_costs",
    "people",
    "projects",
    "admin_users",
)


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


def default_with_researcher() -> CalculatorState:
    """The default state with one researcher, as the calculator has once one has been added."""
    state: CalculatorState = CalculatorState.default()
    state.people["1"] = Person("1", PersonType.RESEARCH_TEAM, 85)
    return state


def modified_state() -> CalculatorState:
    state: CalculatorState = default_with_researcher().with_default_costs()
    state.international_collaborators = True
    state.indirect_cost_percentage = 55
    second: Person = Person("2", PersonType.RESEARCH_TEAM, 41.2, "research_scientist", 3)
    state.people["2"] = second
    state.activities.append(Activity(None, second, "data", 20.5, 11, 11))
    state.direct_costs.pop()
    return state


def test_save_and_load(conn: Connection) -> None:
    state: CalculatorState = modified_state()
    public_id: str = sql_store.save_project(conn, state, COST_OF_KNOWLEDGE_VERSION)
    restored: CalculatorState = sql_store.load_project(conn, public_id)
    assert restored == state
    assert restored.total_cost() == pytest.approx(state.total_cost())
    # Integer inputs stay integers, so the int-bounded Streamlit inputs accept them.
    assert isinstance(restored.peer_reviewer.hourly_rate, int)
    assert restored.activities[-1].get_person() is restored.people["2"]


def test_update_project(conn: Connection) -> None:
    public_id: str = sql_store.save_project(conn, CalculatorState.default(), COST_OF_KNOWLEDGE_VERSION)
    state: CalculatorState = modified_state()
    sql_store.update_project(conn, public_id, state, COST_OF_KNOWLEDGE_VERSION)
    assert sql_store.load_project(conn, public_id) == state
    assert len(sql_store.list_projects(conn)) == 1


def test_projects_are_found_by_public_id_only(conn: Connection) -> None:
    public_id: str = sql_store.save_project(conn, CalculatorState.default(), COST_OF_KNOWLEDGE_VERSION)
    assert len(public_id) == sql_store.PUBLIC_ID_LENGTH
    assert set(public_id) <= set(sql_store.PUBLIC_ID_ALPHABET)
    [project] = sql_store.list_projects(conn)
    with pytest.raises(KeyError):
        sql_store.load_project(conn, str(project["id"]))


def test_save_and_update_record_tool_version(conn: Connection) -> None:
    public_id: str = sql_store.save_project(conn, CalculatorState.default(), COST_OF_KNOWLEDGE_VERSION)
    [project] = sql_store.list_projects(conn)
    assert project["version"] == COST_OF_KNOWLEDGE_VERSION
    assert "parent_id" not in project

    sql_store.update_project(conn, public_id, modified_state(), "0.1.3")
    [project] = sql_store.list_projects(conn)
    assert project["version"] == "0.1.3"


def test_save_and_load_simplified_estimates(conn: Connection) -> None:
    state: CalculatorState = default_with_researcher()
    state.people["2"] = Person("2", PersonType.RESEARCH_TEAM, 40)
    state.simplified_hours = {"incubation": {"1": 286, "2": 12.5}, "data": {"1": 266.5}}
    state.simplified_direct_costs = {"data": 250.5, "writing": 3400}
    public_id: str = sql_store.save_project(conn, state, COST_OF_KNOWLEDGE_VERSION)
    restored: CalculatorState = sql_store.load_project(conn, public_id)
    assert restored == state
    assert restored.calculator_mode == "simplified"
    assert restored.total_hours() == 286 + 12.5 + 266.5 + 23
    assert restored.total_cost() == pytest.approx((286 + 266.5 + 23) * 85 + 12.5 * 40 + 250.5 + 3400)

    # Detailed mode ignores the simplified estimates, which are kept.
    state.calculator_mode = "detailed"
    sql_store.update_project(conn, public_id, state, COST_OF_KNOWLEDGE_VERSION)
    restored = sql_store.load_project(conn, public_id)
    assert restored == state
    assert restored.total_hours() == 23


def test_loaded_alam_defaults_saved_for_detailed_projects_only(conn: Connection) -> None:
    def stored_flag() -> int | None:
        return sql_store.load_projects(conn)[0][0]["loaded_alam_defaults"]

    state: CalculatorState = modified_state()
    state.calculator_mode = "detailed"
    public_id: str = sql_store.save_project(conn, state, COST_OF_KNOWLEDGE_VERSION)
    assert stored_flag() == 0
    sql_store.update_project(conn, public_id, state, COST_OF_KNOWLEDGE_VERSION, loaded_alam_defaults=True)
    assert stored_flag() == 1

    state.calculator_mode = "simplified"
    sql_store.update_project(conn, public_id, state, COST_OF_KNOWLEDGE_VERSION, loaded_alam_defaults=True)
    assert stored_flag() is None


def test_update_missing_project_raises(conn: Connection) -> None:
    with pytest.raises(KeyError):
        sql_store.update_project(conn, "missing", CalculatorState.default(), COST_OF_KNOWLEDGE_VERSION)


def test_list_projects(conn: Connection) -> None:
    state: CalculatorState = modified_state()
    public_id: str = sql_store.save_project(conn, state, COST_OF_KNOWLEDGE_VERSION)
    [project] = sql_store.list_projects(conn)
    assert project["public_id"] == public_id
    assert project["total_cost"] == pytest.approx(state.total_cost())


def test_load_projects(conn: Connection) -> None:
    assert sql_store.load_projects(conn) == []
    first_public_id: str = sql_store.save_project(conn, CalculatorState.default(), COST_OF_KNOWLEDGE_VERSION)
    state: CalculatorState = modified_state()
    second_public_id: str = sql_store.save_project(conn, state, COST_OF_KNOWLEDGE_VERSION)
    projects: list[tuple[dict[str, Any], CalculatorState]] = sql_store.load_projects(conn)
    # Most recently created first, each with its own people, activities and direct costs.
    assert [project["public_id"] for project, _ in projects] == [second_public_id, first_public_id]
    assert [loaded for _, loaded in projects] == [state, CalculatorState.default()]


def test_load_projects_pages(conn: Connection) -> None:
    states: list[CalculatorState] = [modified_state() if index % 2 else CalculatorState.default() for index in range(5)]
    public_ids: list[str] = [sql_store.save_project(conn, state, COST_OF_KNOWLEDGE_VERSION) for state in states]
    assert sql_store.count_projects(conn) == 5
    everything = sql_store.load_projects(conn)
    pages = [sql_store.load_projects(conn, 2, offset) for offset in (0, 2, 4)]
    assert [len(page) for page in pages] == [2, 2, 1]
    assert [project["public_id"] for page in pages for project, _ in page] == list(reversed(public_ids))
    assert [pair for page in pages for pair in page] == everything
    assert sql_store.load_projects(conn, 2, 10) == []


def test_load_projects_rejects_bad_page(conn: Connection) -> None:
    with pytest.raises(ValueError, match="limit"):
        sql_store.load_projects(conn, 0)
    with pytest.raises(ValueError, match="limit"):
        sql_store.load_projects(conn, 5, -1)


def test_delete_project_cascades(conn: Connection) -> None:
    public_id: str = sql_store.save_project(conn, modified_state(), COST_OF_KNOWLEDGE_VERSION)
    sql_store.delete_project(conn, public_id)
    assert sql_store.list_projects(conn) == []
    for table in ("people", "activities", "direct_costs"):
        assert count_rows(conn, table) == 0
    with pytest.raises(KeyError):
        sql_store.load_project(conn, public_id)


def test_first_admin_login_is_authorised_owner(conn: Connection) -> None:
    first: dict[str, Any] = sql_store.record_admin_login(conn, "iss#1", "a@example.org", "A")
    second: dict[str, Any] = sql_store.record_admin_login(conn, "iss#2", "b@example.org", "B")
    assert (first["is_owner"], first["is_authorised"]) == (True, True)
    assert (second["is_owner"], second["is_authorised"]) == (False, False)
    assert [user["user_id"] for user in sql_store.list_admin_users(conn)] == ["iss#1", "iss#2"]


def test_admin_login_again_keeps_authorisation(conn: Connection) -> None:
    sql_store.record_admin_login(conn, "iss#1", "a@example.org", "A")
    sql_store.record_admin_login(conn, "iss#2", "b@example.org", "B")
    again: dict[str, Any] = sql_store.record_admin_login(conn, "iss#1", "new@example.org", "A2")
    assert (again["email"], again["name"], again["is_owner"], again["is_authorised"]) == (
        "new@example.org",
        "A2",
        True,
        True,
    )
    assert len(sql_store.list_admin_users(conn)) == 2


def test_authorise_admin_user(conn: Connection) -> None:
    sql_store.record_admin_login(conn, "iss#1", None, None)
    sql_store.record_admin_login(conn, "iss#2", None, None)
    sql_store.authorise_admin_user(conn, "iss#2")
    sql_store.authorise_admin_user(conn, "iss#2")
    second: dict[str, Any] = sql_store.record_admin_login(conn, "iss#2", None, None)
    assert (second["is_owner"], second["is_authorised"]) == (False, True)
    assert second["authorised_at"] is not None
    with pytest.raises(KeyError):
        sql_store.authorise_admin_user(conn, "iss#3")


def test_set_admin_owner(conn: Connection) -> None:
    sql_store.record_admin_login(conn, "iss#1", None, None)
    sql_store.record_admin_login(conn, "iss#2", None, None)
    sql_store.set_admin_owner(conn, "iss#2")
    first, second = sql_store.list_admin_users(conn)[::-1]
    assert (first["user_id"], first["is_owner"], first["is_authorised"]) == ("iss#1", False, True)
    assert (second["user_id"], second["is_owner"], second["is_authorised"]) == ("iss#2", True, True)
    with pytest.raises(KeyError):
        sql_store.set_admin_owner(conn, "iss#3")


def test_delete_admin_user(conn: Connection) -> None:
    sql_store.record_admin_login(conn, "iss#1", None, None)
    sql_store.record_admin_login(conn, "iss#2", None, None)
    with pytest.raises(ValueError, match="owner"):
        sql_store.delete_admin_user(conn, "iss#1")
    sql_store.delete_admin_user(conn, "iss#2")
    assert [user["user_id"] for user in sql_store.list_admin_users(conn)] == ["iss#1"]
    with pytest.raises(KeyError):
        sql_store.delete_admin_user(conn, "iss#2")


def test_save_rejects_oversize_text(conn: Connection) -> None:
    state: CalculatorState = default_with_researcher()
    state.activities[0].name = "x" * (sql_store.MAX_TEXT_LENGTH + 1)
    with pytest.raises(ValueError, match="too long"):
        sql_store.save_project(conn, state, COST_OF_KNOWLEDGE_VERSION)
    assert count_rows(conn, "projects") == 0


def test_save_rejects_negative_or_huge_numbers(conn: Connection) -> None:
    state: CalculatorState = default_with_researcher()
    state.peer_reviewer.hourly_rate = -1
    with pytest.raises(ValueError, match="outside"):
        sql_store.save_project(conn, state, COST_OF_KNOWLEDGE_VERSION)


def test_unknown_table_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown table"):
        sql_store._check_table("projects; DROP TABLE projects")


def test_is_admin_owner(conn: Connection) -> None:
    sql_store.record_admin_login(conn, "a", "a@example.com", "A")
    sql_store.record_admin_login(conn, "b", "b@example.com", "B")
    assert sql_store.is_admin_owner(conn, "a")
    assert not sql_store.is_admin_owner(conn, "b")
    assert not sql_store.is_admin_owner(conn, "missing")


def test_owner_email_restricts_first_owner(conn: Connection) -> None:
    other = sql_store.record_admin_login(conn, "x", "x@example.com", "X", owner_email="boss@example.com")
    assert not other["is_owner"]
    unverified = sql_store.record_admin_login(
        conn, "y", "boss@example.com", "Y", owner_email="boss@example.com", email_verified=False
    )
    assert not unverified["is_owner"]
    boss = sql_store.record_admin_login(conn, "z", "Boss@Example.com", "Z", owner_email="boss@example.com")
    assert boss["is_owner"]
    assert boss["is_authorised"]
