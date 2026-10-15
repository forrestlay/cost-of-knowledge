"""Settings for the streamlit_analytics2 tracking shared by the calculator and result pages."""

from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError
from streamlit_analytics2 import storage

from src import database, sql_store

if TYPE_CHECKING:
    from collections.abc import Iterable

    from streamlit_analytics2.events import Event
    from streamlit_analytics2.storage import Store

# Saved under data/ so that the Docker volume mounted there also persists the analytics events.
ANALYTICS_FILE: Path = Path(__file__).parent.parent / "data" / "analytics.db"


def analytics_password() -> str | None:
    """Password for the analytics dashboard, from the ANALYTICS_PASSWORD environment variable, falling back to
    "analytics_password" in Streamlit secrets.

    Returns None if neither is set, which leaves the dashboard without a password. An empty string must not be returned
    instead, as streamlit_analytics2 would then accept an empty password input.
    """
    password: str | None = os.environ.get("ANALYTICS_PASSWORD")
    if password:
        return password
    try:
        secret: object = st.secrets.get("analytics_password")
    except StreamlitSecretNotFoundError:
        return None
    return str(secret) if secret else None


class DatabaseEventStore:
    """streamlit_analytics2 event store that saves events to the analytics_events table of the database configured by
    DATABASE_TYPE (see src/database.py). Use it with sa2.track(store=DatabaseEventStore()).

    A connection is opened for each call, as a sqlite3 connection cannot be shared between the threads Streamlit runs
    scripts on, and a MySQL connection may time out between runs. Both methods raise RuntimeError if no database is
    configured, and the database driver's error if it cannot be reached. streamlit_analytics2 catches and logs these.
    """

    def append(self, events: Iterable[Event]) -> None:
        """Saves events to the database, in the order given."""
        events = list(events)
        if not events:
            return
        # Tables are created once per server process by init_database, rather than on every run's connection.
        database.init_database()
        with closing(database.connect_without_init()) as conn:
            sql_store.append_analytics_events(conn, events)

    def read(self) -> list[Event]:
        """Returns every saved event, oldest first."""
        database.init_database()
        with closing(database.connect_without_init()) as conn:
            return sql_store.read_analytics_events(conn)


def analytics_store() -> Store:
    """Store for streamlit_analytics2 events, for sa2.track(store=...).

    Events are saved to the database when DATABASE_TYPE is set (see src/database.py), and otherwise to ANALYTICS_FILE.
    """
    if database.get_database_type() != "none":
        return DatabaseEventStore()
    # open_store returns the same store object for every run, as sa2.track(events_path=ANALYTICS_FILE) did.
    return storage.open_store(ANALYTICS_FILE)


def simple_analytics_embed() -> None:
    st.html(
        '<script async src="https://scripts.simpleanalyticscdn.com/latest.js"></script>', unsafe_allow_javascript=True
    )
