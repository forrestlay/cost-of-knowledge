"""Database configuration for saving Cost of Knowledge calculator projects.

The database backend is chosen by the DATABASE_TYPE Streamlit secret in .streamlit/secrets.toml, or failing that by
the DATABASE_TYPE environment variable. It may be "none" (the default, saving is disabled), "sqlite" or "mysql".

A MySQL database is set by DATABASE_URL, in the form mysql://host[:port]/database, with the DATABASE_USERNAME and
DATABASE_PASSWORD settings, each also read from Streamlit secrets or failing that from environment variables.

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

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast, get_args
from urllib.parse import SplitResult, unquote, urlsplit

import pymysql
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from src import sql_store

if TYPE_CHECKING:
    from src.sql_store import Connection

DatabaseType = Literal["none", "sqlite", "mysql"]

DATABASE_TYPE_SECRET: str = "DATABASE_TYPE"
DATABASE_URL_SECRET: str = "DATABASE_URL"
DATABASE_USERNAME_SECRET: str = "DATABASE_USERNAME"
DATABASE_PASSWORD_SECRET: str = "DATABASE_PASSWORD"
SQLITE_DATABASE_FILE: Path = Path(__file__).parent.parent / "data" / "cost_of_knowledge.db"
MYSQL_DEFAULT_PORT: int = 3306

# Query parameter of the calculator holding the public id of a project saved to the database, e.g.
# ?project_id=V1StGXR8_Z5jdHi6B-myT, which is loaded on page load.
PROJECT_ID_QUERY_PARAM: str = "project_id"

# Errors raised by the database drivers when a database cannot be reached or a query fails.
DATABASE_ERRORS: tuple[type[Exception], ...] = (sqlite3.Error, pymysql.Error)


def _get_setting(name: str) -> str | None:
    """Returns a setting from Streamlit secrets, falling back to the environment variable of the same name."""
    try:
        value: object = st.secrets.get(name)
    except StreamlitSecretNotFoundError:
        value = None
    return str(value) if value else os.environ.get(name) or None


def get_database_type() -> DatabaseType:
    """Returns the configured database type from Streamlit secrets, falling back to the environment variable.

    Returns "none" if DATABASE_TYPE is not set or is empty.

    Raises:
        ValueError: If DATABASE_TYPE is set to an unsupported value.
    """
    value: str = (_get_setting(DATABASE_TYPE_SECRET) or "none").strip().lower()
    if value not in get_args(DatabaseType):
        raise ValueError(
            f"Unsupported {DATABASE_TYPE_SECRET} {value!r}, expected one of {', '.join(get_args(DatabaseType))}."
        )
    return cast("DatabaseType", value)


def _mysql_connect() -> pymysql.connections.Connection:
    """Opens a connection to the MySQL database set by DATABASE_URL, DATABASE_USERNAME and DATABASE_PASSWORD.

    A username or password in DATABASE_URL is used when DATABASE_USERNAME or DATABASE_PASSWORD is not set.

    Raises:
        ValueError: If DATABASE_URL is missing or malformed, or no username is set.
    """
    url: str | None = _get_setting(DATABASE_URL_SECRET)
    if not url:
        raise ValueError(f"{DATABASE_URL_SECRET} must be set when {DATABASE_TYPE_SECRET} is mysql.")
    parts: SplitResult = urlsplit(url.strip())
    database_name: str = unquote(parts.path.lstrip("/"))
    if parts.scheme not in ("mysql", "mysql+pymysql") or not parts.hostname or not database_name:
        raise ValueError(f"{DATABASE_URL_SECRET} must be in the form mysql://host[:port]/database.")

    username: str | None = _get_setting(DATABASE_USERNAME_SECRET) or (parts.username and unquote(parts.username))
    if not username:
        raise ValueError(f"{DATABASE_USERNAME_SECRET} must be set when {DATABASE_TYPE_SECRET} is mysql.")
    password: str = _get_setting(DATABASE_PASSWORD_SECRET) or unquote(parts.password or "")

    return pymysql.connect(
        host=parts.hostname,
        port=parts.port or MYSQL_DEFAULT_PORT,
        user=username,
        password=password,
        database=database_name,
        charset="utf8mb4",
        connect_timeout=10,
    )


@st.cache_resource
def init_database() -> DatabaseType:
    """Creates and initialises the configured database if it does not already exist, and returns its type.

    Cached so this runs once per server process rather than on every script rerun.
    """
    database_type: DatabaseType = get_database_type()
    if database_type != "none":
        with closing(connect()):
            pass
    return database_type


def connect() -> Connection:
    """Opens a connection to the configured database, creating its tables if needed. The caller must close it.

    A new connection is opened for each use because a sqlite3 connection cannot be shared between the threads
    Streamlit runs scripts on, and a MySQL connection may time out between saves.

    Raises:
        RuntimeError: If no database is configured.
    """
    database_type: DatabaseType = get_database_type()
    if database_type == "sqlite":
        SQLITE_DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
        return sql_store.connect(str(SQLITE_DATABASE_FILE))
    if database_type == "mysql":
        conn: pymysql.connections.Connection = _mysql_connect()
        try:
            sql_store.init_db(conn)
        except BaseException:
            conn.close()
            raise
        return conn
    raise RuntimeError(f"No database configured. Set {DATABASE_TYPE_SECRET} to enable saving.")
