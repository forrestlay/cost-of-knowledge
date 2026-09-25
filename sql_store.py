"""SQLite persistence for Cost of Knowledge calculator projects.

Each saved CalculatorState is a row in the projects table, with its people, activities and direct costs in child
tables. Rows are built from CalculatorState.to_dict() and loaded back through CalculatorState.from_dict(), so the dict
format remains the single definition of what is serialised.

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
from datetime import UTC, datetime
from typing import Any

from calculator_state import CalculatorState

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


def init_db(conn: sqlite3.Connection) -> None:
    """Enables foreign keys on the connection and creates the tables if they do not exist."""
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(UTC).isoformat()


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


def _insert_children(conn: sqlite3.Connection, project_id: int, state: CalculatorState) -> None:
    """Inserts the people, activities and direct costs of a state for the given project."""
    data: dict[str, Any] = state.to_dict()

    people_rows: list[tuple[str, dict[str, Any]]] = [
        *(("team", person) for person in data["people"]),
        ("peer_reviewer", data["peer_reviewer"]),
        ("journal_editor", data["journal_editor"]),
    ]
    conn.executemany(
        "INSERT INTO people (project_id, position, unique_key, role, name, person_type, hourly_rate)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (project_id, position, person["unique_key"], role, person["name"], person["person_type"],
             person["hourly_rate"])
            for position, (role, person) in enumerate(people_rows)
        ],
    )
    conn.executemany(
        f"INSERT INTO activities (project_id, position, {', '.join(_ACTIVITY_COLUMNS)})"
        f" VALUES (?, ?, {', '.join('?' for _ in _ACTIVITY_COLUMNS)})",
        [
            (project_id, position, *(activity.get(column) for column in _ACTIVITY_COLUMNS))
            for position, activity in enumerate(data["activities"])
        ],
    )
    conn.executemany(
        "INSERT INTO direct_costs (project_id, position, unique_key, name, phase, cost) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (project_id, position, cost["unique_key"], cost["name"], cost["phase"], cost["cost"])
            for position, cost in enumerate(data["direct_costs"])
        ],
    )


def save_project(conn: sqlite3.Connection, state: CalculatorState) -> int:
    """Saves a calculator state as a new project and returns its id."""
    values: dict[str, Any] = _project_values(state)
    timestamp: str = _now()
    with conn:
        cursor: sqlite3.Cursor = conn.execute(
            f"INSERT INTO projects (created_at, updated_at, {', '.join(values)})"
            f" VALUES (?, ?, {', '.join('?' for _ in values)})",
            (timestamp, timestamp, *values.values()),
        )
        project_id: int = cursor.lastrowid  # ty:ignore[invalid-assignment]
        _insert_children(conn, project_id, state)
    return project_id


def update_project(conn: sqlite3.Connection, project_id: int, state: CalculatorState) -> None:
    """Replaces a saved project's data with the given calculator state.

    Raises:
        KeyError: If no project with that id exists.
    """
    values: dict[str, Any] = _project_values(state)
    with conn:
        cursor: sqlite3.Cursor = conn.execute(
            f"UPDATE projects SET updated_at = ?, {', '.join(f'{column} = ?' for column in values)} WHERE id = ?",
            (_now(), *values.values(), project_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"No project with id {project_id}.")
        # Activities reference people, so remove them first.
        for table in ("activities", "direct_costs", "people"):
            conn.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
        _insert_children(conn, project_id, state)


def load_project(conn: sqlite3.Connection, project_id: int) -> CalculatorState:
    """Loads a saved project as a CalculatorState, ready for CalculatorState.apply_to_session_state.

    Raises:
        KeyError: If no project with that id exists.
    """
    conn.row_factory = sqlite3.Row
    try:
        project: sqlite3.Row | None = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if project is None:
            raise KeyError(f"No project with id {project_id}.")

        people: dict[str, list[dict[str, Any]]] = {"team": [], "peer_reviewer": [], "journal_editor": []}
        for row in conn.execute("SELECT * FROM people WHERE project_id = ? ORDER BY position", (project_id,)):
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
            for row in conn.execute("SELECT * FROM activities WHERE project_id = ? ORDER BY position", (project_id,))
        ]
        direct_costs: list[dict[str, Any]] = [
            {"name": row["name"], "phase": row["phase"], "cost": row["cost"], "unique_key": row["unique_key"]}
            for row in conn.execute("SELECT * FROM direct_costs WHERE project_id = ? ORDER BY position", (project_id,))
        ]
    finally:
        conn.row_factory = None

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


def list_projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Lists saved projects, most recently updated first, without loading their full data."""
    cursor: sqlite3.Cursor = conn.execute(
        "SELECT id, created_at, updated_at, user_name, project_name, total_cost, total_hours"
        " FROM projects ORDER BY updated_at DESC, id DESC"
    )
    columns: list[str] = [description[0] for description in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def delete_project(conn: sqlite3.Connection, project_id: int) -> None:
    """Deletes a saved project along with its people, activities and direct costs."""
    with conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
