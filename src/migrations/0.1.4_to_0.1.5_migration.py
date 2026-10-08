"""Migrates a Cost of Knowledge database from tool version 0.1.4 to 0.1.5.

Version 0.1.5 records the average number of peer reviewers per journal submission of the peer review activity, in
activities.peer_reviewers. This migration adds the column. Activities saved before it have no value, and are loaded with
one peer reviewer, which is what their costs were calculated with.

The migration is safe to run more than once, and does nothing to a database that is already up to date.

It is run by src/migrate.py, along with any other migrations a database needs. It can also be run on its own against
the database configured by DATABASE_TYPE (see src/database.py) before starting version 0.1.5 of the tool:

    uv run python "src/migrations/0.1.4_to_0.1.5_migration.py"

or against a particular SQLite database file:

    uv run python "src/migrations/0.1.4_to_0.1.5_migration.py" path/to/database.db

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


def _has_peer_reviewers_column(conn: Connection) -> bool:
    """Returns whether the activities table has a peer_reviewers column."""
    if isinstance(conn, sqlite3.Connection):
        return any(column[1] == "peer_reviewers" for column in conn.execute("PRAGMA table_info(activities)"))
    with closing(conn.cursor()) as cursor:
        cursor.execute(
            "SELECT 1 FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'activities' AND COLUMN_NAME = 'peer_reviewers'"
        )
        return cursor.fetchone() is not None


def migrate(conn: Connection) -> None:
    """Migrates the database of a sqlite3 or PyMySQL connection from tool version 0.1.4 to 0.1.5."""
    if _has_peer_reviewers_column(conn):
        return
    with closing(conn.cursor()) as cursor:
        cursor.execute("ALTER TABLE activities ADD COLUMN peer_reviewers INTEGER")
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
    print("Migrated the database from tool version 0.1.4 to 0.1.5.")


if __name__ == "__main__":
    main(sys.argv)
