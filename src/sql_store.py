"""SQLite and MySQL persistence for Cost of Knowledge calculator projects.

Each saved CalculatorState is a row in the projects table, with its people, activities and direct costs in child
tables. Rows are built from CalculatorState.to_dict() and loaded back through CalculatorState.from_dict(), so the dict
format remains the single definition of what is serialised.

Functions take either a sqlite3 connection or a PyMySQL connection. Queries are written with "?" placeholders, which
are rewritten to PyMySQL's "%s" placeholders when needed.

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
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.calculator_state import CalculatorState

if TYPE_CHECKING:
    from collections.abc import Iterator

    import pymysql

    type Connection = sqlite3.Connection | pymysql.connections.Connection
    type Cursor = sqlite3.Cursor | pymysql.cursors.Cursor

SCHEMA: str = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    user_name TEXT,
    user_country TEXT NOT NULL,
    international_collaborators INTEGER NOT NULL,
    project_name TEXT,
    project_field TEXT NOT NULL,
    tool_step INTEGER NOT NULL,
    -- Derived from the inputs below for querying; ignored when a project is loaded.
    total_cost NUMERIC NOT NULL,
    total_hours NUMERIC NOT NULL
);

CREATE TABLE IF NOT EXISTS people (
    project_id INTEGER NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    unique_key TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('team', 'peer_reviewer', 'journal_editor')),
    name TEXT,
    person_type TEXT NOT NULL,
    hourly_rate NUMERIC NOT NULL,
    PRIMARY KEY (project_id, unique_key)
);

CREATE TABLE IF NOT EXISTS activities (
    project_id INTEGER NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    unique_key INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('activity', 'peer_review', 'journal_editing')),
    name TEXT,
    phase TEXT NOT NULL,
    person_key TEXT NOT NULL,
    group_key INTEGER,
    hours NUMERIC,
    review_rounds INTEGER,
    journal_submissions INTEGER,
    initial_round_hours NUMERIC,
    subsequent_round_hours NUMERIC,
    hours_per_submission NUMERIC,
    PRIMARY KEY (project_id, unique_key),
    FOREIGN KEY (project_id, person_key) REFERENCES people (project_id, unique_key)
);

CREATE TABLE IF NOT EXISTS direct_costs (
    project_id INTEGER NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    unique_key INTEGER NOT NULL,
    name TEXT,
    phase TEXT NOT NULL,
    cost NUMERIC NOT NULL,
    PRIMARY KEY (project_id, unique_key)
);
"""

# The tables of SCHEMA for MySQL, one statement each. MySQL ignores foreign keys declared inline on a column, needs
# AUTO_INCREMENT to generate ids and a length for text columns in a key, and its NUMERIC type would round to integers.
MYSQL_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        schema_version INTEGER NOT NULL,
        created_at VARCHAR(32) NOT NULL,
        updated_at VARCHAR(32) NOT NULL,
        user_name TEXT,
        user_country VARCHAR(16) NOT NULL,
        international_collaborators INTEGER NOT NULL,
        project_name TEXT,
        project_field TEXT NOT NULL,
        tool_step INTEGER NOT NULL,
        -- Derived from the inputs below for querying, ignored when a project is loaded.
        total_cost DOUBLE NOT NULL,
        total_hours DOUBLE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS people (
        project_id INTEGER NOT NULL,
        position INTEGER NOT NULL,
        unique_key VARCHAR(255) NOT NULL,
        role VARCHAR(32) NOT NULL CHECK (role IN ('team', 'peer_reviewer', 'journal_editor')),
        name TEXT,
        person_type TEXT NOT NULL,
        hourly_rate DOUBLE NOT NULL,
        PRIMARY KEY (project_id, unique_key),
        FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS activities (
        project_id INTEGER NOT NULL,
        position INTEGER NOT NULL,
        unique_key INTEGER NOT NULL,
        kind VARCHAR(32) NOT NULL CHECK (kind IN ('activity', 'peer_review', 'journal_editing')),
        name TEXT,
        phase TEXT NOT NULL,
        person_key VARCHAR(255) NOT NULL,
        group_key INTEGER,
        hours DOUBLE,
        review_rounds INTEGER,
        journal_submissions INTEGER,
        initial_round_hours DOUBLE,
        subsequent_round_hours DOUBLE,
        hours_per_submission DOUBLE,
        PRIMARY KEY (project_id, unique_key),
        FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
        FOREIGN KEY (project_id, person_key) REFERENCES people (project_id, unique_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS direct_costs (
        project_id INTEGER NOT NULL,
        position INTEGER NOT NULL,
        unique_key INTEGER NOT NULL,
        name TEXT,
        phase TEXT NOT NULL,
        cost DOUBLE NOT NULL,
        PRIMARY KEY (project_id, unique_key),
        FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
    )
    """,
)

# Columns of the activities table that hold fields of a serialised activity, besides project_id and position.
_ACTIVITY_COLUMNS: tuple[str, ...] = (
    "unique_key",
    "kind",
    "name",
    "phase",
    "person_key",
    "group_key",
    "hours",
    "review_rounds",
    "journal_submissions",
    "initial_round_hours",
    "subsequent_round_hours",
    "hours_per_submission",
)


def connect(database: str) -> sqlite3.Connection:
    """Opens a SQLite database with foreign keys enforced and creates the schema if needed.

    Args:
        database: Path to the database file, or ":memory:".
    """
    conn: sqlite3.Connection = sqlite3.connect(database)
    init_db(conn)
    return conn


def init_db(conn: Connection) -> None:
    """Creates the tables if they do not exist. For SQLite, also enables foreign keys on the connection."""
    if isinstance(conn, sqlite3.Connection):
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)
        return
    with closing(conn.cursor()) as cursor:
        for statement in MYSQL_SCHEMA:
            cursor.execute(statement)
    conn.commit()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sql(conn: Connection, query: str) -> str:
    """Rewrites a query's "?" placeholders to the placeholder style of the connection's driver."""
    return query if isinstance(conn, sqlite3.Connection) else query.replace("?", "%s")


def _column_value(value: Any) -> Any:
    """Returns whole number floats as ints, as SQLite's NUMERIC columns do, so int-bounded Streamlit inputs accept them.

    MySQL's DOUBLE columns return every number as a float.
    """
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _fetch_dicts(cursor: Cursor) -> list[dict[str, Any]]:
    """Returns the cursor's remaining rows as dicts keyed by column name."""
    columns: list[str] = [description[0] for description in cursor.description]
    return [
        {column: _column_value(value) for column, value in zip(columns, row, strict=True)} for row in cursor.fetchall()
    ]


@contextmanager
def _transaction(conn: Connection) -> Iterator[Cursor]:
    """Yields a cursor, committing when the block succeeds and rolling back if it raises."""
    try:
        with closing(conn.cursor()) as cursor:
            yield cursor
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _project_values(state: CalculatorState) -> dict[str, Any]:
    """Values of a projects row for the given state, excluding id and timestamps."""
    data: dict[str, Any] = state.to_dict()
    return {
        "schema_version": data["schema_version"],
        **data["project"],
        "international_collaborators": int(data["project"]["international_collaborators"]),
        "tool_step": data["tool_step"],
        "total_cost": data["summary"]["total_cost"],
        "total_hours": data["summary"]["total_hours"],
    }


def _insert_children(conn: Connection, cursor: Cursor, project_id: int, state: CalculatorState) -> None:
    """Inserts the people, activities and direct costs of a state for the given project."""
    data: dict[str, Any] = state.to_dict()

    people_rows: list[tuple[str, dict[str, Any]]] = [
        *(("team", person) for person in data["people"]),
        ("peer_reviewer", data["peer_reviewer"]),
        ("journal_editor", data["journal_editor"]),
    ]
    cursor.executemany(
        _sql(
            conn,
            "INSERT INTO people (project_id, position, unique_key, role, name, person_type, hourly_rate)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ),
        [
            (
                project_id,
                position,
                person["unique_key"],
                role,
                person["name"],
                person["person_type"],
                person["hourly_rate"],
            )
            for position, (role, person) in enumerate(people_rows)
        ],
    )
    cursor.executemany(
        _sql(
            conn,
            f"INSERT INTO activities (project_id, position, {', '.join(_ACTIVITY_COLUMNS)})"
            f" VALUES (?, ?, {', '.join('?' for _ in _ACTIVITY_COLUMNS)})",
        ),
        [
            (project_id, position, *(activity.get(column) for column in _ACTIVITY_COLUMNS))
            for position, activity in enumerate(data["activities"])
        ],
    )
    cursor.executemany(
        _sql(
            conn,
            "INSERT INTO direct_costs (project_id, position, unique_key, name, phase, cost) VALUES (?, ?, ?, ?, ?, ?)",
        ),
        [
            (project_id, position, cost["unique_key"], cost["name"], cost["phase"], cost["cost"])
            for position, cost in enumerate(data["direct_costs"])
        ],
    )


def save_project(conn: Connection, state: CalculatorState) -> int:
    """Saves a calculator state as a new project and returns its id."""
    values: dict[str, Any] = _project_values(state)
    timestamp: str = _now()
    with _transaction(conn) as cursor:
        cursor.execute(
            _sql(
                conn,
                f"INSERT INTO projects (created_at, updated_at, {', '.join(values)})"
                f" VALUES (?, ?, {', '.join('?' for _ in values)})",
            ),
            (timestamp, timestamp, *values.values()),
        )
        project_id: int = cursor.lastrowid  # ty:ignore[invalid-assignment]
        _insert_children(conn, cursor, project_id, state)
    return project_id


def update_project(conn: Connection, project_id: int, state: CalculatorState) -> None:
    """Replaces a saved project's data with the given calculator state.

    Raises:
        KeyError: If no project with that id exists.
    """
    values: dict[str, Any] = _project_values(state)
    with _transaction(conn) as cursor:
        # Checked with a SELECT, as MySQL's rowcount for an UPDATE counts only the rows whose values changed.
        cursor.execute(_sql(conn, "SELECT 1 FROM projects WHERE id = ?"), (project_id,))
        if cursor.fetchone() is None:
            raise KeyError(f"No project with id {project_id}.")
        cursor.execute(
            _sql(
                conn,
                f"UPDATE projects SET updated_at = ?, {', '.join(f'{column} = ?' for column in values)} WHERE id = ?",
            ),
            (_now(), *values.values(), project_id),
        )
        # Activities reference people, so remove them first.
        for table in ("activities", "direct_costs", "people"):
            cursor.execute(_sql(conn, f"DELETE FROM {table} WHERE project_id = ?"), (project_id,))
        _insert_children(conn, cursor, project_id, state)


def load_project(conn: Connection, project_id: int) -> CalculatorState:
    """Loads a saved project as a CalculatorState, ready for CalculatorState.apply_to_session_state.

    Raises:
        KeyError: If no project with that id exists.
    """
    with closing(conn.cursor()) as cursor:

        def select_children(table: str) -> list[dict[str, Any]]:
            cursor.execute(_sql(conn, f"SELECT * FROM {table} WHERE project_id = ? ORDER BY position"), (project_id,))
            return _fetch_dicts(cursor)

        cursor.execute(_sql(conn, "SELECT * FROM projects WHERE id = ?"), (project_id,))
        projects: list[dict[str, Any]] = _fetch_dicts(cursor)
        if not projects:
            raise KeyError(f"No project with id {project_id}.")
        project: dict[str, Any] = projects[0]

        people: dict[str, list[dict[str, Any]]] = {"team": [], "peer_reviewer": [], "journal_editor": []}
        for row in select_children("people"):
            people[row["role"]].append(
                {
                    "name": row["name"],
                    "unique_key": row["unique_key"],
                    "person_type": row["person_type"],
                    "hourly_rate": row["hourly_rate"],
                }
            )
        activities: list[dict[str, Any]] = [
            {column: row[column] for column in _ACTIVITY_COLUMNS if row[column] is not None or column == "name"}
            for row in select_children("activities")
        ]
        direct_costs: list[dict[str, Any]] = [
            {"name": row["name"], "phase": row["phase"], "cost": row["cost"], "unique_key": row["unique_key"]}
            for row in select_children("direct_costs")
        ]

    return CalculatorState.from_dict(
        {
            "schema_version": project["schema_version"],
            "project": {
                "user_name": project["user_name"],
                "user_country": project["user_country"],
                "international_collaborators": bool(project["international_collaborators"]),
                "project_name": project["project_name"],
                "project_field": project["project_field"],
            },
            "people": people["team"],
            "peer_reviewer": people["peer_reviewer"][0],
            "journal_editor": people["journal_editor"][0],
            "activities": activities,
            "direct_costs": direct_costs,
            "tool_step": project["tool_step"],
        }
    )


def list_projects(conn: Connection) -> list[dict[str, Any]]:
    """Lists saved projects, most recently updated first, without loading their full data."""
    with closing(conn.cursor()) as cursor:
        cursor.execute(
            "SELECT id, created_at, updated_at, user_name, project_name, total_cost, total_hours"
            " FROM projects ORDER BY updated_at DESC, id DESC"
        )
        return _fetch_dicts(cursor)


def delete_project(conn: Connection, project_id: int) -> None:
    """Deletes a saved project along with its people, activities and direct costs."""
    with _transaction(conn) as cursor:
        cursor.execute(_sql(conn, "DELETE FROM projects WHERE id = ?"), (project_id,))
