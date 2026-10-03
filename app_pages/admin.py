"""Page listing every result saved to the database, at BASE-URL/admin. It is not linked to from the calculator.

Users must log in with st.login. The first user to log in is authorised automatically and can then authorise the
users who log in after them, in the section at the bottom of the page.

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
from contextlib import closing
from typing import TYPE_CHECKING, Any

import pandas as pd
import streamlit as st

from src import database, sql_store
from src.calculator_state import OVERALL_TOTAL_PHASES, compute_costs
from src.reference_data import (
    COUNTRY_CURRENCIES,
    COUNTRY_NAMES,
    RESEARCH_PHASES,
    ROLES,
    field_of_research_display_name,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.calculator_state import CalculatorState
    from src.models import Cost

# The login providers configured in the [auth] section of secrets.toml, and their button labels.
LOGIN_PROVIDERS: dict[str, str] = {"google": "Google", "microsoft": "Microsoft"}

# Environment variables for the [auth] section of secrets.toml, which st.login reads. Each maps to its path in that
# section, e.g. GOOGLE_CLIENT_ID is [auth.google] client_id.
AUTH_ENVIRONMENT_VARIABLES: dict[str, tuple[str, ...]] = {
    "AUTH_REDIRECT_URI": ("redirect_uri",),
    "COOKIE_SECRET": ("cookie_secret",),
    "GOOGLE_CLIENT_ID": ("google", "client_id"),
    "GOOGLE_CLIENT_SECRET": ("google", "client_secret"),
    "GOOGLE_METADATA_URL": ("google", "server_metadata_url"),
    "MSFT_CLIENT_ID": ("microsoft", "client_id"),
    "MSFT_CLIENT_SECRET": ("microsoft", "client_secret"),
    "MSFT_METADATA_URL": ("microsoft", "server_metadata_url"),
}

# url_path of this page, set in main.py.
ADMIN_URL_PATH: str = "admin"
# url_path of the result page, set in main.py.
RESULT_URL_PATH: str = "result"


def calculator_url() -> str:
    """URL of the calculator, from the URL of this page, which is the calculator's URL followed by ADMIN_URL_PATH.

    Falls back to a relative URL when the browser's URL is unknown, e.g. when running under AppTest.
    """
    return (st.context.url or "./").removesuffix(ADMIN_URL_PATH)


@st.cache_data(ttl=60, show_spinner="Loading saved results...")
def load_saved() -> list[tuple[dict[str, Any], CalculatorState]]:
    """Loads every saved project and its calculator state, most recently saved first.

    Cached for a minute so reruns of the page do not query the database each time.
    """
    with closing(database.connect()) as conn:
        return sql_store.load_projects(conn)


@st.cache_data(ttl=60, show_spinner="Loading saved results...")
def load_results() -> pd.DataFrame:
    """Loads every saved project as one row of totals, most recently saved first.

    Cached for a minute so reruns of the page do not query the database each time. Costs are in the currency of each
    project's country, as saved.
    """
    projects: list[tuple[dict[str, Any], CalculatorState]] = load_saved()

    rows: list[dict[str, Any]] = []
    for project, state in projects:
        combined: list[Cost] = [*state.effective_activities(), *state.effective_direct_costs()]  # ty:ignore[invalid-assignment]
        rows.append(
            {
                "public_id": project["public_id"],
                "Saved": pd.to_datetime(project["created_at"]),
                "Country": COUNTRY_NAMES.get(state.user_country, state.user_country),
                "International collaboration": state.international_collaborators,
                "Field": field_of_research_display_name(state.project_field),
                "Researchers": sum(person.quantity for person in state.people.values()),
                "Peer reviews": state.peer_review.review_rounds,
                "Journal submissions": state.peer_review.journal_submissions,
                "Calculator mode": state.calculator_mode.capitalize(),
                # NULL for simplified projects, which have no defaults to load.
                "Loaded Alam et al. defaults": None
                if project["loaded_alam_defaults"] is None
                else bool(project["loaded_alam_defaults"]),
                "Include publishing costs": state.include_publishing_costs,
                "Publishing cost estimate": round(state.publishing_costs),
                "Currency": COUNTRY_CURRENCIES.get(state.user_country, ("", ""))[0],
                **{label: round(compute_costs(combined, phase=key)) for key, label in RESEARCH_PHASES.items()},
                "Total": round(state.total_cost()),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "public_id",
            "Saved",
            "Country",
            "International collaboration",
            "Field",
            "Researchers",
            "Peer reviews",
            "Journal submissions",
            "Calculator mode",
            "Loaded Alam et al. defaults",
            "Include publishing costs",
            "Publishing cost estimate",
            "Currency",
            *RESEARCH_PHASES.values(),
            "Total",
        ],
    ).astype({"Loaded Alam et al. defaults": "boolean"})


def inject_auth_secrets() -> None:
    """Adds the authentication settings that are set as environment variables to st.secrets, for st.login to use.

    st.login reads only the [auth] section of secrets.toml. Settings that are already in st.secrets take precedence over
    environment variables, and variables that are not set or are empty are ignored.
    """
    environment_auth: dict[str, Any] = {}
    for variable, path in AUTH_ENVIRONMENT_VARIABLES.items():
        value: str | None = os.environ.get(variable)
        if not value:
            continue
        section: dict[str, Any] = environment_auth
        for key in path[:-1]:
            section = section.setdefault(key, {})
        section[path[-1]] = value
    if not environment_auth:
        return

    # merge_programmatic_secrets replaces whole top-level keys, so the existing [auth] section is merged in first.
    existing_auth: dict[str, Any] = (
        dict(st.secrets.to_dict().get("auth", {})) if st.secrets.load_if_toml_exists() else {}
    )
    merged_auth: dict[str, Any] = {**environment_auth, **existing_auth}
    for provider in ("google", "microsoft"):
        if provider in environment_auth and provider in existing_auth:
            merged_auth[provider] = {**environment_auth[provider], **existing_auth[provider]}
    if merged_auth != existing_auth:
        st.secrets.merge_programmatic_secrets({"auth": merged_auth})


def user_claim(name: str) -> str | None:
    """Returns a claim of the logged-in user's login as a string, or None if the provider did not give it."""
    value: object = st.user.get(name)
    return value if isinstance(value, str) else None


def manage_user(click_key: str) -> None:
    """Runs the action of a button clicked in the users table, as the on_click callback of its button column.

    Args:
        click_key: The key of the button column, which holds the clicked row and button label in st.session_state.
    """
    click = st.session_state[click_key]
    user_id: str = st.session_state.admin_user_ids[click.row]
    action: Callable[[sql_store.Connection, str], None]
    # The label is the text of the button, which may include its icon, e.g. ":material/key: Set owner".
    if "Authorise" in click.label:
        action, description = sql_store.authorise_admin_user, "authorise"
    elif "Set owner" in click.label:
        action, description = sql_store.set_admin_owner, "make owner of"
    elif "Reject" in click.label or "Delete" in click.label:
        action, description = sql_store.delete_admin_user, "remove"
    else:
        return
    try:
        with closing(database.connect()) as conn:
            action(conn, user_id)
    except (KeyError, ValueError, *database.DATABASE_ERRORS) as error:
        st.session_state.admin_authorise_error = f"Could not {description} the user: {error}"


def load_result() -> None:
    """Loads the result of the clicked row into the details section, as the on_click callback of the Details column."""
    selected_id: str = st.session_state.admin_public_ids[st.session_state.admin_load_click.row]
    if selected_id != st.session_state.admin_selected_id:
        st.session_state.admin_selected_id = selected_id
        st.session_state.admin_show_json = False


def show_authorisation_section(current_user: dict[str, Any]) -> None:
    """Shows the users who have logged in and, to the owner, buttons to authorise, reject, delete or make owner."""
    st.divider()
    st.subheader("Authorised users")
    if not current_user["is_owner"]:
        st.caption("Only the owner, who is the first user to log in, can authorise and manage other users.")
    if "admin_authorise_error" in st.session_state:
        st.error(st.session_state.pop("admin_authorise_error"), icon=":material/error:")
    try:
        with closing(database.connect()) as conn:
            users: list[dict[str, Any]] = sql_store.list_admin_users(conn)
    except database.DATABASE_ERRORS as error:
        st.error(f"Could not load the users from the database: {error}", icon=":material/error:")
        return

    # The row of a button click indexes into the users shown, so keep their ids for the click's callback.
    st.session_state.admin_user_ids = [user["user_id"] for user in users]
    is_owner: bool = current_user["is_owner"]
    columns: list[str] = ["Name", "Email", "Owner", "Authorised", "First login", "Last login"]
    column_config: dict[str, Any] = {
        "Owner": st.column_config.CheckboxColumn("Owner"),
        "Authorised": st.column_config.CheckboxColumn("Authorised"),
        "First login": st.column_config.DatetimeColumn("First login", format="YYYY-MM-DD HH:mm"),
        "Last login": st.column_config.DatetimeColumn("Last login", format="YYYY-MM-DD HH:mm"),
    }
    if is_owner:
        # The owner has no buttons, as the owner can be neither authorised, rejected nor deleted. The owner can only be
        # replaced by setting another user as owner.
        columns += ["Access", "Remove"]
        column_config["Access"] = st.column_config.ButtonColumn(
            "Access",
            help="Authorise a user who is waiting, or make an authorised user the owner in place of you.",
            on_click=manage_user,
            args=("admin_access_click",),
            key="admin_access_click",
        )
        column_config["Remove"] = st.column_config.ButtonColumn(
            "Remove",
            help="Reject a user who is waiting, or delete an authorised user.",
            on_click=manage_user,
            args=("admin_remove_click",),
            key="admin_remove_click",
        )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Name": user["name"],
                    "Email": user["email"],
                    "Owner": user["is_owner"],
                    "Authorised": user["is_authorised"],
                    "First login": pd.to_datetime(user["first_login_at"]),
                    "Last login": pd.to_datetime(user["last_login_at"]),
                    "Access": None
                    if user["is_owner"]
                    else (":material/key: Set owner" if user["is_authorised"] else ":material/check: Authorise"),
                    "Remove": None
                    if user["is_owner"]
                    else (":material/delete: Delete" if user["is_authorised"] else ":material/close: Reject"),
                }
                for user in users
            ],
            columns=columns,
        ),
        hide_index=True,
        column_config=column_config,
    )


inject_auth_secrets()

st.set_page_config(page_title="Saved results", layout="wide")

st.title("Saved results")

if database.get_database_type() == "none":
    st.info("No database is configured, so there are no saved results.", icon=":material/info:")
    st.stop()

if not st.user.is_logged_in:
    st.info("Log in to view the saved results.", icon=":material/lock:")
    with st.container(horizontal=True):
        for provider, label in LOGIN_PROVIDERS.items():
            st.button(f"Log in with {label}", icon=":material/login:", on_click=st.login, args=(provider,))
    st.stop()

try:
    with closing(database.connect()) as conn:
        current_user: dict[str, Any] = sql_store.record_admin_login(
            conn,
            sql_store.admin_user_id(user_claim("iss"), user_claim("sub") or ""),
            user_claim("email"),
            user_claim("name"),
        )
except database.DATABASE_ERRORS as error:
    st.error(f"Could not check your access in the database: {error}", icon=":material/error:")
    st.stop()

if not current_user["is_authorised"]:
    st.warning(
        "You are logged in, but you have not been authorised to view the saved results. Ask the first user who"
        " logged in to authorise you on this page, then refresh.",
        icon=":material/lock:",
    )
    st.button("Log out", icon=":material/logout:", on_click=st.logout)
    st.stop()

st.button("Log out", icon=":material/logout:", on_click=st.logout)

with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
    st.caption("Every result saved from the calculator. Costs are in the currency of each result's country.")
    if st.button("Refresh", icon=":material/refresh:"):
        load_saved.clear()
        load_results.clear()

try:
    results: pd.DataFrame = load_results()
    states: dict[str, CalculatorState] = {str(project["public_id"]): state for project, state in load_saved()}
except database.DATABASE_ERRORS as error:
    st.error(f"Could not load the saved results from the database: {error}", icon=":material/error:")
    show_authorisation_section(current_user)
    st.stop()

if results.empty:
    st.info("No results have been saved yet.", icon=":material/info:")
    show_authorisation_section(current_user)
    st.stop()

public_ids: list[str] = results.pop("public_id").astype(str).tolist()

# Link each result to its result page, with its public id filled in.
results.insert(
    0,
    "Link",
    calculator_url() + f"{RESULT_URL_PATH}?{database.PROJECT_ID_QUERY_PARAM}=" + pd.Series(public_ids),
)
# The button to load each result into the details section, after the link.
results.insert(1, "Details", ":material/visibility: Load")
# The row of a button click indexes into the results shown, so keep their ids for the click's callback.
st.session_state.admin_public_ids = public_ids

# The public id of the result shown in the details section, kept across reruns.
if "admin_selected_id" not in st.session_state:
    st.session_state.admin_selected_id = None
if "admin_show_json" not in st.session_state:
    st.session_state.admin_show_json = False

with st.container(horizontal=True, horizontal_alignment="right"):
    st.download_button(
        "Export all results",
        data=results.drop(columns="Details").assign(public_id=public_ids).to_csv(index=False),
        file_name="results.csv",
        mime="text/csv",
        icon=":material/download:",
        on_click="ignore",
    )

st.dataframe(
    results,
    hide_index=True,
    column_config={
        "Link":st.column_config.LinkColumn(
            "Link",
            help="Open this result's page.",
            display_text=f"{database.PROJECT_ID_QUERY_PARAM}=(.*)$",
            pinned=True,
        ),
        "Details": st.column_config.ButtonColumn(
            "Details",
            help="Load this result into the details section below.",
            pinned=True,
            on_click=load_result,
            key="admin_load_click",
        ),
        "Saved": st.column_config.DatetimeColumn("Saved", format="YYYY-MM-DD HH:mm"),
        "International collaboration": st.column_config.CheckboxColumn("International collaboration"),
        "Loaded Alam et al. defaults": st.column_config.CheckboxColumn(
            "Loaded Alam et al. defaults",
            help="Whether the defaults from Alam et al. (2026) were loaded. Blank for simplified results.",
        ),
        "Include publishing costs": st.column_config.CheckboxColumn(
            "Include publishing costs",
            help="Whether the publishing cost estimate counts towards the total.",
        ),
        **{
            label: st.column_config.NumberColumn(label, format="localized")
            for label in ["Publishing cost estimate", *RESEARCH_PHASES.values(), "Total"]
        },
    },
)

st.subheader("Result details")

if st.session_state.admin_selected_id not in states:
    st.caption('Click "Load" on a result in the table above to see its details.')
    show_authorisation_section(current_user)
    st.stop()

state: CalculatorState = states[st.session_state.admin_selected_id]
currency: str = COUNTRY_CURRENCIES.get(state.user_country, ("", ""))[0]
st.caption(
    f"Result {st.session_state.admin_selected_id} · "
    f"{state.calculator_mode.capitalize()} · amounts in {currency or 'USD'}"
)

# The tables of the details section, in the order shown, which are also exported together as one CSV.
detail_tables: dict[str, pd.DataFrame] = {}

detail_tables["Researchers"] = pd.DataFrame(
    [
        {
            "Researcher": person.label,
            "Role": ROLES[person.role].short_display_name(state.user_country) if person.role in ROLES else "",
            "Quantity": person.quantity,
            "Hourly rate": person.hourly_rate,
        }
        for person in state.people.values()
    ],
    columns=["Researcher", "Role", "Quantity", "Hourly rate"],
)
if state.calculator_mode == "simplified":
    detail_tables["Phase hours and direct costs"] = pd.DataFrame(
        [
            {
                "Phase": RESEARCH_PHASES[phase],
                "Hours": sum(state.simplified_hours.get(phase, {}).values()),
                "Direct costs": state.simplified_direct_costs.get(phase, 0.0),
            }
            for phase in OVERALL_TOTAL_PHASES
        ],
        columns=["Phase", "Hours", "Direct costs"],
    )
else:
    detail_tables["Activities"] = pd.DataFrame(
        [
            {
                "Activity": activity.get_name(),
                "Researcher": activity.get_person().label,
                "Phase": RESEARCH_PHASES.get(activity.get_phase(), activity.get_phase()),
                "Hours": activity.get_hours(),
                "Cost": activity.get_total_cost(),
            }
            for activity in state.effective_activities()
        ],
        columns=["Activity", "Researcher", "Phase", "Hours", "Cost"],
    )
    detail_tables["Direct costs"] = pd.DataFrame(
        [
            {
                "Direct cost": direct_cost.get_name(),
                "Phase": RESEARCH_PHASES.get(direct_cost.get_phase(), direct_cost.get_phase()),
                "Cost": direct_cost.get_total_cost(),
            }
            for direct_cost in state.effective_direct_costs()
        ],
        columns=["Direct cost", "Phase", "Cost"],
    )
detail_tables["Peer review, journal submissions and publishing"] = pd.DataFrame(
    [
        {"Activity": "Peer review rounds", "Value": state.peer_review.review_rounds},
        {"Activity": "Journal editorial work submissions", "Value": state.journal_editing.journal_submissions},
        {
            "Activity": f"Publishing cost estimate ({COUNTRY_CURRENCIES.get(state.user_country, ('USD', ''))[0]})"
            f"{'' if state.include_publishing_costs else ', not included in the total'}",
            "Value": state.publishing_costs,
        },
    ],
    columns=["Activity", "Value"],
)

# The tables have different columns, so the CSV has the columns of all of them, with the table of each row first.
loaded_export: pd.DataFrame = pd.concat(
    [table.assign(Table=name) for name, table in detail_tables.items()], ignore_index=True
)
loaded_export = loaded_export[["Table", *(column for column in loaded_export.columns if column != "Table")]]
loaded_export.insert(0, "public_id", st.session_state.admin_selected_id)
with st.container(horizontal=True, horizontal_alignment="right"):
    st.download_button(
        "Export loaded result",
        data=loaded_export.to_csv(index=False),
        file_name=f"result-{st.session_state.admin_selected_id}.csv",
        mime="text/csv",
        icon=":material/download:",
        on_click="ignore",
    )

st.markdown("**Researchers**")
st.dataframe(
    detail_tables["Researchers"],
    hide_index=True,
    column_config={"Hourly rate": st.column_config.NumberColumn("Hourly rate", format="localized")},
)

if state.calculator_mode == "simplified":
    st.markdown("**Phase hours and direct costs**")
    st.dataframe(
        detail_tables["Phase hours and direct costs"],
        hide_index=True,
        column_config={
            "Hours": st.column_config.NumberColumn("Hours", format="localized"),
            "Direct costs": st.column_config.NumberColumn("Direct costs", format="localized"),
        },
    )
else:
    st.markdown("**Activities**")
    st.dataframe(
        detail_tables["Activities"],
        hide_index=True,
        column_config={
            "Hours": st.column_config.NumberColumn("Hours", format="localized"),
            "Cost": st.column_config.NumberColumn("Cost", format="localized"),
        },
    )
    st.markdown("**Direct costs**")
    st.dataframe(
        detail_tables["Direct costs"],
        hide_index=True,
        column_config={"Cost": st.column_config.NumberColumn("Cost", format="localized")},
    )

st.markdown("**Peer review, journal submissions and publishing**")
st.dataframe(detail_tables["Peer review, journal submissions and publishing"], hide_index=True)

if st.button("Hide raw JSON" if st.session_state.admin_show_json else "Show raw JSON", icon=":material/data_object:"):
    st.session_state.admin_show_json = not st.session_state.admin_show_json
    st.rerun()

if st.session_state.admin_show_json:
    st.json(state.to_dict())

show_authorisation_section(current_user)
