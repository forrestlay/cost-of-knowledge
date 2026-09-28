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


def test_save_button_saves_then_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(database.DATABASE_TYPE_SECRET, "sqlite")
    at: AppTest = AppTest.from_file(MAIN, default_timeout=30)
    run(at)

    next(button for button in at.button if button.label == "Save your result to share").click()
    run(at)
    project_id: int = at.session_state["database_project_id"]
    next(field for field in at.text_input if field.label == "Name of your paper/project").set_value("Renamed project")
    next(button for button in at.button if button.label == "Save your result to share").click()
    run(at)

    assert at.session_state["database_project_id"] == project_id
    with closing(database.connect()) as conn:
        projects = sql_store.list_projects(conn)
    assert [(project["id"], project["project_name"]) for project in projects] == [(project_id, "Renamed project")]


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
    project_id: int = at.session_state["database_project_id"]
    [copy_link] = copy_link_buttons(at)
    assert copy_link["label"] == "Copy link to saved result"
    assert copy_link["url"].endswith(f"?project_id={project_id}")


def test_query_param_loads_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(database.DATABASE_TYPE_SECRET, "sqlite")
    state: CalculatorState = CalculatorState.default()
    state.project_name = "Saved project"
    state.user_name = "Ada"
    with closing(database.connect()) as conn:
        project_id: int = sql_store.save_project(conn, state)

    at: AppTest = AppTest.from_file(MAIN, default_timeout=30)
    at.query_params["project_id"] = str(project_id)
    run(at)
    assert at.session_state["database_project_id"] == project_id
    assert at.text_input(key="user_name_input").value == "Ada"
    assert at.session_state["project_name"] == "Saved project"

    # Edits must survive reruns rather than being replaced by the saved project again.
    next(field for field in at.text_input if field.label == "Name of your paper/project").set_value("Edited")
    run(at)
    assert at.session_state["project_name"] == "Edited"


@pytest.mark.parametrize("project_id", ["999", "not-a-number"])
def test_query_param_with_unknown_project_keeps_defaults(monkeypatch: pytest.MonkeyPatch, project_id: str) -> None:
    monkeypatch.setenv(database.DATABASE_TYPE_SECRET, "sqlite")
    at: AppTest = AppTest.from_file(MAIN, default_timeout=30)
    at.query_params["project_id"] = project_id
    run(at)
    assert "database_project_id" not in at.session_state
    assert at.toast[0].value.startswith("Could not load the project")


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
    project_id: int = at.session_state["database_project_id"]
    after: list[str] = [button.proto.url for button in at.get("link_button") if button.proto.label in share_labels]
    assert len(after) == len(share_labels)
    assert all(f"?project_id={project_id}" in unquote(url) for url in after)
