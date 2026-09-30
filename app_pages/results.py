"""Page listing every result saved to the database, at BASE-URL/results. It is not linked to from the calculator.

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
from src.calculator_state import compute_costs
from src.reference_data import COUNTRY_CURRENCIES, COUNTRY_NAMES, RESEARCH_PHASES, field_of_research_display_name

if TYPE_CHECKING:
    from src.calculator_state import CalculatorState
    from src.models import Cost

# url_path of this page, set in main.py.
RESULTS_URL_PATH: str = "results"


def calculator_url() -> str:
    """URL of the calculator, from the URL of this page, which is the calculator's URL followed by RESULTS_URL_PATH.

    Falls back to a relative URL when the browser's URL is unknown, e.g. when running under AppTest.
    """
    return (st.context.url or "./").removesuffix(RESULTS_URL_PATH)


@st.cache_data(ttl=60, show_spinner="Loading saved results...")
def load_results() -> pd.DataFrame:
    """Loads every saved project as one row of totals, most recently saved first.

    Cached for a minute so reruns of the page do not query the database each time. Costs are in the currency of each
    project's country, as saved.
    """
    with closing(database.connect()) as conn:
        projects: list[tuple[dict[str, Any], CalculatorState]] = sql_store.load_projects(conn)

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
                "Peer reviews": state.peer_review.review_rounds,
                "Journal submissions": state.peer_review.journal_submissions,
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
            "Peer reviews",
            "Journal submissions",
            "Currency",
            *RESEARCH_PHASES.values(),
            "Total",
        ],
    )


st.set_page_config(page_title="Saved results", layout="wide")

st.title("Saved results")

if database.get_database_type() == "none":
    st.info("No database is configured, so there are no saved results.", icon=":material/info:")
    st.stop()

with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
    st.caption("Every result saved from the calculator. Costs are in the currency of each result's country.")
    if st.button("Refresh", icon=":material/refresh:"):
        load_results.clear()

try:
    results: pd.DataFrame = load_results()
except database.DATABASE_ERRORS as error:
    st.error(f"Could not load the saved results from the database: {error}", icon=":material/error:")
    st.stop()

if results.empty:
    st.info("No results have been saved yet.", icon=":material/info:")
    st.stop()

# Link each result to the calculator with its public id filled in, which loads it.
results.insert(
    0, "Link", calculator_url() + f"?{database.PROJECT_ID_QUERY_PARAM}=" + results.pop("public_id").astype(str)
)

st.dataframe(
    results,
    hide_index=True,
    column_config={
        "Link": st.column_config.LinkColumn(
            "Link",
            help="Open this result in the calculator.",
            display_text=f"{database.PROJECT_ID_QUERY_PARAM}=(.*)$",
            pinned=True,
        ),
        "Saved": st.column_config.DatetimeColumn("Saved", format="YYYY-MM-DD HH:mm"),
        "International collaboration": st.column_config.CheckboxColumn("International collaboration"),
        **{
            label: st.column_config.NumberColumn(label, format="localized")
            for label in [*RESEARCH_PHASES.values(), "Total"]
        },
    },
)
