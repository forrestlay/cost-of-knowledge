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

import logging
import os
from collections.abc import Mapping
from contextlib import closing
from typing import TYPE_CHECKING, Any

import pandas as pd
import streamlit as st

from src import database, sql_store
from src.calculator_state import OVERALL_TOTAL_PHASES, compute_costs
from src.csv_safety import to_safe_csv
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

# Button labels for the named login providers that may be configured in the [auth] section of secrets.toml, e.g.
# [auth.google]. Providers not listed here are labelled with their name in title case.
LOGIN_PROVIDER_LABELS: dict[str, str] = {"google": "Google", "microsoft": "Microsoft"}

# Environment variables for the [auth] section of secrets.toml, which st.login reads, mapped to their keys in that
# section. They configure a single login provider, e.g. CLIENT_ID is [auth] client_id.
AUTH_ENVIRONMENT_VARIABLES: dict[str, str] = {
    "AUTH_REDIRECT_URI": "redirect_uri",
    "COOKIE_SECRET": "cookie_secret",
    "CLIENT_ID": "client_id",
    "CLIENT_SECRET": "client_secret",
    "SERVER_METADATA_URL": "server_metadata_url",
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


# Number of results per page of the results table, and the options for it.
PAGE_SIZES: tuple[int, ...] = (25, 50, 100)
# Number of results loaded at a time when exporting every result, so the export does not hold them all in memory.
EXPORT_CHUNK_SIZE: int = 200


@st.cache_data(ttl=60, show_spinner="Loading saved results...")
def count_saved() -> int:
    """Returns the number of saved projects. Cached for a minute."""
    with closing(database.connect()) as conn:
        return sql_store.count_projects(conn)


@st.cache_data(ttl=60, show_spinner="Loading saved results...")
def load_saved(limit: int, offset: int) -> list[tuple[dict[str, Any], CalculatorState]]:
    """Loads one page of saved projects and their calculator states, most recently saved first.

    Cached for a minute so reruns of the page do not query the database each time.
    """
    with closing(database.connect()) as conn:
        return sql_store.load_projects(conn, limit, offset)


@st.cache_data(ttl=60, show_spinner="Loading saved result...")
def load_one(public_id: str) -> CalculatorState | None:
    """Loads one saved project's calculator state, or None if it has been deleted. Cached for a minute."""
    try:
        with closing(database.connect()) as conn:
            return sql_store.load_project(conn, public_id)
    except KeyError:
        return None


def results_frame(projects: list[tuple[dict[str, Any], CalculatorState]]) -> pd.DataFrame:
    """Returns the given saved projects as one row of totals each, in the order given.

    Costs are in the currency of each project's country, as saved.
    """
    rows: list[dict[str, Any]] = []
    for project, state in projects:
        combined: list[Cost] = [*state.effective_activities(), *state.effective_direct_costs()]  # ty:ignore[invalid-assignment]
        rows.append(
            {
                "public_id": project["public_id"],
                "Saved": pd.to_datetime(project["created_at"]),
                "Version": state.version,
                "Country": COUNTRY_NAMES.get(state.user_country, state.user_country),
                "International collaboration": state.international_collaborators,
                "Field": field_of_research_display_name(state.project_field),
                "Researchers": sum(person.quantity for person in state.people.values()),
                "Peer reviewers": state.peer_review.peer_reviewers,
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
            "Version",
            "Country",
            "International collaboration",
            "Field",
            "Researchers",
            "Peer reviewers",
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


def export_all_results() -> str:
    """Returns every saved result as CSV text, loading the results in chunks. Run when the export button is clicked."""
    frames: list[pd.DataFrame] = []
    with closing(database.connect()) as conn:
        total: int = sql_store.count_projects(conn)
        for offset in range(0, total, EXPORT_CHUNK_SIZE):
            frame: pd.DataFrame = results_frame(sql_store.load_projects(conn, EXPORT_CHUNK_SIZE, offset))
            link_prefix: str = calculator_url() + f"{RESULT_URL_PATH}?{database.PROJECT_ID_QUERY_PARAM}="
            frame.insert(0, "Link", link_prefix + frame["public_id"].astype(str))
            frames.append(frame)
    return to_safe_csv(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), index=False)


def inject_auth_secrets() -> None:
    """Adds the authentication settings that are set as environment variables to st.secrets, for st.login to use.

    st.login reads only the [auth] section of secrets.toml. Settings that are already in st.secrets take precedence over
    environment variables, and variables that are not set or are empty are ignored.
    """
    environment_auth: dict[str, str] = {
        key: value for variable, key in AUTH_ENVIRONMENT_VARIABLES.items() if (value := os.environ.get(variable))
    }
    if not environment_auth:
        return

    # merge_programmatic_secrets replaces whole top-level keys, so the existing [auth] section is merged in first.
    existing_auth: dict[str, Any] = auth_secrets()
    merged_auth: dict[str, Any] = {**environment_auth, **existing_auth}
    if merged_auth != existing_auth:
        st.secrets.merge_programmatic_secrets({"auth": merged_auth})


def auth_secrets() -> dict[str, Any]:
    """Returns the [auth] section of st.secrets, or an empty dict when there is none."""
    try:
        auth: object = st.secrets.get("auth")
    except Exception:  # noqa: BLE001 - no secrets file
        auth = None
    return (
        {key: dict(value) if isinstance(value, Mapping) else value for key, value in auth.items()}
        if isinstance(auth, Mapping)
        else {}
    )


def login_providers() -> dict[str | None, str]:
    """Returns the login providers configured in st.secrets, mapped to their button labels.

    The single provider set directly in the [auth] section, such as by environment variables, is keyed by None, which
    st.login uses when given no provider. When it is set, it is the only provider. Otherwise, named providers from
    secrets.toml, e.g. [auth.google], are keyed by name.
    """
    auth: dict[str, Any] = auth_secrets()
    if auth.get("client_id"):
        return {None: "Log in"}
    return {
        name: f"Log in with {LOGIN_PROVIDER_LABELS.get(name, name.title())}"
        for name, settings in auth.items()
        if isinstance(settings, dict)
    }


def user_claim(name: str) -> str | None:
    """Returns a claim of the logged-in user's login as a string, or None if the provider did not give it."""
    value: object = st.user.get(name)
    return value if isinstance(value, str) else None


def owner_email() -> str | None:
    """Email address allowed to become the owner when nobody has logged in yet, from the ADMIN_OWNER_EMAIL secret or
    environment variable. When unset, the first user to log in becomes the owner.
    """
    value: object = None
    try:
        value = st.secrets.get("ADMIN_OWNER_EMAIL")
    except Exception:  # noqa: BLE001 - no secrets file
        value = None
    return str(value or os.environ.get("ADMIN_OWNER_EMAIL") or "").strip().lower() or None


def user_claim_verified() -> bool:
    """Whether the login provider has verified the user's email. Providers that omit the claim count as verified."""
    value: object = st.user.get("email_verified")
    return value is not False


def manage_user(click_key: str) -> None:
    """Runs the action of a button clicked in the users table, as the on_click callback of its button column.

    Args:
        click_key: The key of the button column, which holds the clicked row and button label in st.session_state.
    """
    click = st.session_state[click_key]
    user_id: str = st.session_state.admin_user_ids[click.row]
    # Checked again here, as the callback must not rely on the buttons only having been shown to the owner.
    if not st.user.is_logged_in:
        return
    acting_user_id: str = sql_store.admin_user_id(user_claim("iss"), user_claim("sub") or "")
    try:
        with closing(database.connect()) as conn:
            is_owner: bool = sql_store.is_admin_owner(conn, acting_user_id)
    except database.DATABASE_ERRORS:
        logging.getLogger(__name__).exception("Could not check the owner of the admin page.")
        st.session_state.admin_authorise_error = "Could not check your access."
        return
    if not is_owner:
        st.session_state.admin_authorise_error = "Only the owner can manage users."
        return
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


@st.dialog("Delete result")
def confirm_delete_result(public_id: str) -> None:
    """Asks the user to confirm deleting the saved result, then deletes it and clears it from the details section."""
    st.write(f"Delete result **{public_id}**? Its link will stop working. This cannot be undone.")
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button("Cancel"):
            st.rerun()
        if not st.button("Delete", type="primary", icon=":material/delete:"):
            return
    acting_user_id: str = sql_store.admin_user_id(user_claim("iss"), user_claim("sub") or "")
    try:
        with closing(database.connect()) as conn:
            # Checked again here, as the dialog reruns on its own without the access checks at the top of the page.
            if not any(
                user["user_id"] == acting_user_id and user["is_authorised"] for user in sql_store.list_admin_users(conn)
            ):
                st.error("You are not authorised to delete results.", icon=":material/error:")
                return
            sql_store.delete_project(conn, public_id)
    except database.DATABASE_ERRORS as error:
        st.error(f"Could not delete the result: {error}", icon=":material/error:")
        return
    count_saved.clear()
    load_saved.clear()
    load_one.clear()
    st.session_state.admin_selected_id = None
    st.session_state.admin_show_json = False
    st.rerun()


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
        for provider, label in login_providers().items():
            st.button(label, icon=":material/login:", on_click=st.login, args=(provider,))
    st.stop()

try:
    with closing(database.connect()) as conn:
        current_user: dict[str, Any] = sql_store.record_admin_login(
            conn,
            sql_store.admin_user_id(user_claim("iss"), user_claim("sub") or ""),
            user_claim("email"),
            user_claim("name"),
            owner_email=owner_email(),
            email_verified=user_claim_verified(),
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
        count_saved.clear()
        load_saved.clear()
        load_one.clear()

try:
    total_results: int = count_saved()
except database.DATABASE_ERRORS as error:
    st.error(f"Could not load the saved results from the database: {error}", icon=":material/error:")
    show_authorisation_section(current_user)
    st.stop()

if total_results == 0:
    st.info("No results have been saved yet.", icon=":material/info:")
    show_authorisation_section(current_user)
    st.stop()

with st.container(horizontal=True, vertical_alignment="bottom"):
    page_size: int = st.selectbox("Results per page", PAGE_SIZES, key="admin_page_size")
    page_count: int = max(1, -(-total_results // page_size))
    # Clamped, as results may have been deleted or the page size changed since the page was chosen.
    if st.session_state.get("admin_page", 1) > page_count:
        st.session_state.admin_page = page_count
    page: int = st.number_input("Page", min_value=1, max_value=page_count, step=1, key="admin_page")
    st.caption(f"{total_results} saved results, page {page} of {page_count}.")

try:
    page_projects: list[tuple[dict[str, Any], CalculatorState]] = load_saved(page_size, (page - 1) * page_size)
except database.DATABASE_ERRORS as error:
    st.error(f"Could not load the saved results from the database: {error}", icon=":material/error:")
    show_authorisation_section(current_user)
    st.stop()
results: pd.DataFrame = results_frame(page_projects)
states: dict[str, CalculatorState] = {str(project["public_id"]): state for project, state in page_projects}

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
        data=export_all_results,
        file_name="results.csv",
        mime="text/csv",
        icon=":material/download:",
        on_click="ignore",
    )

st.dataframe(
    results,
    hide_index=True,
    column_config={
        "Link": st.column_config.LinkColumn(
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
            help="Whether the publishing cost estimate is shown in the infographic. Results saved by older versions of "
            "the tool counted it towards the total; publishing costs no longer count towards the total.",
        ),
        **{
            label: st.column_config.NumberColumn(label, format="localized")
            for label in ["Publishing cost estimate", *RESEARCH_PHASES.values(), "Total"]
        },
    },
)

st.subheader("Result details")

# The selected result may be on another page than the one shown, so it is loaded by its id if it is not in this page.
selected_state: CalculatorState | None = None
if st.session_state.admin_selected_id is not None:
    selected_state = states.get(st.session_state.admin_selected_id) or load_one(st.session_state.admin_selected_id)
if selected_state is None:
    st.caption('Click "Load" on a result in the table above to see its details.')
    show_authorisation_section(current_user)
    st.stop()

state: CalculatorState = selected_state
currency: str = COUNTRY_CURRENCIES.get(state.user_country, ("", ""))[0]
st.caption(
    f"Result {st.session_state.admin_selected_id} · "
    f"Version {state.version} · {state.calculator_mode.capitalize()} · amounts in {currency or 'USD'}"
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
        {"Activity": "Peer reviewers", "Value": state.peer_review.peer_reviewers},
        {"Activity": "Peer review rounds", "Value": state.peer_review.review_rounds},
        {"Activity": "Journal editorial work submissions", "Value": state.journal_editing.journal_submissions},
        {
            "Activity": f"Publishing cost estimate ({COUNTRY_CURRENCIES.get(state.user_country, ('USD', ''))[0]}), "
            "not included in the total",
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
        data=to_safe_csv(loaded_export, index=False),
        file_name=f"result-{st.session_state.admin_selected_id}.csv",
        mime="text/csv",
        icon=":material/download:",
        on_click="ignore",
    )
    if st.button("Delete loaded result", icon=":material/delete:"):
        confirm_delete_result(str(st.session_state.admin_selected_id))

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
