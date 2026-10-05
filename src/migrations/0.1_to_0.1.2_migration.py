"""Migrates a Cost of Knowledge database from tool version 0.1 to 0.1.2.

Version 0.1 recorded the version of the form that each project was saved under as an integer (main.FORM_VERSION, always
1) in projects.version. Version 0.1.2 records the version of the tool instead (main.COST_OF_KNOWLEDGE_VERSION), as text
such as '0.1.2'. This migration changes projects.version to a text column and rewrites the projects saved under form
version 1 as saved under tool version '0.1'.

The migration is safe to run more than once, and does nothing to a database that is already up to date.

It is run by src/migrate.py, along with any other migrations a database needs. It can also be run on its own against
the database configured by DATABASE_TYPE (see src/database.py) before starting version 0.1.2 of the tool:

    uv run python "src/migrations/0.1_to_0.1.2_migration.py"

or against a particular SQLite database file:

    uv run python "src/migrations/0.1_to_0.1.2_migration.py" path/to/database.db

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

# Form version recorded by tool version 0.1, and the tool version that replaces it.
OLD_FORM_VERSION: int = 1
OLD_TOOL_VERSION: str = "0.1"


def _sqlite_version_type(conn: sqlite3.Connection) -> str:
    """Returns the declared type of projects.version in a SQLite database, in upper case."""
    for column in conn.execute("PRAGMA table_info(projects)").fetchall():
        if column[1] == "version":
            return str(column[2]).upper()
    raise RuntimeError("The projects table has no version column.")


def _migrate_sqlite(conn: sqlite3.Connection) -> None:
    """Changes projects.version to TEXT, as SQLite cannot change a column's type in place.

    The text values are copied into a new column, which then replaces the old one. Copying through a TEXT column keeps
    versions such as '0.1' as text, where an INTEGER column would convert them to the number 0.1.
    """
    if _sqlite_version_type(conn) == "INTEGER":
        conn.execute("BEGIN")
        try:
            # A column added with NOT NULL needs a default, which save_project and update_project never rely on.
            conn.execute("ALTER TABLE projects ADD COLUMN version_text TEXT NOT NULL DEFAULT ''")
            conn.execute(
                "UPDATE projects SET version_text = CASE WHEN version = ? THEN ? ELSE CAST(version AS TEXT) END",
                (OLD_FORM_VERSION, OLD_TOOL_VERSION),
            )
            conn.execute("ALTER TABLE projects DROP COLUMN version")
            conn.execute("ALTER TABLE projects RENAME COLUMN version_text TO version")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def _migrate_mysql(conn: Connection) -> None:
    """Changes projects.version to VARCHAR(16), then rewrites form version 1 as tool version '0.1'.

    MySQL commits each ALTER TABLE immediately, so the rewrite runs whatever the column's type, in case an earlier run
    stopped between the two steps.
    """
    with closing(conn.cursor()) as cursor:
        cursor.execute(
            "SELECT DATA_TYPE FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projects' AND COLUMN_NAME = 'version'"
        )
        row: tuple[str, ...] | None = cursor.fetchone()
        if row is None:
            raise RuntimeError("The projects table has no version column.")
        if row[0].lower() != "varchar":
            cursor.execute("ALTER TABLE projects MODIFY COLUMN version VARCHAR(16) NOT NULL")
        cursor.execute("UPDATE projects SET version = %s WHERE version = %s", (OLD_TOOL_VERSION, str(OLD_FORM_VERSION)))
    conn.commit()


def migrate(conn: Connection) -> None:
    """Migrates the database of a sqlite3 or PyMySQL connection from tool version 0.1 to 0.1.2."""
    if isinstance(conn, sqlite3.Connection):
        _migrate_sqlite(conn)
    else:
        _migrate_mysql(conn)


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
    print("Migrated the database from tool version 0.1 to 0.1.2.")


if __name__ == "__main__":
    main(sys.argv)
