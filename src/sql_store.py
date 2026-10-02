"""SQLite and MySQL persistence for Cost of Knowledge calculator projects.

Each saved CalculatorState is a row in the projects table, with its people, activities and direct costs in child
tables. save_project creates a new row and update_project overwrites a saved project in place. Each project records
the version of the form (main.FORM_VERSION) that it was saved under. Rows are built from CalculatorState.to_dict() and
loaded back through CalculatorState.from_dict(), so the dict format remains the single definition of what is serialised.

No names are stored. Databases created by older versions are not migrated and must be reset.

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

import secrets
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.calculator_state import CalculatorState

if TYPE_CHECKING:
    from collections.abc import Iterator

    import pymysql
    import pymysql.cursors

    type Connection = sqlite3.Connection | pymysql.connections.Connection
    type Cursor = sqlite3.Cursor | pymysql.cursors.Cursor

SCHEMA: str = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    -- Non-sequential id that is safe to show in URLs, from generate_public_id.
    public_id VARCHAR(21) NOT NULL UNIQUE,
    schema_version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    user_country TEXT NOT NULL,
    international_collaborators INTEGER NOT NULL,
    project_field TEXT NOT NULL,
    indirect_cost_percentage INTEGER NOT NULL DEFAULT 40,
    -- 'simplified' or 'granular': whether the activities and direct_costs tables or the simplified_* tables count
    -- towards the totals.
    calculator_mode TEXT NOT NULL DEFAULT 'simplified' CHECK (calculator_mode IN ('simplified', 'granular')),
    -- 1 if the user loaded the default estimates from Alam et al. (2026) in the granular calculator, otherwise 0. NULL
    -- for simplified projects, as the button is only offered in the granular calculator.
    loaded_alam_defaults INTEGER CHECK (loaded_alam_defaults IN (0, 1)),
    -- The user's estimate of the cost of publishing their journal article, in the currency of user_country.
    publishing_costs NUMERIC NOT NULL,
    -- 1 if publishing_costs count towards total_cost, otherwise 0.
    include_publishing_costs INTEGER NOT NULL DEFAULT 0 CHECK (include_publishing_costs IN (0, 1)),
    -- Derived from the inputs below for querying; ignored when a project is loaded.
    total_cost NUMERIC NOT NULL,
    total_hours NUMERIC NOT NULL,
    -- Version of the form (main.FORM_VERSION) that the project was saved under.
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS people (
    project_id INTEGER NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    unique_key TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('team', 'peer_reviewer', 'journal_editor')),
    -- Key of the person's role in reference_data.ROLES, e.g. 'assistant_professor'.
    researcher_role TEXT,
    person_type TEXT NOT NULL,
    hourly_rate NUMERIC NOT NULL,
    -- Number of people sharing the hourly rate.
    quantity INTEGER NOT NULL DEFAULT 1,
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

-- Simplified estimate of the hours of a researcher in a phase.
CREATE TABLE IF NOT EXISTS simplified_hours (
    project_id INTEGER NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    phase TEXT NOT NULL,
    person_key TEXT NOT NULL,
    hours NUMERIC NOT NULL,
    PRIMARY KEY (project_id, phase, person_key),
    FOREIGN KEY (project_id, person_key) REFERENCES people (project_id, unique_key)
);

-- Simplified estimate of the total direct costs of a phase.
CREATE TABLE IF NOT EXISTS simplified_direct_costs (
    project_id INTEGER NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    phase TEXT NOT NULL,
    cost NUMERIC NOT NULL,
    PRIMARY KEY (project_id, phase)
);
"""

# The tables of SCHEMA for MySQL, one statement each. MySQL ignores foreign keys declared inline on a column, needs
# AUTO_INCREMENT to generate ids and a length for text columns in a key, and its NUMERIC type would round to integers.
MYSQL_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        -- Non-sequential id that is safe to show in URLs, from generate_public_id. Binary collation, as the default
        -- collation is case-insensitive and the id's alphabet mixes cases.
        public_id VARCHAR(21) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
        schema_version INTEGER NOT NULL,
        created_at VARCHAR(32) NOT NULL,
        updated_at VARCHAR(32) NOT NULL,
        user_country VARCHAR(16) NOT NULL,
        international_collaborators INTEGER NOT NULL,
        project_field TEXT NOT NULL,
        indirect_cost_percentage INTEGER NOT NULL DEFAULT 40,
        -- 'simplified' or 'granular': whether the activities and direct_costs tables or the simplified_* tables
        -- count towards the totals.
        calculator_mode VARCHAR(16) NOT NULL DEFAULT 'simplified' CHECK (calculator_mode IN ('simplified', 'granular')),
        -- 1 if the user loaded the default estimates from Alam et al. (2026) in the granular calculator, otherwise 0.
        -- NULL for simplified projects, as the button is only offered in the granular calculator.
        loaded_alam_defaults BOOLEAN,
        -- The user's estimate of the cost of publishing their journal article, in the currency of user_country.
        publishing_costs DOUBLE NOT NULL,
        -- 1 if publishing_costs count towards total_cost, otherwise 0.
        include_publishing_costs BOOLEAN NOT NULL DEFAULT 0,
        -- Derived from the inputs below for querying, ignored when a project is loaded.
        total_cost DOUBLE NOT NULL,
        total_hours DOUBLE NOT NULL,
        -- Version of the form (main.FORM_VERSION) that the project was saved under.
        version INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS people (
        project_id INTEGER NOT NULL,
        position INTEGER NOT NULL,
        unique_key VARCHAR(255) NOT NULL,
        role VARCHAR(32) NOT NULL CHECK (role IN ('team', 'peer_reviewer', 'journal_editor')),
        -- Key of the person's role in reference_data.ROLES, e.g. 'assistant_professor'.
        researcher_role VARCHAR(64),
        person_type TEXT NOT NULL,
        hourly_rate DOUBLE NOT NULL,
        -- Number of people sharing the hourly rate.
        quantity INTEGER NOT NULL DEFAULT 1,
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
    """
    CREATE TABLE IF NOT EXISTS simplified_hours (
        project_id INTEGER NOT NULL,
        position INTEGER NOT NULL,
        phase VARCHAR(32) NOT NULL,
        person_key VARCHAR(255) NOT NULL,
        hours DOUBLE NOT NULL,
        PRIMARY KEY (project_id, phase, person_key),
        FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
        FOREIGN KEY (project_id, person_key) REFERENCES people (project_id, unique_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS simplified_direct_costs (
        project_id INTEGER NOT NULL,
        position INTEGER NOT NULL,
        phase VARCHAR(32) NOT NULL,
        cost DOUBLE NOT NULL,
        PRIMARY KEY (project_id, phase),
        FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
    )
    """,
)

# The URL-safe alphabet and default length of NanoID, giving about 126 bits of randomness per id.
PUBLIC_ID_ALPHABET: str = "useandom-26T198340PX75pxJACKVERYMINDBUSHWOLF_GQZbfghjklqvwyzrict"
PUBLIC_ID_LENGTH: int = 21

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
    """Creates the tables if they do not exist. For SQLite, also enables foreign keys on the connection.

    Databases created by older versions are not migrated and must be reset.
    """
    if isinstance(conn, sqlite3.Connection):
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)
    else:
        with closing(conn.cursor()) as cursor:
            for statement in MYSQL_SCHEMA:
                cursor.execute(statement)
        conn.commit()


def generate_public_id(size: int = PUBLIC_ID_LENGTH) -> str:
    """Returns a random NanoID, for identifying a project in URLs without revealing how many projects are saved."""
    return "".join(secrets.choice(PUBLIC_ID_ALPHABET) for _ in range(size))


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
    if cursor.description is None:
        return []
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


def _project_values(state: CalculatorState, loaded_alam_defaults: bool) -> dict[str, Any]:
    """Values of a projects row for the given state, excluding id and timestamps.

    loaded_alam_defaults is recorded only for granular projects, and is NULL otherwise.
    """
    data: dict[str, Any] = state.to_dict()
    return {
        "schema_version": data["schema_version"],
        **data["project"],
        "international_collaborators": int(data["project"]["international_collaborators"]),
        "include_publishing_costs": int(data["project"]["include_publishing_costs"]),
        "loaded_alam_defaults": int(loaded_alam_defaults) if state.calculator_mode == "granular" else None,
        "total_cost": data["summary"]["total_cost"],
        "total_hours": data["summary"]["total_hours"],
    }


def _insert_children(conn: Connection, cursor: Cursor, project_id: int, state: CalculatorState) -> None:
    """Inserts the people, activities, direct costs and simplified estimates of a state for the given project."""
    data: dict[str, Any] = state.to_dict()

    people_rows: list[tuple[str, dict[str, Any]]] = [
        *(("team", person) for person in data["people"]),
        ("peer_reviewer", data["peer_reviewer"]),
        ("journal_editor", data["journal_editor"]),
    ]
    cursor.executemany(
        _sql(
            conn,
            "INSERT INTO people (project_id, position, unique_key, role, researcher_role, person_type, hourly_rate,"
            " quantity) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ),
        [
            (
                project_id,
                position,
                person["unique_key"],
                role,
                person["role"],
                person["person_type"],
                person["hourly_rate"],
                person["quantity"],
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
    cursor.executemany(
        _sql(
            conn, "INSERT INTO simplified_hours (project_id, position, phase, person_key, hours) VALUES (?, ?, ?, ?, ?)"
        ),
        [
            (project_id, position, hours["phase"], hours["person_key"], hours["hours"])
            for position, hours in enumerate(data["simplified_hours"])
        ],
    )
    cursor.executemany(
        _sql(conn, "INSERT INTO simplified_direct_costs (project_id, position, phase, cost) VALUES (?, ?, ?, ?)"),
        [
            (project_id, position, cost["phase"], cost["cost"])
            for position, cost in enumerate(data["simplified_direct_costs"])
        ],
    )


def save_project(conn: Connection, state: CalculatorState, version: int, loaded_alam_defaults: bool = False) -> str:
    """Saves a calculator state as a new project and returns its public id.

    Args:
        conn: Connection to the database.
        state: Calculator state to save.
        version: Version of the form that the project is saved under.
        loaded_alam_defaults: Whether the user loaded the default estimates from Alam et al. (2026). Only stored for
            projects in granular mode.
    """
    values: dict[str, Any] = {**_project_values(state, loaded_alam_defaults), "version": version}
    public_id: str = generate_public_id()
    timestamp: str = _now()
    with _transaction(conn) as cursor:
        cursor.execute(
            _sql(
                conn,
                f"INSERT INTO projects (public_id, created_at, updated_at, {', '.join(values)})"
                f" VALUES (?, ?, ?, {', '.join('?' for _ in values)})",
            ),
            (public_id, timestamp, timestamp, *values.values()),
        )
        project_id: int = cursor.lastrowid  # ty:ignore[invalid-assignment]
        _insert_children(conn, cursor, project_id, state)
    return public_id


def update_project(
    conn: Connection, public_id: str, state: CalculatorState, version: int, loaded_alam_defaults: bool = False
) -> None:
    """Replaces a saved project's data, form version and loaded_alam_defaults flag with the given values.

    Raises:
        KeyError: If no project with that public id exists.
    """
    values: dict[str, Any] = {**_project_values(state, loaded_alam_defaults), "version": version}
    with _transaction(conn) as cursor:
        # Checked with a SELECT, as MySQL's rowcount for an UPDATE counts only the rows whose values changed.
        cursor.execute(_sql(conn, "SELECT id FROM projects WHERE public_id = ?"), (public_id,))
        row: tuple[Any, ...] | None = cursor.fetchone()
        if row is None:
            raise KeyError(f"No project with id {public_id!r}.")
        project_id: int = row[0]
        cursor.execute(
            _sql(
                conn,
                f"UPDATE projects SET updated_at = ?, {', '.join(f'{column} = ?' for column in values)} WHERE id = ?",
            ),
            (_now(), *values.values(), project_id),
        )
        # Activities and simplified hours reference people, so remove them first.
        for table in ("activities", "simplified_hours", "simplified_direct_costs", "direct_costs", "people"):
            cursor.execute(_sql(conn, f"DELETE FROM {table} WHERE project_id = ?"), (project_id,))
        _insert_children(conn, cursor, project_id, state)


def _state_from_rows(
    project: dict[str, Any],
    people_rows: list[dict[str, Any]],
    activity_rows: list[dict[str, Any]],
    direct_cost_rows: list[dict[str, Any]],
    simplified_hours_rows: list[dict[str, Any]],
    simplified_direct_cost_rows: list[dict[str, Any]],
) -> CalculatorState:
    """Builds a CalculatorState from a projects row and its child rows, each in position order."""
    people: dict[str, list[dict[str, Any]]] = {"team": [], "peer_reviewer": [], "journal_editor": []}
    for row in people_rows:
        people[row["role"]].append(
            {
                "unique_key": row["unique_key"],
                "person_type": row["person_type"],
                "hourly_rate": row["hourly_rate"],
                "role": row["researcher_role"],
                "quantity": row["quantity"],
            }
        )
    activities: list[dict[str, Any]] = [
        {column: row[column] for column in _ACTIVITY_COLUMNS if row[column] is not None or column == "name"}
        for row in activity_rows
    ]
    direct_costs: list[dict[str, Any]] = [
        {"name": row["name"], "phase": row["phase"], "cost": row["cost"], "unique_key": row["unique_key"]}
        for row in direct_cost_rows
    ]

    return CalculatorState.from_dict(
        {
            "schema_version": project["schema_version"],
            "project": {
                "user_country": project["user_country"],
                "international_collaborators": bool(project["international_collaborators"]),
                "project_field": project["project_field"],
                "indirect_cost_percentage": project["indirect_cost_percentage"],
                "calculator_mode": project["calculator_mode"],
                "publishing_costs": project["publishing_costs"],
                "include_publishing_costs": bool(project["include_publishing_costs"]),
            },
            "people": people["team"],
            "peer_reviewer": people["peer_reviewer"][0],
            "journal_editor": people["journal_editor"][0],
            "activities": activities,
            "direct_costs": direct_costs,
            "simplified_hours": [
                {"phase": row["phase"], "person_key": row["person_key"], "hours": row["hours"]}
                for row in simplified_hours_rows
            ],
            "simplified_direct_costs": [
                {"phase": row["phase"], "cost": row["cost"]} for row in simplified_direct_cost_rows
            ],
        }
    )


def load_project(conn: Connection, public_id: str) -> CalculatorState:
    """Loads a saved project as a CalculatorState, ready for CalculatorState.apply_to_session_state.

    Raises:
        KeyError: If no project with that public id exists.
    """
    with closing(conn.cursor()) as cursor:
        cursor.execute(_sql(conn, "SELECT * FROM projects WHERE public_id = ?"), (public_id,))
        projects: list[dict[str, Any]] = _fetch_dicts(cursor)
        if not projects:
            raise KeyError(f"No project with id {public_id!r}.")
        project: dict[str, Any] = projects[0]

        def select_children(table: str) -> list[dict[str, Any]]:
            cursor.execute(
                _sql(conn, f"SELECT * FROM {table} WHERE project_id = ? ORDER BY position"), (project["id"],)
            )
            return _fetch_dicts(cursor)

        return _state_from_rows(
            project,
            select_children("people"),
            select_children("activities"),
            select_children("direct_costs"),
            select_children("simplified_hours"),
            select_children("simplified_direct_costs"),
        )


def load_projects(conn: Connection) -> list[tuple[dict[str, Any], CalculatorState]]:
    """Loads every saved project, most recently created first.

    Reads each table once rather than once per project, so it stays quick for a remote database with many projects.

    Returns:
        A list of (projects row, calculator state) pairs. The projects row holds the project's public_id, created_at
        and updated_at among its other columns.
    """
    with closing(conn.cursor()) as cursor:
        cursor.execute("SELECT * FROM projects ORDER BY created_at DESC, id DESC")
        projects: list[dict[str, Any]] = _fetch_dicts(cursor)

        def select_children(table: str) -> dict[int, list[dict[str, Any]]]:
            cursor.execute(f"SELECT * FROM {table} ORDER BY project_id, position")
            rows_by_project: dict[int, list[dict[str, Any]]] = {}
            for row in _fetch_dicts(cursor):
                rows_by_project.setdefault(row["project_id"], []).append(row)
            return rows_by_project

        people: dict[int, list[dict[str, Any]]] = select_children("people")
        activities: dict[int, list[dict[str, Any]]] = select_children("activities")
        direct_costs: dict[int, list[dict[str, Any]]] = select_children("direct_costs")
        simplified_hours: dict[int, list[dict[str, Any]]] = select_children("simplified_hours")
        simplified_direct_costs: dict[int, list[dict[str, Any]]] = select_children("simplified_direct_costs")

    return [
        (
            project,
            _state_from_rows(
                project,
                people.get(project["id"], []),
                activities.get(project["id"], []),
                direct_costs.get(project["id"], []),
                simplified_hours.get(project["id"], []),
                simplified_direct_costs.get(project["id"], []),
            ),
        )
        for project in projects
    ]


def list_projects(conn: Connection) -> list[dict[str, Any]]:
    """Lists saved projects, most recently updated first, without loading their full data."""
    with closing(conn.cursor()) as cursor:
        cursor.execute(
            "SELECT id, public_id, version, created_at, updated_at, total_cost, total_hours"
            " FROM projects ORDER BY updated_at DESC, id DESC"
        )
        return _fetch_dicts(cursor)


def delete_project(conn: Connection, public_id: str) -> None:
    """Deletes a saved project along with its people, activities, direct costs and simplified estimates."""
    with _transaction(conn) as cursor:
        cursor.execute(_sql(conn, "DELETE FROM projects WHERE public_id = ?"), (public_id,))
