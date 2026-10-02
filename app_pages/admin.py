"""Page listing every result saved to the database, at BASE-URL/admin. It is not linked to from the calculator.

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
    from src.calculator_state import CalculatorState
    from src.models import Cost

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
                # NULL for simplified projects, which have no defaults to load.
                "Loaded Alam et al. defaults": None
                if project["loaded_alam_defaults"] is None
                else bool(project["loaded_alam_defaults"]),
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
            "Loaded Alam et al. defaults",
            "Currency",
            *RESEARCH_PHASES.values(),
            "Total",
        ],
    ).astype({"Loaded Alam et al. defaults": "boolean"})


st.set_page_config(page_title="Saved results", layout="wide")

st.title("Saved results")

if database.get_database_type() == "none":
    st.info("No database is configured, so there are no saved results.", icon=":material/info:")
    st.stop()

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
    st.stop()

if results.empty:
    st.info("No results have been saved yet.", icon=":material/info:")
    st.stop()

public_ids: list[str] = results.pop("public_id").astype(str).tolist()

# Link each result to its result page, with its public id filled in.
results.insert(
    0,
    "Link",
    calculator_url() + f"{RESULT_URL_PATH}?{database.PROJECT_ID_QUERY_PARAM}=" + pd.Series(public_ids),
)

# The public id of the result shown in the details section, kept across reruns.
if "admin_selected_id" not in st.session_state:
    st.session_state.admin_selected_id = None
if "admin_show_json" not in st.session_state:
    st.session_state.admin_show_json = False

table_event = st.dataframe(
    results,
    hide_index=True,
    key="admin_results_table",
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "Link": st.column_config.LinkColumn(
            "Link",
            help="Open this result's page.",
            display_text=f"{database.PROJECT_ID_QUERY_PARAM}=(.*)$",
            pinned=True,
        ),
        "Saved": st.column_config.DatetimeColumn("Saved", format="YYYY-MM-DD HH:mm"),
        "International collaboration": st.column_config.CheckboxColumn("International collaboration"),
        "Loaded Alam et al. defaults": st.column_config.CheckboxColumn(
            "Loaded Alam et al. defaults",
            help="Whether the defaults from Alam et al. (2026) were loaded. Blank for simplified results.",
        ),
        **{
            label: st.column_config.NumberColumn(label, format="localized")
            for label in [*RESEARCH_PHASES.values(), "Total"]
        },
    },
)

# Selecting a row loads that result into the details section. Clearing the selection keeps the loaded result.
selected_rows: list[int] = table_event.selection.rows
if selected_rows:
    selected_id: str = public_ids[selected_rows[0]]
    if selected_id != st.session_state.admin_selected_id:
        st.session_state.admin_selected_id = selected_id
        st.session_state.admin_show_json = False

st.subheader("Result details")

if st.session_state.admin_selected_id not in states:
    st.caption("Select a result in the table above (tick the box at the start of its row) to see its details.")
    st.stop()

state: CalculatorState = states[st.session_state.admin_selected_id]
currency: str = COUNTRY_CURRENCIES.get(state.user_country, ("", ""))[0]
st.caption(
    f"Result {st.session_state.admin_selected_id} · "
    f"{state.calculator_mode.capitalize()} · amounts in {currency or 'USD'}"
)

st.markdown("**Researchers**")
st.dataframe(
    pd.DataFrame(
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
    ),
    hide_index=True,
    column_config={"Hourly rate": st.column_config.NumberColumn("Hourly rate", format="localized")},
)

if state.calculator_mode == "simplified":
    st.markdown("**Phase hours and direct costs**")
    phase_rows: list[dict[str, Any]] = [
        {
            "Phase": RESEARCH_PHASES[phase],
            "Hours": sum(state.simplified_hours.get(phase, {}).values()),
            "Direct costs": state.simplified_direct_costs.get(phase, 0.0),
        }
        for phase in OVERALL_TOTAL_PHASES
    ]
    st.dataframe(
        pd.DataFrame(phase_rows, columns=["Phase", "Hours", "Direct costs"]),
        hide_index=True,
        column_config={
            "Hours": st.column_config.NumberColumn("Hours", format="localized"),
            "Direct costs": st.column_config.NumberColumn("Direct costs", format="localized"),
        },
    )
else:
    st.markdown("**Activities**")
    st.dataframe(
        pd.DataFrame(
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
        ),
        hide_index=True,
        column_config={
            "Hours": st.column_config.NumberColumn("Hours", format="localized"),
            "Cost": st.column_config.NumberColumn("Cost", format="localized"),
        },
    )
    st.markdown("**Direct costs**")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Direct cost": direct_cost.get_name(),
                    "Phase": RESEARCH_PHASES.get(direct_cost.get_phase(), direct_cost.get_phase()),
                    "Cost": direct_cost.get_total_cost(),
                }
                for direct_cost in state.effective_direct_costs()
            ],
            columns=["Direct cost", "Phase", "Cost"],
        ),
        hide_index=True,
        column_config={"Cost": st.column_config.NumberColumn("Cost", format="localized")},
    )

st.markdown("**Peer review and journal submissions**")
st.dataframe(
    pd.DataFrame(
        [
            {"Activity": "Peer review rounds", "Value": state.peer_review.review_rounds},
            {"Activity": "Journal editorial work submissions", "Value": state.journal_editing.journal_submissions},
        ],
        columns=["Activity", "Value"],
    ),
    hide_index=True,
)

if st.button("Hide raw JSON" if st.session_state.admin_show_json else "Show raw JSON", icon=":material/data_object:"):
    st.session_state.admin_show_json = not st.session_state.admin_show_json
    st.rerun()

if st.session_state.admin_show_json:
    st.json(state.to_dict())
