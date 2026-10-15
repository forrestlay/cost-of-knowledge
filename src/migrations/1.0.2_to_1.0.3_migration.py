"""Migrates a Cost of Knowledge database from tool version 1.0.2 to 1.0.3.

Version 1.0.3 can save the events recorded by streamlit_analytics2 to the database, in the analytics_events table
(see src.analytics.DatabaseEventStore). This migration creates the table. Events recorded earlier to data/analytics.db
are not copied into it.

The migration is safe to run more than once, and does nothing to a database that is already up to date.

It is run by src/migrate.py, along with any other migrations a database needs. It can also be run on its own against
the database configured by DATABASE_TYPE (see src/database.py) before starting version 1.0.3 of the tool:

    uv run python "src/migrations/1.0.2_to_1.0.3_migration.py"

or against a particular SQLite database file:

    uv run python "src/migrations/1.0.2_to_1.0.3_migration.py" path/to/database.db

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

import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

# Allows running this file directly as a script, as the src package is imported from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

if TYPE_CHECKING:
    from src.sql_store import Connection

# The analytics_events table as of version 1.0.3, kept here rather than taken from src/sql_store.py so that this
# migration does not change if the current schema does.
SQLITE_ANALYTICS_EVENTS_TABLE: str = """
CREATE TABLE IF NOT EXISTS analytics_events (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    session TEXT NOT NULL,
    visitor TEXT,
    page TEXT,
    name TEXT,
    widget_id TEXT,
    widget_type TEXT,
    widget_key TEXT,
    value TEXT,
    props TEXT
)
"""

MYSQL_ANALYTICS_EVENTS_TABLE: str = """
CREATE TABLE IF NOT EXISTS analytics_events (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    ts VARCHAR(32) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    session TEXT NOT NULL,
    visitor TEXT,
    page TEXT,
    name TEXT,
    widget_id TEXT,
    widget_type TEXT,
    widget_key TEXT,
    value TEXT,
    props TEXT
)
"""


def migrate(conn: Connection) -> None:
    """Migrates the database of a sqlite3 or PyMySQL connection from tool version 1.0.2 to 1.0.3."""
    statement: str = (
        SQLITE_ANALYTICS_EVENTS_TABLE if isinstance(conn, sqlite3.Connection) else MYSQL_ANALYTICS_EVENTS_TABLE
    )
    with closing(conn.cursor()) as cursor:
        cursor.execute(statement)
    conn.commit()


def main(argv: list[str]) -> None:
    if len(argv) > 1:
        database_file: Path = Path(argv[1])
        if not database_file.is_file():
            raise SystemExit(f"No database file at {database_file}.")
        with closing(sqlite3.connect(database_file)) as conn:
            migrate(conn)
    else:
        from src import database

        database_type: database.DatabaseType = database.get_database_type()
        if database_type == "none":
            raise SystemExit(f"No database configured. Set {database.DATABASE_TYPE_SECRET}, or pass a SQLite file.")
        if database_type == "sqlite" and not database.SQLITE_DATABASE_FILE.is_file():
            raise SystemExit(f"No database file at {database.SQLITE_DATABASE_FILE}.")
        # Opened without database.connect, which would create missing tables first.
        with closing(database.connect_without_init()) as conn:
            migrate(conn)
    print("Migrated the database from tool version 1.0.2 to 1.0.3.")


if __name__ == "__main__":
    main(sys.argv)
