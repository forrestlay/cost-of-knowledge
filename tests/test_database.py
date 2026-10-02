"""Tests for reading the database configuration and saving from the app."""

from __future__ import annotations

import json
from contextlib import closing
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

import pymysql
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from test_app import MAIN, run

from src import database, sql_store
from src.calculator_state import CalculatorState
from src.reference_data import RESEARCH_PHASES

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Ignores any local secrets and environment variables, and puts the SQLite database in a temporary folder."""
    monkeypatch.setattr(st, "secrets", {})
    for secret in (
        database.DATABASE_TYPE_SECRET,
        database.DATABASE_URL_SECRET,
        database.DATABASE_USERNAME_SECRET,
        database.DATABASE_PASSWORD_SECRET,
    ):
        monkeypatch.delenv(secret, raising=False)
    database_file: Path = tmp_path / "data" / "test.db"
    monkeypatch.setattr(database, "SQLITE_DATABASE_FILE", database_file)
    database.init_database.clear()
    yield database_file
    database.init_database.clear()


def test_database_type_defaults_to_none() -> None:
    assert database.get_database_type() == "none"


@pytest.mark.parametrize(("value", "expected"), [("sqlite", "sqlite"), (" MySQL ", "mysql"), ("", "none")])
def test_database_type_from_environment(monkeypatch: pytest.MonkeyPatch, value: str, expected: str) -> None:
    monkeypatch.setenv(database.DATABASE_TYPE_SECRET, value)
    assert database.get_database_type() == expected


def test_database_type_secret_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(st, "secrets", {database.DATABASE_TYPE_SECRET: "sqlite"})
    monkeypatch.setenv(database.DATABASE_TYPE_SECRET, "none")
    assert database.get_database_type() == "sqlite"


def test_unsupported_database_type_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(database.DATABASE_TYPE_SECRET, "postgres")
    with pytest.raises(ValueError, match="postgres"):
        database.get_database_type()


def test_init_database_creates_sqlite_file(monkeypatch: pytest.MonkeyPatch, isolated_database: Path) -> None:
    monkeypatch.setenv(database.DATABASE_TYPE_SECRET, "sqlite")
    assert database.init_database() == "sqlite"
    assert isolated_database.exists()
    with closing(database.connect()) as conn:
        assert sql_store.list_projects(conn) == []


def test_init_database_none_creates_nothing(isolated_database: Path) -> None:
    assert database.init_database() == "none"
    assert not isolated_database.exists()


def test_save_button_hidden_without_database() -> None:
    at: AppTest = AppTest.from_file(MAIN, default_timeout=30).run()
    assert not [button for button in at.button if button.label == "Save your result to share"]


def click_save(at: AppTest) -> None:
    next(button for button in at.button if button.label == "Save your result to share").click()
    run(at)


def test_save_button_saves_changes_as_child_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(database.DATABASE_TYPE_SECRET, "sqlite")
    at: AppTest = AppTest.from_file(MAIN, default_timeout=30)
    run(at)

    click_save(at)
    public_id: str = at.session_state["database_public_id"]
    next(box for box in at.selectbox if box.label.startswith("Field of research")).set_value("4601")
    run(at)
    click_save(at)
    child_public_id: str = at.session_state["database_public_id"]

    assert child_public_id != public_id
    with closing(database.connect()) as conn:
        projects = {project["public_id"]: project for project in sql_store.list_projects(conn)}
        original: CalculatorState = sql_store.load_project(conn, public_id)
        child: CalculatorState = sql_store.load_project(conn, child_public_id)
    assert projects.keys() == {public_id, child_public_id}
    assert original.project_field != "4601"
    assert child.project_field == "4601"
    assert projects[child_public_id]["parent_id"] == projects[public_id]["id"]
    assert projects[public_id]["parent_id"] is None


def test_save_button_without_changes_keeps_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(database.DATABASE_TYPE_SECRET, "sqlite")
    at: AppTest = AppTest.from_file(MAIN, default_timeout=30)
    run(at)

    click_save(at)
    public_id: str = at.session_state["database_public_id"]
    click_save(at)

    assert at.session_state["database_public_id"] == public_id
    with closing(database.connect()) as conn:
        assert [project["public_id"] for project in sql_store.list_projects(conn)] == [public_id]


def copy_link_buttons(at: AppTest) -> list[dict[str, str]]:
    """Returns the data of each copy link button custom component in the app."""
    return [
        json.loads(element.proto.json)
        for element in at.get("bidi_component")
        if element.proto.component_name == "copy_link_button"
    ]


def test_copy_link_button_shown_after_save(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(database.DATABASE_TYPE_SECRET, "sqlite")
    at: AppTest = AppTest.from_file(MAIN, default_timeout=30)
    run(at)
    assert not copy_link_buttons(at)

    next(button for button in at.button if button.label == "Save your result to share").click()
    run(at)
    public_id: str = at.session_state["database_public_id"]
    [copy_link] = copy_link_buttons(at)
    assert copy_link["label"] == "Copy link to saved result"
    assert copy_link["url"].endswith(f"?project_id={public_id}")


def run_results_page(at: AppTest) -> None:
    """Runs the app and switches to the results page, clearing its cached results from any earlier test."""
    st.cache_data.clear()
    run(at)
    at.switch_page("app_pages/admin.py")
    run(at)


def test_results_page_without_database() -> None:
    at: AppTest = AppTest.from_file(MAIN, default_timeout=30)
    run_results_page(at)
    assert at.title[0].value == "Saved results"
    assert at.info[0].value.startswith("No database is configured")
    assert not at.dataframe


def test_results_page_lists_saved_projects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(database.DATABASE_TYPE_SECRET, "sqlite")
    state: CalculatorState = CalculatorState.default()
    state.user_country = "gb"
    state.international_collaborators = True
    state.peer_review.review_rounds = 2
    state.peer_review.journal_submissions = 3
    with closing(database.connect()) as conn:
        public_id: str = sql_store.save_project(conn, state)

    at: AppTest = AppTest.from_file(MAIN, default_timeout=30)
    run_results_page(at)
    # The calculator's widgets are not rendered on the results page.
    assert not at.metric
    [row] = at.dataframe[0].value.to_dict("records")
    summary: dict[str, Any] = state.summary(RESEARCH_PHASES)
    assert row == {
        "Link": f"./result?project_id={public_id}",
        "Saved": row["Saved"],
        "Country": "United Kingdom",
        "International collaboration": True,
        "Field": "Commerce, management, tourism and services/Accounting, auditing and accountability",
        "Peer reviews": 2,
        "Journal submissions": 3,
        "Currency": "GBP",
        **{label: round(summary["phase_costs"][label]) for label in RESEARCH_PHASES.values()},
        "Total": round(summary["total_cost"]),
    }


def capture_mysql_connect(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replaces pymysql.connect with a stub that records its arguments."""
    arguments: dict[str, Any] = {}

    def fake_connect(**kwargs: Any) -> None:
        arguments.update(kwargs)

    monkeypatch.setattr(pymysql, "connect", fake_connect)
    return arguments


def test_mysql_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    arguments: dict[str, Any] = capture_mysql_connect(monkeypatch)
    monkeypatch.setenv(database.DATABASE_URL_SECRET, "mysql://db.example.org:3307/cost_of_knowledge")
    monkeypatch.setenv(database.DATABASE_USERNAME_SECRET, "calculator")
    monkeypatch.setenv(database.DATABASE_PASSWORD_SECRET, "p@ss:word")
    database._mysql_connect()
    assert (
        arguments.items()
        >= {
            "host": "db.example.org",
            "port": 3307,
            "user": "calculator",
            "password": "p@ss:word",
            "database": "cost_of_knowledge",
        }.items()
    )


def test_mysql_secrets_take_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    arguments: dict[str, Any] = capture_mysql_connect(monkeypatch)
    monkeypatch.setattr(
        st,
        "secrets",
        {database.DATABASE_URL_SECRET: "mysql://secret-host/secret_db", database.DATABASE_USERNAME_SECRET: "secret"},
    )
    monkeypatch.setenv(database.DATABASE_URL_SECRET, "mysql://env-host/env_db")
    monkeypatch.setenv(database.DATABASE_USERNAME_SECRET, "env")
    database._mysql_connect()
    assert (arguments["host"], arguments["port"], arguments["database"], arguments["user"]) == (
        "secret-host",
        database.MYSQL_DEFAULT_PORT,
        "secret_db",
        "secret",
    )
    assert arguments["password"] == ""


def test_mysql_credentials_fall_back_to_url(monkeypatch: pytest.MonkeyPatch) -> None:
    arguments: dict[str, Any] = capture_mysql_connect(monkeypatch)
    monkeypatch.setenv(database.DATABASE_URL_SECRET, "mysql://url-user:p%40ss@localhost/db")
    database._mysql_connect()
    assert (arguments["user"], arguments["password"]) == ("url-user", "p@ss")


@pytest.mark.parametrize(
    ("url", "username", "message"),
    [
        (None, "user", database.DATABASE_URL_SECRET),
        ("localhost/db", "user", "mysql://host"),
        ("mysql://localhost", "user", "mysql://host"),
        ("mysql://localhost/db", None, database.DATABASE_USERNAME_SECRET),
    ],
)
def test_mysql_invalid_settings_raise(
    monkeypatch: pytest.MonkeyPatch, url: str | None, username: str | None, message: str
) -> None:
    capture_mysql_connect(monkeypatch)
    if url:
        monkeypatch.setenv(database.DATABASE_URL_SECRET, url)
    if username:
        monkeypatch.setenv(database.DATABASE_USERNAME_SECRET, username)
    with pytest.raises(ValueError, match=message):
        database._mysql_connect()


def test_share_buttons_link_to_saved_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(database.DATABASE_TYPE_SECRET, "sqlite")
    at: AppTest = AppTest.from_file(MAIN, default_timeout=30)
    run(at)
    share_labels: set[str] = {"Share on LinkedIn", "Share on X", "Share on Facebook", "Share via email"}
    before: list[str] = [button.proto.url for button in at.get("link_button") if button.proto.label in share_labels]
    assert len(before) == len(share_labels)
    assert not [url for url in before if "project_id" in unquote(url)]

    next(button for button in at.button if button.label == "Save your result to share").click()
    run(at)
    public_id: str = at.session_state["database_public_id"]
    after: list[str] = [button.proto.url for button in at.get("link_button") if button.proto.label in share_labels]
    assert len(after) == len(share_labels)
    assert all(f"?project_id={public_id}" in unquote(url) for url in after)


def run_result_page(at: AppTest, public_id: str | None) -> None:
    """Runs the app and switches to the result page, with the public id in its query parameter if given."""
    run(at)
    at.switch_page("app_pages/result.py")
    if public_id is not None:
        at.query_params[database.PROJECT_ID_QUERY_PARAM] = public_id
    run(at)


def test_result_page_shows_saved_result_without_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(database.DATABASE_TYPE_SECRET, "sqlite")
    state: CalculatorState = CalculatorState.default()
    state.user_country = "gb"
    with closing(database.connect()) as conn:
        public_id: str = sql_store.save_project(conn, state)

    at: AppTest = AppTest.from_file(MAIN, default_timeout=30)
    run_result_page(at, public_id)
    assert not at.exception
    assert [metric.label for metric in at.metric] == ["Estimated total cost", "Estimated direct costs"]
    assert at.metric[0].value.startswith("£")
    # Hours must be absent from the charts' data, which is sent to the browser, and from the image.
    charts: list[str] = [chart.proto.spec for chart in at.get("plotly_chart")]
    assert charts
    assert not [spec for spec in charts if "Hours" in spec or "hours" in spec]
    assert not [image for image in at.get("imgs") if "hours" in str(image.proto).lower()]
    # The buttons back to the calculator must not carry the result's id, so the calculator starts blank.
    buttons = at.get("link_button")
    assert buttons
    assert not [button for button in buttons if "project_id" in button.proto.url]


def test_result_page_with_unknown_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(database.DATABASE_TYPE_SECRET, "sqlite")
    at: AppTest = AppTest.from_file(MAIN, default_timeout=30)
    run_result_page(at, "does-not-exist")
    assert at.error[0].value.startswith("There is no result with id")
    assert not at.metric


def test_result_page_without_id() -> None:
    at: AppTest = AppTest.from_file(MAIN, default_timeout=30)
    run_result_page(at, None)
    assert at.info[0].value == "No result was chosen."
