"""Migrates a Cost of Knowledge database from tool version 1.0.1 to 1.0.2.

Version 1.0.2 records the hourly rate excluding indirect costs of each researcher whose rate was calculated from a
salary or entered directly, in people.base_hourly_rate, so that their rate follows changes to the indirect cost rate.
This migration adds the column. People saved before it have no value, and their projects have a schema_version below
6, so the rate is derived when they are loaded (see CalculatorState.from_dict). Their saved hourly rates are unchanged.

The migration is safe to run more than once, and does nothing to a database that is already up to date.

It is run by src/migrate.py, along with any other migrations a database needs. It can also be run on its own against
the database configured by DATABASE_TYPE (see src/database.py) before starting version 1.0.2 of the tool:

    uv run python "src/migrations/1.0.1_to_1.0.2_migration.py"

or against a particular SQLite database file:

    uv run python "src/migrations/1.0.1_to_1.0.2_migration.py" path/to/database.db

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


def _has_base_hourly_rate_column(conn: Connection) -> bool:
    """Returns whether the people table has a base_hourly_rate column."""
    if isinstance(conn, sqlite3.Connection):
        return any(column[1] == "base_hourly_rate" for column in conn.execute("PRAGMA table_info(people)"))
    with closing(conn.cursor()) as cursor:
        cursor.execute(
            "SELECT 1 FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'people' AND COLUMN_NAME = 'base_hourly_rate'"
        )
        return cursor.fetchone() is not None


def migrate(conn: Connection) -> None:
    """Migrates the database of a sqlite3 or PyMySQL connection from tool version 1.0.1 to 1.0.2."""
    if _has_base_hourly_rate_column(conn):
        return
    # The types match the hourly_rate column of each schema in src/sql_store.py.
    column_type: str = "NUMERIC" if isinstance(conn, sqlite3.Connection) else "DOUBLE"
    with closing(conn.cursor()) as cursor:
        cursor.execute(f"ALTER TABLE people ADD COLUMN base_hourly_rate {column_type}")
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
    print("Migrated the database from tool version 1.0.1 to 1.0.2.")


if __name__ == "__main__":
    main(sys.argv)
