"""SQLite and MySQL persistence for Cost of Knowledge calculator projects.

Each saved CalculatorState is a row in the projects table, with its people, activities and direct costs in child
tables. save_project creates a new row and update_project overwrites a saved project in place. Each project records
the version of the tool (main.COST_OF_KNOWLEDGE_VERSION) that it was saved under. Rows are built from
CalculatorState.to_dict() and loaded back through CalculatorState.from_dict(), so the dict format remains the single
definition of what is serialised.

No names are stored for projects. Databases created by older versions of the tool are not migrated automatically. Run
the scripts in src/migrations to bring them up to date.

The admin_users table records everyone who has logged in to the admin page. The first user to log in is the owner and is
authorised automatically. Every later user must be authorised by the owner before they can use the admin page.

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

import math
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
    -- 'simplified' or 'detailed': whether the activities and direct_costs tables or the simplified_* tables count
    -- towards the totals.
    calculator_mode TEXT NOT NULL DEFAULT 'simplified' CHECK (calculator_mode IN ('simplified', 'detailed')),
    -- 1 if the user loaded the default estimates from Alam et al. (2026) in the detailed calculator, otherwise 0. NULL
    -- for simplified projects, as the button is only offered in the detailed calculator.
    loaded_alam_defaults INTEGER CHECK (loaded_alam_defaults IN (0, 1)),
    -- The user's estimate of the cost of publishing their journal article, in the currency of user_country.
    publishing_costs NUMERIC NOT NULL,
    -- 1 if publishing_costs count towards total_cost, otherwise 0.
    include_publishing_costs INTEGER NOT NULL DEFAULT 0 CHECK (include_publishing_costs IN (0, 1)),
    -- Derived from the inputs below for querying; ignored when a project is loaded.
    total_cost NUMERIC NOT NULL,
    total_hours NUMERIC NOT NULL,
    -- Version of the tool (main.COST_OF_KNOWLEDGE_VERSION) that the project was saved under, e.g. '0.1.2'.
    version TEXT NOT NULL
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
    peer_reviewers INTEGER,
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

-- Users who have logged in to the admin page.
CREATE TABLE IF NOT EXISTS admin_users (
    -- Identifies the user at their login provider, from admin_user_id.
    user_id VARCHAR(255) PRIMARY KEY,
    email TEXT,
    name TEXT,
    -- 1 for the first user to log in, who authorises the others. The owner is always authorised.
    is_owner INTEGER NOT NULL DEFAULT 0 CHECK (is_owner IN (0, 1)),
    is_authorised INTEGER NOT NULL DEFAULT 0 CHECK (is_authorised IN (0, 1)),
    first_login_at TEXT NOT NULL,
    last_login_at TEXT NOT NULL,
    authorised_at TEXT
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
        -- 'simplified' or 'detailed': whether the activities and direct_costs tables or the simplified_* tables
        -- count towards the totals.
        calculator_mode VARCHAR(16) NOT NULL DEFAULT 'simplified' CHECK (calculator_mode IN ('simplified', 'detailed')),
        -- 1 if the user loaded the default estimates from Alam et al. (2026) in the detailed calculator, otherwise 0.
        -- NULL for simplified projects, as the button is only offered in the detailed calculator.
        loaded_alam_defaults BOOLEAN,
        -- The user's estimate of the cost of publishing their journal article, in the currency of user_country.
        publishing_costs DOUBLE NOT NULL,
        -- 1 if publishing_costs count towards total_cost, otherwise 0.
        include_publishing_costs BOOLEAN NOT NULL DEFAULT 0,
        -- Derived from the inputs below for querying, ignored when a project is loaded.
        total_cost DOUBLE NOT NULL,
        total_hours DOUBLE NOT NULL,
        -- Version of the tool (main.COST_OF_KNOWLEDGE_VERSION) that the project was saved under, e.g. '0.1.2'.
        version VARCHAR(16) NOT NULL
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
        peer_reviewers INTEGER,
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
    """
    CREATE TABLE IF NOT EXISTS admin_users (
        -- Identifies the user at their login provider, from admin_user_id.
        user_id VARCHAR(255) PRIMARY KEY,
        email TEXT,
        name TEXT,
        -- 1 for the first user to log in, who authorises the others. The owner is always authorised.
        is_owner BOOLEAN NOT NULL DEFAULT 0,
        is_authorised BOOLEAN NOT NULL DEFAULT 0,
        first_login_at VARCHAR(32) NOT NULL,
        last_login_at VARCHAR(32) NOT NULL,
        authorised_at VARCHAR(32)
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
    "peer_reviewers",
)


# Tables holding a project's child rows, in the order they are deleted. Activities and simplified hours reference
# people, so they come first. Table names are interpolated into queries, so only names from here may be used.
_CHILD_TABLES: tuple[str, ...] = ("activities", "simplified_hours", "simplified_direct_costs", "direct_costs", "people")
_SELECTABLE_TABLES: frozenset[str] = frozenset((*_CHILD_TABLES, "projects", "admin_users"))

# Limits on a saved project, so anonymous saves cannot fill the database or slow the admin page.
MAX_TEXT_LENGTH: int = 200
MAX_PEOPLE: int = 100
MAX_ACTIVITIES: int = 500
MAX_DIRECT_COSTS: int = 500
MAX_HOURS: float = 1_000_000
MAX_COST: float = 1_000_000_000_000


def _check_table(table: str) -> str:
    """Returns the table name if it is a known table, as names are interpolated into queries rather than bound."""
    if table not in _SELECTABLE_TABLES:
        raise ValueError(f"Unknown table {table!r}.")
    return table


def validate_state(state: CalculatorState) -> None:
    """Checks that a state is small and sane enough to save.

    Raises:
        ValueError: If a list is too long, a text is too long, or a number is negative, not finite or implausibly large.
    """
    data: dict[str, Any] = state.to_dict()
    for name, limit in (("people", MAX_PEOPLE), ("activities", MAX_ACTIVITIES), ("direct_costs", MAX_DIRECT_COSTS)):
        if len(data[name]) > limit:
            raise ValueError(f"Too many {name.replace('_', ' ')}, the limit is {limit}.")
    for table in ("simplified_hours", "simplified_direct_costs"):
        if len(data[table]) > MAX_PEOPLE * 4:
            raise ValueError(f"Too many {table.replace('_', ' ')}.")

    def check_text(value: Any) -> None:
        if isinstance(value, str) and len(value) > MAX_TEXT_LENGTH:
            raise ValueError(f"Text is too long, the limit is {MAX_TEXT_LENGTH} characters.")

    def check_number(value: Any, limit: float) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        if not math.isfinite(value) or value < 0 or value > limit:
            raise ValueError(f"Number {value!r} is outside the allowed range.")

    people: list[dict[str, Any]] = [*data["people"], data["peer_reviewer"], data["journal_editor"]]
    for person in people:
        check_text(person["unique_key"])
        check_number(person["hourly_rate"], MAX_COST)
        check_number(person["quantity"], MAX_PEOPLE)
    for item in (*data["activities"], *data["direct_costs"]):
        for value in item.values():
            check_text(value)
        for column in ("hours", "initial_round_hours", "subsequent_round_hours", "hours_per_submission"):
            check_number(item.get(column), MAX_HOURS)
        check_number(item.get("cost"), MAX_COST)
    for hours in data["simplified_hours"]:
        check_number(hours["hours"], MAX_HOURS)
    for cost in data["simplified_direct_costs"]:
        check_number(cost["cost"], MAX_COST)
    for column in ("user_country", "project_field"):
        check_text(data["project"][column])
    check_number(data["project"]["publishing_costs"], MAX_COST)
    check_number(data["project"]["indirect_cost_percentage"], 1000)


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

    Databases created by older versions of the tool are not migrated. Run the scripts in src/migrations to migrate them.
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
    """Rewrites a query's "?" placeholders to the placeholder style of the connection's driver.

    Every "?" is replaced, so a query must not contain a literal "?" or "%" in its text. Pass such values as parameters.
    """
    if "%" in query:
        raise ValueError("Queries must not contain a literal '%', pass it as a parameter.")
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

    loaded_alam_defaults is recorded only for detailed projects, and is NULL otherwise.
    """
    data: dict[str, Any] = state.to_dict()
    return {
        "schema_version": data["schema_version"],
        **data["project"],
        "international_collaborators": int(data["project"]["international_collaborators"]),
        "include_publishing_costs": int(data["project"]["include_publishing_costs"]),
        "loaded_alam_defaults": int(loaded_alam_defaults) if state.calculator_mode == "detailed" else None,
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


def save_project(conn: Connection, state: CalculatorState, version: str, loaded_alam_defaults: bool = False) -> str:
    """Saves a calculator state as a new project and returns its public id.

    Args:
        conn: Connection to the database.
        state: Calculator state to save.
        version: Version of the tool that the project is saved under, e.g. "0.1.2".
        loaded_alam_defaults: Whether the user loaded the default estimates from Alam et al. (2026). Only stored for
            projects in detailed mode.
    """
    validate_state(state)
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
    conn: Connection, public_id: str, state: CalculatorState, version: str, loaded_alam_defaults: bool = False
) -> None:
    """Replaces a saved project's data, tool version and loaded_alam_defaults flag with the given values.

    Raises:
        KeyError: If no project with that public id exists.
    """
    validate_state(state)
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
        for table in _CHILD_TABLES:
            cursor.execute(_sql(conn, f"DELETE FROM {_check_table(table)} WHERE project_id = ?"), (project_id,))
        _insert_children(conn, cursor, project_id, state)


def _state_from_rows(
    project: dict[str, Any],
    people_rows: list[dict[str, Any]],
    activity_rows: list[dict[str, Any]],
    direct_cost_rows: list[dict[str, Any]],
    simplified_hours_rows: list[dict[str, Any]],
    simplified_direct_cost_rows: list[dict[str, Any]],
) -> CalculatorState:
    """Builds a CalculatorState from a projects row and its child rows, each in position order, with the version of
    the tool that the project was saved under.
    """
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
            "version": project["version"],
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
                _sql(conn, f"SELECT * FROM {_check_table(table)} WHERE project_id = ? ORDER BY position"),
                (project["id"],),
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


def count_projects(conn: Connection) -> int:
    """Returns the number of saved projects."""
    with closing(conn.cursor()) as cursor:
        cursor.execute("SELECT COUNT(*) FROM projects")
        return int(cursor.fetchone()[0])


def load_projects(
    conn: Connection, limit: int | None = None, offset: int = 0
) -> list[tuple[dict[str, Any], CalculatorState]]:
    """Loads saved projects, most recently created first.

    Reads each table once rather than once per project, so it stays quick for a remote database with many projects.
    Pass limit and offset to load one page of projects, so the cost does not grow with the number of saved projects.

    Args:
        conn: Connection to the database.
        limit: Maximum number of projects to load, or None to load every project.
        offset: Number of the most recent projects to skip. Only used with limit.

    Returns:
        A list of (projects row, calculator state) pairs. The projects row holds the project's public_id, created_at
        and updated_at among its other columns.

    Raises:
        ValueError: If limit is below 1 or offset is negative.
    """
    if limit is not None and (limit < 1 or offset < 0):
        raise ValueError("limit must be at least 1 and offset must not be negative.")
    with closing(conn.cursor()) as cursor:
        if limit is None:
            cursor.execute("SELECT * FROM projects ORDER BY created_at DESC, id DESC")
        else:
            cursor.execute(
                _sql(conn, "SELECT * FROM projects ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"),
                (int(limit), int(offset)),
            )
        projects: list[dict[str, Any]] = _fetch_dicts(cursor)
        if not projects:
            return []
        project_ids: list[int] = [project["id"] for project in projects]

        def select_children(table: str) -> dict[int, list[dict[str, Any]]]:
            if limit is None:
                cursor.execute(f"SELECT * FROM {_check_table(table)} ORDER BY project_id, position")
            else:
                placeholders: str = ", ".join("?" for _ in project_ids)
                cursor.execute(
                    _sql(
                        conn,
                        f"SELECT * FROM {_check_table(table)} WHERE project_id IN ({placeholders})"
                        " ORDER BY project_id, position",
                    ),
                    project_ids,
                )
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


def admin_user_id(issuer: str | None, subject: str) -> str:
    """Returns the admin_users key of a user, from the issuer and subject claims of their login."""
    return f"{issuer or ''}#{subject}"


def is_admin_owner(conn: Connection, user_id: str) -> bool:
    """Returns whether the user is the authorised owner of the admin page."""
    with closing(conn.cursor()) as cursor:
        cursor.execute(
            _sql(conn, "SELECT 1 FROM admin_users WHERE user_id = ? AND is_owner = 1 AND is_authorised = 1"), (user_id,)
        )
        return cursor.fetchone() is not None


def record_admin_login(
    conn: Connection,
    user_id: str,
    email: str | None,
    name: str | None,
    owner_email: str | None = None,
    email_verified: bool = True,
) -> dict[str, Any]:
    """Records a login to the admin page and returns the user's admin_users row.

    A user logging in for the first time is added as unauthorised, unless there is no owner yet, in which case
    they become the authorised owner. Later logins update the user's email, name and last login time.

    If owner_email is given, only a user with that verified email can become the first owner. Others are added as
    unauthorised, and the first owner must still be that user.
    """
    timestamp: str = _now()
    may_own: bool = owner_email is None or (
        email_verified and email is not None and email.strip().lower() == owner_email.strip().lower()
    )
    with _transaction(conn) as cursor:
        cursor.execute(_sql(conn, "SELECT 1 FROM admin_users WHERE user_id = ?"), (user_id,))
        if cursor.fetchone() is None:
            # Decided in the INSERT itself, so the owner is whoever's row is first inserted into an empty table.
            cursor.execute(
                _sql(
                    conn,
                    "INSERT INTO admin_users (user_id, email, name, is_owner, is_authorised, first_login_at,"
                    " last_login_at, authorised_at)"
                    " SELECT ?, ?, ?, counts.is_first, counts.is_first, ?, ?, CASE WHEN counts.is_first = 1 THEN ? END"
                    " FROM (SELECT CASE WHEN COALESCE(SUM(is_owner), 0) = 0 AND ? = 1 THEN 1 ELSE 0 END AS is_first"
                    " FROM admin_users) AS counts",
                ),
                (user_id, email, name, timestamp, timestamp, timestamp, int(may_own)),
            )
        else:
            cursor.execute(
                _sql(conn, "UPDATE admin_users SET email = ?, name = ?, last_login_at = ? WHERE user_id = ?"),
                (email, name, timestamp, user_id),
            )
        cursor.execute(_sql(conn, "SELECT * FROM admin_users WHERE user_id = ?"), (user_id,))
        return _admin_user_row(_fetch_dicts(cursor)[0])


def _admin_user_row(row: dict[str, Any]) -> dict[str, Any]:
    """Returns an admin_users row with its flag columns as bools."""
    return {**row, "is_owner": bool(row["is_owner"]), "is_authorised": bool(row["is_authorised"])}


def list_admin_users(conn: Connection) -> list[dict[str, Any]]:
    """Lists everyone who has logged in to the admin page, the owner first and then in order of first login."""
    with closing(conn.cursor()) as cursor:
        cursor.execute("SELECT * FROM admin_users ORDER BY is_owner DESC, first_login_at, user_id")
        return [_admin_user_row(row) for row in _fetch_dicts(cursor)]


def authorise_admin_user(conn: Connection, user_id: str) -> None:
    """Authorises a user who has logged in to the admin page. Does nothing for a user who is already authorised.

    Raises:
        KeyError: If no user with that id has logged in.
    """
    with _transaction(conn) as cursor:
        # Checked with a SELECT, as MySQL's rowcount for an UPDATE counts only the rows whose values changed.
        cursor.execute(_sql(conn, "SELECT is_authorised FROM admin_users WHERE user_id = ?"), (user_id,))
        row: tuple[Any, ...] | None = cursor.fetchone()
        if row is None:
            raise KeyError(f"No admin user with id {user_id!r}.")
        if not row[0]:
            cursor.execute(
                _sql(conn, "UPDATE admin_users SET is_authorised = 1, authorised_at = ? WHERE user_id = ?"),
                (_now(), user_id),
            )


def set_admin_owner(conn: Connection, user_id: str) -> None:
    """Makes a user the owner, who authorises the others, in place of the current owner. The new owner is authorised.

    The previous owner stays authorised as an ordinary user.

    Raises:
        KeyError: If no user with that id has logged in.
    """
    with _transaction(conn) as cursor:
        cursor.execute(_sql(conn, "SELECT 1 FROM admin_users WHERE user_id = ?"), (user_id,))
        if cursor.fetchone() is None:
            raise KeyError(f"No admin user with id {user_id!r}.")
        cursor.execute("UPDATE admin_users SET is_owner = 0 WHERE is_owner = 1")
        cursor.execute(
            _sql(
                conn,
                "UPDATE admin_users SET is_owner = 1, is_authorised = 1,"
                " authorised_at = COALESCE(authorised_at, ?) WHERE user_id = ?",
            ),
            (_now(), user_id),
        )


def delete_admin_user(conn: Connection, user_id: str) -> None:
    """Deletes a user, rejecting them if they are not yet authorised or removing their access if they are.

    A deleted user who logs in again is recorded as a new, unauthorised user.

    Raises:
        KeyError: If no user with that id has logged in.
        ValueError: If the user is the owner, who cannot be deleted.
    """
    with _transaction(conn) as cursor:
        cursor.execute(_sql(conn, "SELECT is_owner FROM admin_users WHERE user_id = ?"), (user_id,))
        row: tuple[Any, ...] | None = cursor.fetchone()
        if row is None:
            raise KeyError(f"No admin user with id {user_id!r}.")
        if row[0]:
            raise ValueError("The owner cannot be deleted.")
        cursor.execute(_sql(conn, "DELETE FROM admin_users WHERE user_id = ?"), (user_id,))
