"""Page showing a saved result, at BASE-URL/result?project_id=PUBLIC_ID. This is the link shared on social media.

The page shows the same charts and social media image as the calculator, but never the hours of labor, as for small
teams they could be used to approximate a salary. The hours are left out of the data of the charts too, not only
hidden, as the data of a chart is sent to the browser.

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
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

import streamlit as st

from src import database, sql_store
from src.calculator_state import compute_costs
from src.figures import (
    build_color_map,
    costs_dataframe,
    costs_pie_chart,
    create_social_media_svg,
    labour_bar_chart,
    labour_dataframe,
    labour_sunburst_chart,
    social_media_svg_to_png,
)
from src.reference_data import (
    COUNTRY_NAMES,
    FIELDS_OF_RESEARCH,
    RESEARCH_PHASES,
    currency_code,
    currency_prefix,
    format_currency,
)
from src.ui import toggletip, toggletip_styles

if TYPE_CHECKING:
    from src.calculator_state import CalculatorState
    from src.models import BaseActivity, Cost, DirectCost

# url_path of this page, set in main.py.
RESULT_URL_PATH: str = "result"


def calculator_url() -> str:
    """URL of the calculator, from the URL of this page, which is the calculator's URL followed by RESULT_URL_PATH.

    Drops the query string, so the calculator does not load the result. Falls back to a relative URL when the
    browser's URL is unknown, e.g. when running under AppTest.
    """
    page_url: str = urlsplit(st.context.url or "")._replace(query="", fragment="").geturl()
    return page_url.rstrip("/").removesuffix(RESULT_URL_PATH) if page_url else "./"


def back_to_calculator_button() -> None:
    """Shows the button to the calculator. It is a link, so the browser loads the calculator as a new session, which
    starts from a fresh state rather than the one of the result.
    """
    st.link_button(
        "Estimate your own Cost of Knowledge",
        calculator_url(),
        icon=":material/calculate:",
        type="primary",
    )


def load_result(public_id: str) -> CalculatorState | None:
    """Loads the project saved under the given public id, or shows why it could not be loaded and returns None."""
    if database.get_database_type() == "none":
        st.info("No database is configured, so results cannot be shown.", icon=":material/info:")
        return None
    try:
        with closing(database.connect()) as conn:
            return sql_store.load_project(conn, public_id)
    except KeyError:
        st.error(f"There is no result with id {public_id!r}.", icon=":material/error:")
    except database.DATABASE_ERRORS as error:
        st.error(f"Could not load the result from the database: {error}", icon=":material/error:")
    return None


st.set_page_config(page_title="The Cost of Knowledge - shared result", layout="wide")

# Enables toggletips (src.ui.toggletip) on this page.
toggletip_styles()

st.title("The Cost of Knowledge")

public_id: str | None = st.query_params.get(database.PROJECT_ID_QUERY_PARAM)
if public_id is None:
    st.info("No result was chosen.", icon=":material/info:")
    back_to_calculator_button()
    st.stop()

# Load only when the query parameter changes, so the charts' selections do not query the database on every rerun.
if public_id != st.session_state.get("result_public_id"):
    st.session_state["result_state"] = load_result(public_id)
    st.session_state["result_public_id"] = public_id
state: CalculatorState | None = st.session_state["result_state"]
if state is None:
    back_to_calculator_button()
    st.stop()

country: str = state.user_country
results_activities: list[BaseActivity] = state.effective_activities()
results_direct_costs: list[DirectCost] = state.effective_direct_costs()
combined_costs_list: list[Cost] = [*results_activities, *results_direct_costs]  # ty:ignore[invalid-assignment]
total_cost: float = compute_costs(combined_costs_list)

st.markdown(
    """
        <span style="font-size: 1.4rem">**As a researcher, have you thought about what it really costs to take a
        journal article from ideation to publication?**</span>

        Debates about the economics of scholarly publishing typically focus on subscription prices, article
        processing charges, publisher revenues, and profit margins. Much less attention is paid to the costs
        incurred in producing the research that makes scholarly publishing possible.

        The researcher who has shared their result with you has used the Cost of Knowledge Calculator to estimate the
        full cost of preparing and publishing one of their refereed journal articles.
        """,
    unsafe_allow_html=True,
)

social_media_svg: str = create_social_media_svg(
    country=COUNTRY_NAMES.get(country, ""),
    international_collaborators=state.international_collaborators,
    project_field=FIELDS_OF_RESEARCH[state.project_field].name
    if state.project_field in FIELDS_OF_RESEARCH
    else state.project_field,
    total_cost=total_cost,
    total_hours=0.0,
    phase_costs={label: compute_costs(combined_costs_list, phase=key) for key, label in RESEARCH_PHASES.items()},
    format_currency=lambda amount: format_currency(amount, country),
    show_hours=False,
).as_svg()
with st.container(horizontal=True, horizontal_alignment="center"):
    st.image(social_media_svg_to_png(social_media_svg), width=540)

st.markdown(
    """
         You can try the Cost of Knowledge Calculator yourself:
    """,
    text_alignment="center",
)

with st.container(horizontal=True, horizontal_alignment="center"):
    back_to_calculator_button()

# Same colour maps as the calculator, so each phase and activity has the same colour on both pages.
phase_color_map: dict[str, str] = build_color_map(list(RESEARCH_PHASES.values()))
item_color_map: dict[str, str] = build_color_map([item.get_name() or "Unnamed" for item in combined_costs_list])


st.header("The Cost of This Refereed Journal Article")

st.markdown(
    """
        These results should not be taken to reflect or quantify the value of research, only the costs
        involved in preparing a refereed journal article. Prior literature has established that research provides
        substantial economic and social returns{footnote_1}, and with this tool we instead seek to draw attention
        to the resources required for scholarly publishing.
        """.replace(
        "{footnote_1}",
        toggletip(
            "<sup>1</sup>",
            "Jones, B. F., & Summers, L. H. (Eds.). (2022). A Calculation of the Social Returns to Innovation. In "
            "Innovation and Public Policy (pp. 13-60). University of Chicago Press. "
            "https://doi.org/10.7208/chicago/9780226805597.003.0002; Salter, A. J., & Martin, B. R. (2001). "
            "The economic benefits of publicly funded basic research: A critical review. Research Policy, 30(3), "
            "509-532. https://doi.org/10.1016/S0048-7333(00)00091-3.",
        ),
    ),
    unsafe_allow_html=True,
)

k1, k2 = st.columns(2)
k1.metric("Estimated total cost", format_currency(total_cost, country))
k2.metric("Estimated direct costs", format_currency(compute_costs(results_direct_costs), country))

with st.container(border=True):
    colorblind_safe_graphs: bool = st.toggle("Enable colorblind safe graphs", value=False, key="colorblind_safe_graphs")


st.subheader("Total cost breakdown")

costs_chart_selection = st.pills(
    "**Show cost breakdown for**",
    ["phases", "activities and direct costs"],
    default="phases",
)
costs_pie_names: Literal["Phase", "Item"] = "Phase" if costs_chart_selection == "phases" else "Item"
st.plotly_chart(
    costs_pie_chart(
        costs_dataframe(combined_costs_list),
        costs_pie_names,
        phase_color_map,
        item_color_map,
        hatching=colorblind_safe_graphs,
    ),
    width="stretch",
)


st.subheader("Labor activity breakdown")

# Without the hours, which must not reach the browser.
labour_df = labour_dataframe(results_activities, include_hours=False)

# The sunburst breaks costs down by activity, so it is only shown for the granular calculator.
if state.calculator_mode == "granular":
    st.markdown("""
                Click on the phases and people in the chart below to see the breakdown of costs within each. Click on
                the phase or person again to return to the parent view.
                """)
    st.plotly_chart(
        labour_sunburst_chart(
            labour_df, phase_color_map, total_cost, currency_code(country), hatching=colorblind_safe_graphs
        ),
        width="stretch",
    )
    st.caption(
        "Percentages are calculated as a percentage of the total cost of the "
        "paper, including direct costs that are not shown in this chart."
    )

st.plotly_chart(
    labour_bar_chart(
        labour_df,
        "Cost",
        "Cost of Labor Activities",
        phase_color_map,
        currency_code(country),
        currency_prefix(country),
        hatching=colorblind_safe_graphs,
    ),
    width="stretch",
)

with st.container(horizontal=True, horizontal_alignment="center"):
    back_to_calculator_button()

st.divider()
st.markdown(
    """
        :small[<sup>1</sup> Jones, B. F., & Summers, L. H. (Eds.). (2022). *A Calculation of the Social Returns to
        Innovation.* In Innovation and Public Policy (pp. 13–60). University of Chicago Press.
        https://doi.org/10.7208/chicago/9780226805597.003.0002;
        Salter, A. J., & Martin, B. R. (2001). *The economic benefits of publicly funded basic research: A critical
        review.* Research Policy, 30(3), 509–532. https://doi.org/10.1016/S0048-7333(00)00091-3.]

        :small[:material/copyright: Copyright 2026 Alam, Andrew, Baker, Coupe, Koh,
        Lay, Loh, and Tanima.
        :material/license: The content on this website is subject to the [Creative Commons Attribution 4.0
        International License](https://creativecommons.org/licenses/by/4.0/).]

        :small[[Privacy Policy](https://sparcopen.org/privacy-policy/)]
        """,
    unsafe_allow_html=True,
)
