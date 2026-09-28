#!/usr/bin/env python3

"""Cost of Knowledge Visualisation Tool

This Streamlit application can be used to estimate the cost of producing and publishing a research journal article and
visualise the breakdown of those costs.

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

import json
import logging
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import quote

import drawsvg as draw
import pandas as pd
import plotly.express as px
import resvg_py
import streamlit as st

from src import database, sql_store
from src.calculator_state import CalculatorState, compute_costs, compute_hours
from src.currency_rates import convert_currency
from src.database import DatabaseType, get_database_type, init_database
from src.models import (
    Activity,
    DirectCost,
    Person,
    PersonType,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.models import Cost

st.set_page_config(page_title="Cost of Knowledge Calculator", layout="wide")

COST_OF_KNOWLEDGE_URL: str = "https://costofknowledge.org"

# Placeholder hex values that Streamlit's frontend swaps for its theme's categorical
# colour palette (see streamlit/elements/lib/streamlit_plotly_theme.py). Assigning one
# of these to a category keeps that phase or activity on the same Streamlit colour in
# every chart. Charts with more than 10 categories fall back to px.colors.qualitative.Light24.
STREAMLIT_CATEGORICAL_COLORS: list[str] = [f"#{n:06d}" for n in range(1, 11)]

# Default hourly rate of labour for new people, in USD. Converted to the user's currency when a person is added.
DEFAULT_HOURLY_RATE_USD: float = 85.0

TOOL_STEPS: list[str] = [
    "project",
    "people",
    "incubation",
    "data",
    "writing",
    "editing",
    "save",
    "end",
]

SCIENTIFIC_FIELDS: list[str] = [
    "Natural sciences",
    "Formal sciences",
    "Social sciences",
    "Applied sciences/engineering",
]

# Country list loaded from data/country.json. The selectbox shows the country name
# but stores the lowercase country code (e.g. "us") as the value.
_COUNTRY_DATA: list[dict[str, object]] = json.loads(
    (Path(__file__).parent / "data" / "country.json").read_text(encoding="utf-8")
)
COUNTRY_NAMES: dict[str, str] = {str(country["code"]): str(country["name"]) for country in _COUNTRY_DATA}
COUNTRY_CODES: list[str] = sorted(COUNTRY_NAMES, key=lambda code: COUNTRY_NAMES[code])
# ISO 4217 currency code (e.g. "USD") and symbol (e.g. "$") for each country code.
COUNTRY_CURRENCIES: dict[str, tuple[str, str]] = {
    str(country["code"]): (
        str(country["currency_code"]),
        str(country["currency_symbol"]),
    )
    for country in _COUNTRY_DATA
}

ROLES: list[str] = [
    "Professor",
    "Associate Professor",
    "Assistant Professor",
    "Instructor",
    "Lecturer",
    "Senior Lecturer",
    "Associate Lecturer",
    "Research Assistant",
    "Peer reviewer",
    "Journal editor",
    "Other",
]

RESEARCH_PHASES: dict[str, str] = {
    "incubation": "Incubation",
    "data": "Data collection and analysis",
    "writing": "Manuscript preparation",
    "editing": "Peer review and journal editorial work",
}

# TODO: Add sharing of PDF and PNG, put names on PDF

ACTIVITY_OPTIONS: dict[str, list[str]] = {
    "incubation": [
        "Ideation and conception",
        "Ethics approval",
        "Grant applications",
        "Other",
    ],
    "data": [
        "Data collection",
        "Data analysis",
        "Interview transcription",
        "Other",
    ],
    "writing": [
        "Writing and manuscript preparation",
        "Conferencing (labor)",
    ],
}

COST_OPTIONS: dict[str, list[str]] = {
    "incubation": [],
    "data": [
        "Software",
        "Databases",
        "Participant incentivization",
    ],
    "writing": [
        "Proofreading and Editing Services",
        "Conferencing (direct costs)",
    ],
}


def currency_code() -> str:
    """ISO 4217 code (e.g. "USD") of the currency of the country chosen by the user."""
    return COUNTRY_CURRENCIES[st.session_state["user_country"]][0]


def currency_prefix() -> str:
    """Prefix put before amounts in the chosen country's currency.

    The currency symbol (e.g. "$"), or the ISO code and a space (e.g. "AED ") for currencies without one.
    """
    code, symbol = COUNTRY_CURRENCIES[st.session_state["user_country"]]
    return symbol if symbol != code else f"{code} "


def format_currency(x: int | float) -> str:
    """Formats an int or float to a string in the currency of the country chosen by the user."""
    return f"{currency_prefix()}{x:,.0f} ({currency_code()})"


# -----------------------------------------------
# Model variables
# -----------------------------------------------

# Populate every calculator input (project details, people, activities, direct costs and progress through the tool)
# with the default state on the first run. CalculatorState.apply_to_session_state is also how a serialised
# calculator is imported, so the defaults and the serialised fields are defined in one place (calculator_state.py).
if "activity_list" not in st.session_state:
    CalculatorState.default().apply_to_session_state(st.session_state)

if "user_country_select" not in st.session_state:
    st.session_state["user_country_select"]: str = st.session_state["user_country"]

# Create and initialise the database set by DATABASE_TYPE, if any. Saving is disabled when it is "none".
DATABASE_TYPE: DatabaseType = get_database_type()

# Tried once per session, so an unreachable database does not slow every rerun. Saving connects again, and reports
# the error to the user if the database is still unreachable.
if "database_initialised" not in st.session_state:
    try:
        init_database()
    except database.DATABASE_ERRORS:
        logging.getLogger(__name__).exception("Could not initialise the %s database.", DATABASE_TYPE)
    st.session_state["database_initialised"] = True

# Query parameter holding the public id of a project saved to the database, e.g. ?project_id=V1StGXR8_Z5jdHi6B-myT,
# which is loaded on page load.
PROJECT_ID_QUERY_PARAM: str = "project_id"


def load_from_database(public_id: str) -> None:
    """Replaces the calculator's inputs with the project saved in the database under the given public id.

    Must run before any widget is rendered, as it replaces widget state. Later saves in the session update the loaded
    project.
    """
    if DATABASE_TYPE == "none":
        st.toast("Could not load the project: no database is configured.", icon=":material/error:")
        return
    try:
        with closing(database.connect()) as conn:
            state: CalculatorState = sql_store.load_project(conn, public_id)
    except KeyError:
        st.toast(f"Could not load the project: no project with id {public_id!r}.", icon=":material/error:")
        return
    except database.DATABASE_ERRORS as error:
        st.toast(f"Could not load the project from the database: {error}", icon=":material/error:")
        return
    state.apply_to_session_state(st.session_state)
    st.session_state["database_public_id"] = public_id
    st.toast("Loaded the project from the database.", icon=":material/check_circle:")


# Load only when the query parameter changes, so the user's edits are not overwritten by the saved project every rerun.
query_project_id: str | None = st.query_params.get(PROJECT_ID_QUERY_PARAM)
if query_project_id is not None and query_project_id != st.session_state.get("loaded_query_project_id"):
    st.session_state["loaded_query_project_id"] = query_project_id
    load_from_database(query_project_id)

# -----------------------------------------------
# Header
# -----------------------------------------------

st.title("Cost of Knowledge Calculator")
st.caption(
    "The tool will enable you to calculate the approximate cost of preparing a refereed journal article from conception"
    " to publication."
)

st.markdown("""
            Debates about the economics of scholarly publishing typically focus on subscription prices, article
            processing charges, publisher revenues, and profit margins. Much less attention is paid to the costs
            incurred in producing the research that makes scholarly publishing possible. This tool aims to make visible
            the substantial investment underpinning scholarly publishing.
            """)

with st.expander("About the data", expanded=False):
    st.markdown("""
                The tool has been pre-populated with information that rests of a number of assumptions. Some of this
                data is based on the accompanying publication, while other data is based on less robust estimations.
                You are invited to fill in your own costs and estimates to produce a more accurate picture of the cost
                of producing one of your publications.
                """)

# -----------------------------------------------
# User and Project
# -----------------------------------------------
st.header(":material/article_person: You and Your Project")
st.markdown("""
            Please fill in some details about you and the research publication or project you want to estimate the cost
            of.
            """)


def next_tool_step(current_step: str):
    """Navigates to the next step in the tool, opening the relevant expander.

    Each step's expander is keyed as ``f"{step}-expander"`` in st.session_state.
    When ``current_step`` is the active step, its expander is collapsed,
    ``tool_step`` advances and the next step's expander is expanded. When
    ``current_step`` is not the active step (its "Next step" button was pressed
    from an expander the user re-opened after moving on), that expander is simply
    collapsed.

    Args:
        current_step: The current step, matching a string in TOOL_STEPS.
    """
    st.session_state[f"{current_step}-expander"]: bool = False
    if (
        st.session_state["tool_step"] < len(TOOL_STEPS) - 1
        and current_step == TOOL_STEPS[st.session_state["tool_step"]]
    ):
        st.session_state["tool_step"]: int = 1 + st.session_state["tool_step"]
        next_step: str = TOOL_STEPS[st.session_state["tool_step"]]
        st.session_state[f"{next_step}-expander"]: bool = True


def update_default_person_name():
    """Syncs the default person's name with the user's name input.

    The default person (unique_key "1") represents the tool user, so keep its name in
    st.session_state["people"] in step with the "Your name" field. Does nothing if the
    user has deleted the default person.
    """
    st.session_state["user_name"] = st.session_state["user_name_input"]
    default_person: Person | None = st.session_state["people"].get("1")
    if default_person is not None:
        default_person.name = st.session_state["user_name"] or "Associate Professor"
        # Also push the new name into the "People or Roles" selectbox widget state;
        # once that widget has a stored value it ignores its index= argument, so
        # updating only default_person.name would not move the displayed selection.
        st.session_state[f"person-name-{default_person.unique_key}"] = default_person.name


project_step: bool = TOOL_STEPS[st.session_state["tool_step"]] == "project"

with st.expander(
    "You and your project",
    expanded=project_step,
    key="project-expander",
    on_change="rerun",
):
    st.session_state["user_name"] = st.text_input(
        "Your name",
        key="user_name_input",
        on_change=update_default_person_name,
    )

    def convert_monetary_values():
        """Converts every monetary value to the currency of the newly selected country, then updates user_country."""
        from_code: str = currency_code()
        to_code: str = COUNTRY_CURRENCIES[st.session_state["user_country_select"]][0]
        st.session_state["user_country"] = st.session_state["user_country_select"]
        if from_code == to_code:
            return

        def convert(amount: int | float) -> float:
            converted: float | None = convert_currency(amount, from_code, to_code)
            return 0.0 if converted is None else round(converted, 2)

        # Check a rate exists for both currencies before changing anything, so values are never left half-converted.
        if convert(1) is None:
            st.toast(
                f"Exchange rates for {from_code} to {to_code} are unavailable, so costs have not been converted.",
                icon=":material/currency_exchange:",
            )
            return

        people: list[Person] = [
            *st.session_state["people"].values(),
            st.session_state["peer_reviewer"],
            st.session_state["journal_editor"],
        ]
        for person in people:
            person.hourly_rate = convert(person.hourly_rate)
            # Drop the widget's state so the number_input picks up the converted rate as its value.
            st.session_state.pop(f"person-rate-{person.unique_key}", None)
        for direct_cost in st.session_state["cost_list"]:
            direct_cost.cost = convert(direct_cost.cost)
            st.session_state.pop(f"directcost-cost-{direct_cost.unique_key}", None)

        st.toast(f"Costs converted from {from_code} to {to_code}.", icon=":material/currency_exchange:")

    st.selectbox(
        "The country your research project is primarily associated with/where most of the costs are incurred",
        COUNTRY_CODES,
        format_func=lambda code: COUNTRY_NAMES[code],
        key="user_country_select",
        on_change=convert_monetary_values,
    )
    st.session_state["international_collaborators"] = st.radio(
        "Does your project have international collaborators outside of the primary country?",
        [False, True],
        index=int(st.session_state["international_collaborators"]),
        format_func=lambda answer: "Yes" if answer else "No",
        horizontal=True,
    )
    st.session_state["project_name"] = st.text_input(
        "Name of your paper/project", value=st.session_state["project_name"]
    )
    st.session_state["project_field"] = st.selectbox(
        "Field of science your paper/project is located in",
        SCIENTIFIC_FIELDS,
        index=SCIENTIFIC_FIELDS.index(st.session_state["project_field"]),
    )
    st.button(
        "Next step",
        key="confirm-project",
        type="primary",
        icon=":material/check:",
        on_click=next_tool_step,
        args=["project"],
    )

# -----------------------------------------------
# Study team
# -----------------------------------------------

st.header(":material/groups: People Involved in the Article Preparation Process")
st.markdown("""
            Fill in the details of the people on your study team or who are otherwise involved in the preparation of
            your journal article in the incubation, data collection and analysis, and manuscript preparation phases.
            The hourly rates below will be used to calculate the cost of labor for most of the steps involved in the
            journal preparation process.
            """)


def add_person(key: str | None = None):
    """Adds a new person role to the tool.

    Args:
        key: A unique_key for the Person. If None, a numerical key will be assigned to the person automatically.
    """
    if key is None:
        # First find the highest unique_key issued so far. Then add one to that key.
        person_key_list: list[int] = [
            int(person.unique_key) for person in st.session_state["people"].values() if person.unique_key.isdigit()
        ]
        key = str(max(person_key_list) + 1)
    # Start new people at the default rate in the user's currency, or in USD if no exchange rate is available.
    hourly_rate: float | None = convert_currency(DEFAULT_HOURLY_RATE_USD, "USD", currency_code())
    st.session_state["people"][key] = Person(
        name=None,
        unique_key=key,
        person_type=PersonType.RESEARCH_TEAM,
        hourly_rate=DEFAULT_HOURLY_RATE_USD if hourly_rate is None else round(hourly_rate, 2),
    )


def delete_person(key: str):
    del st.session_state["people"][key]


@st.dialog("Calculate your hourly rate")
def calculate_hourly_rate(person: Person, key: str):
    salary: int = st.number_input(f"What is your salary in {currency_code()}?", step=1, min_value=0)
    months: int = st.number_input(
        "What is the period for which that salary is paid in months?",
        step=1,
        value=12,
        min_value=1,
    )
    weekly_hours: int = st.number_input(
        "How many hours are you required to work per week?",
        step=1,
        value=40,
        min_value=1,
    )
    indirect_cost_percentage: int = st.slider(
        "Indirect costs multiplier",
        step=1,
        value=40,
        min_value=0,
        max_value=100,
    )
    indirect_cost_multiplier: float = 1 + (indirect_cost_percentage / 100)
    if st.button("Calculate"):
        # Write the computed rate straight into the number_input's widget state so
        # it shows on the next run. Once the widget exists its value can only be
        # changed through its own session_state entry, not via its value= default.
        st.session_state[f"person-rate-{key}"] = Person.salary_to_hourly_rate(
            salary, weekly_hours, months, indirect_cost_multiplier
        )
        st.rerun()


# Check if tool is at the people step, expand Roles expander if True.
people_step: bool = TOOL_STEPS[st.session_state["tool_step"]] == "people"

with st.expander(
    "People or Roles",
    expanded=people_step,
    key="people-expander",
    on_change="rerun",
):
    for key, person in st.session_state["people"].items():
        with st.container(border=True):
            # Show the person's current name in the selectbox even when it is a
            # custom value not in ROLES (e.g. a name synced from the "Your name"
            # field). A newly added person has no name yet, so leave the selectbox
            # unselected (index=None).
            name_options: list[str] = ROLES
            person_name_index: int | None
            if person.name is None:
                person_name_index = None
            elif person.name in ROLES:
                person_name_index = ROLES.index(person.name)
            else:
                name_options = ROLES + [person.name]
                person_name_index = len(ROLES)

            # If person.name widget already has been set in session state, set index to zero as a default value is no
            # longer needed.
            person_name_key: str = f"person-name-{person.unique_key}"
            if person_name_key in st.session_state:
                person_name_index = None

            # Inputs
            person.name: str | None = st.selectbox(
                "Name",
                options=name_options,
                index=person_name_index,
                accept_new_options=True,
                key=person_name_key,
            )
            # Once the widget has its own session_state entry (e.g. after the
            # "Calculate your hourly rate" dialog writes the computed rate into
            # it) that value wins and value= is ignored, so pass the "min"
            # sentinel instead of a default to avoid Streamlit's "created with a
            # default value but also had its value set via the Session State API"
            # warning.
            person_rate_key: str = f"person-rate-{person.unique_key}"
            person_rate_value: float | Literal["min"] = (
                "min" if person_rate_key in st.session_state else float(person.hourly_rate)
            )
            person.hourly_rate: int | float = st.number_input(
                f"Hourly rate of labor including indirect on-costs (in {currency_code()})",
                min_value=0.0,
                value=person_rate_value,
                key=person_rate_key,
            )
            with st.container(horizontal=True, horizontal_alignment="left"):
                if st.button(
                    "Calculate hourly wage using salary",
                    key=f"calculate-hourly-wage-{person.unique_key}",
                ):
                    calculate_hourly_rate(person, person.unique_key)
                if person.person_type == PersonType.RESEARCH_TEAM and int(person.unique_key) > 1:
                    st.button(
                        f"Delete {person.name or 'person'}",
                        key=f"delete-person-{person.unique_key}",
                        icon=":material/delete:",
                        on_click=delete_person,
                        args=[person.unique_key],
                    )

    with st.container(horizontal=True, horizontal_alignment="left"):
        st.button(
            "Add person/role",
            key="add-person",
            icon=":material/add:",
            on_click=add_person,
        )
        st.button(
            "Finalize team",
            key="confirm-team",
            type="primary",
            icon=":material/check:",
            on_click=next_tool_step,
            args=["people"],
        )

# -----------------------------------------------
# Calculator
# -----------------------------------------------


def person_option_display(key: str):
    """Converts a st.session_state["people"] key to a st.selectbox display name."""
    person: Person = st.session_state["people"][key]
    if person.person_type == PersonType.RESEARCH_TEAM:
        return f"{key}: {person.name or 'Unnamed'}"
    return key


def person_option_decode(display_string: str):
    """Converts a st.selectbox display name to a st.session_state["people"] key."""
    return display_string.split(":")[0]


def set_activity_person(activity: Activity, counter: int):
    """Callback for st.selectbox to select the person assigned to an activity."""
    people_key: str = person_option_decode(st.session_state[f"activity-person-{counter}"])
    activity.person: Person = st.session_state["people"][people_key]


def next_activity_key() -> int:
    """Returns an unused unique_key for a new Activity."""
    activity_key_list: list[int] = [activity.unique_key for activity in st.session_state["activity_list"]]
    return max(activity_key_list, default=0) + 1


def next_activity_group_key() -> int:
    """Returns an unused group_key, identifying a new activity rather than a person within one."""
    group_key_list: list[int] = [
        activity.group_key for activity in st.session_state["activity_list"] if isinstance(activity, Activity)
    ]
    return max(group_key_list, default=0) + 1


def add_activity(phase: str):
    """Adds a new activity to the given phase with a single person assigned to it."""
    st.session_state["activity_list"].append(
        Activity(
            None,
            st.session_state["people"]["1"],
            phase,
            0.0,
            next_activity_key(),
            next_activity_group_key(),
        )
    )


def add_activity_person(activity: Activity):
    """Assigns another person to an existing activity.

    Args:
        activity: Any Activity belonging to the activity the person is added to. The new person shares its name,
            phase and group_key.
    """
    st.session_state["activity_list"].append(
        Activity(
            activity.name,
            st.session_state["people"]["1"],
            activity.phase,
            0.0,
            next_activity_key(),
            activity.group_key,
        )
    )


def delete_activity_person(activity: Activity):
    """Removes a single person from an activity, leaving the other people assigned to it in place."""
    st.session_state["activity_list"].remove(activity)


def delete_activity(activities: list[Activity]):
    """Deletes an activity, removing every person assigned to it.

    Args:
        activities: Every Activity sharing the deleted activity's group_key.
    """
    for activity in activities:
        st.session_state["activity_list"].remove(activity)


def add_direct_cost(phase: str):
    cost_key_list: list[int] = [direct_cost.unique_key for direct_cost in st.session_state["cost_list"]]
    st.session_state["cost_list"].append(DirectCost(None, phase, 0.0, max(cost_key_list) + 1))


def delete_direct_cost(direct_cost: DirectCost):
    st.session_state["cost_list"].remove(direct_cost)


def save_to_database() -> None:
    """Saves the calculator's current inputs to the configured database.

    The first save creates a new project, and later saves in the same session update that project. Its public id is kept
    in st.session_state["database_public_id"] so it persists across script reruns.
    """
    state: CalculatorState = CalculatorState.from_session_state(st.session_state)
    public_id: str | None = st.session_state.get("database_public_id")
    try:
        with closing(database.connect()) as conn:
            if public_id is not None:
                try:
                    sql_store.update_project(conn, public_id, state)
                except KeyError:
                    # The saved project was deleted from the database, so save it again as a new project.
                    public_id = None
            if public_id is None:
                public_id = sql_store.save_project(conn, state)
    except database.DATABASE_ERRORS as error:
        st.toast(f"Could not save to the database: {error}", icon=":material/error:")
        return
    st.session_state["database_public_id"] = public_id
    st.toast("Saved to the database.", icon=":material/check_circle:")


st.header(":material/request_quote: Calculator")

main_left, main_right = st.columns([1, 2])

# Activities and costs setup pane
with main_left:
    st.markdown("""
                Provide details of the activities and costs involved in preparing your journal article. The process
                has been divided between four distinct phases: incubation, data collection and analysis, manuscript
                preparation, and peer review and journal editorial work.
                """)

    for phase, phase_name in RESEARCH_PHASES.items():
        # Expand expander if the current tool step is the current phase.
        phase_expand: bool = TOOL_STEPS[st.session_state["tool_step"]] == phase

        # Handle special phases.
        if phase == "editing":
            with st.expander(
                phase_name,
                expanded=phase_expand,
                key=f"{phase}-expander",
                on_change="rerun",
            ):
                st.markdown("""
                            The cost of peer review and journal editorial work is based on the number of journals
                            submitted to and the average number of review rounds across journal submissions. We
                            assume that peer reviewers and journal editors have an average hourly rate of labour
                            equivalent to the loaded rate of a mid-career associate professor, though you may change
                            this rate below.
                            """)

                st.session_state["review_rounds"]: int = st.slider(
                    "Average number of review rounds per journal submission",
                    min_value=1,
                    max_value=20,
                    value=st.session_state["review_rounds"],
                    step=1,
                    key="review-rounds",
                )
                st.session_state["peer_review_activity"].review_rounds: int = st.session_state["review_rounds"]

                st.session_state["journal_submissions"]: int = st.slider(
                    "Number of journals submitted to",
                    min_value=1,
                    max_value=20,
                    value=st.session_state["journal_submissions"],
                    step=1,
                    key="journal-submissions",
                )
                st.session_state["peer_review_activity"].journal_submissions: int = st.session_state[
                    "journal_submissions"
                ]
                st.session_state["journal_editing_activity"].journal_submissions: int = st.session_state[
                    "journal_submissions"
                ]

                st.session_state["peer_reviewer"].hourly_rate: int | float = st.number_input(
                    f"Hourly rate of peer reviewer (in {currency_code()})",
                    min_value=0.0,
                    value=float(st.session_state["peer_reviewer"].hourly_rate),
                )
                st.session_state["journal_editor"].hourly_rate: int | float = st.number_input(
                    f"Hourly rate of journal editor (in {currency_code()})",
                    min_value=0.0,
                    value=float(st.session_state["journal_editor"].hourly_rate),
                )
                with st.container(horizontal=True, horizontal_alignment="left"):
                    st.button(
                        "Finalise cost calculation",
                        key=f"next-phase-{phase}",
                        icon=":material/check:",
                        type="primary",
                        on_click=next_tool_step,
                        args=[phase],
                    )
        else:
            with st.expander(
                phase_name,
                expanded=phase_expand,
                key=f"{phase}-expander",
                on_change="rerun",
            ):
                phase_activities: list[Activity] = [
                    activity
                    for activity in st.session_state["activity_list"]
                    if isinstance(activity, Activity) and activity.get_phase() == phase
                ]
                # Group the phase's activities by group_key, as every person assigned to an activity is held as a
                # separate Activity sharing that key.
                activity_groups: dict[int, list[Activity]] = {}
                for phase_activity in phase_activities:
                    activity_groups.setdefault(phase_activity.group_key, []).append(phase_activity)

                for group_key, group_activities in activity_groups.items():
                    with st.container(border=True):
                        # Offer the phase's preset activities, keeping any current custom name selectable.
                        # A newly added activity has no name yet, so leave the selectbox unselected.
                        current_activity_name: str | None = group_activities[0].name
                        activity_options: list[str] = ACTIVITY_OPTIONS.get(phase, [])
                        activity_name_index: int | None
                        if current_activity_name is None:
                            activity_name_index = None
                        else:
                            if current_activity_name not in activity_options:
                                activity_options = [current_activity_name] + activity_options
                            activity_name_index = activity_options.index(current_activity_name)
                        activity_name: str | None = st.selectbox(
                            "Activity",
                            options=activity_options,
                            index=activity_name_index,
                            accept_new_options=True,
                            key=f"activity-name-{group_key}",
                        )
                        # Keep the name of every person's Activity in step with the renamed activity.
                        for group_activity in group_activities:
                            group_activity.name: str | None = activity_name

                        # Create badge if new activity
                        if activity_name is None:
                            st.badge(
                                "New activity, fill in details",
                                icon=":material/exclamation:",
                                color="orange",
                            )

                        # One row of inputs per person assigned to this activity.
                        for person_index, group_activity in enumerate(group_activities):
                            try:  # Get index of person in list of people.
                                activity_person_index: int = list(st.session_state["people"].keys()).index(
                                    group_activity.person.unique_key
                                )
                            except ValueError:
                                activity_person_index: int = 0

                            # Only label the first row so the rows below it read as a list.
                            row_label_visibility: str = "visible" if person_index == 0 else "collapsed"
                            person_column, hours_column, delete_column = st.columns(
                                [2, 1, 1], vertical_alignment="bottom"
                            )
                            person_column.selectbox(
                                "Assigned person",
                                st.session_state["people"].keys(),
                                key=f"activity-person-{group_activity.unique_key}",
                                index=activity_person_index,
                                format_func=person_option_display,
                                label_visibility=row_label_visibility,
                                on_change=set_activity_person,
                                args=[group_activity, group_activity.unique_key],
                            )
                            group_activity.hours: float = hours_column.number_input(
                                "Hours",
                                key=f"activity-hours-{group_activity.unique_key}",
                                min_value=0.0,
                                step=0.5,
                                value=float(group_activity.get_hours()),
                                label_visibility=row_label_visibility,
                            )
                            # An activity always keeps its first person, so that row has no delete button.
                            if person_index > 0:
                                delete_column.button(
                                    "Del",
                                    key=f"delete-activity-person-{group_activity.unique_key}",
                                    help=f"Remove {group_activity.person.name or 'this person'} from this activity",
                                    icon=":material/delete:",
                                    on_click=delete_activity_person,
                                    args=[group_activity],
                                )

                        # Show badge if nobody assigned to the activity has been given any hours.
                        if compute_hours(group_activities) == 0.0:
                            st.badge(
                                "Hours are set to 0",
                                icon=":material/exclamation:",
                                color="orange",
                            )

                        with st.container(horizontal=True, horizontal_alignment="left"):
                            st.button(
                                "Add person",
                                key=f"add-activity-person-{group_key}",
                                icon=":material/person_add:",
                                on_click=add_activity_person,
                                args=[group_activities[0]],
                            )
                            st.button(
                                "Delete activity",
                                key=f"delete-activity-{group_key}",
                                icon=":material/delete:",
                                on_click=delete_activity,
                                args=[group_activities],
                            )

                phase_costs: list[DirectCost] = [
                    direct_cost for direct_cost in st.session_state["cost_list"] if direct_cost.phase == phase
                ]
                for phase_cost in phase_costs:
                    with st.container(border=True):
                        # Offer the phase's preset direct costs, keeping any current custom name selectable.
                        # A newly added cost has no name yet, so leave the selectbox unselected.
                        cost_options: list[str] = COST_OPTIONS.get(phase, [])
                        cost_name_index: int | None
                        if phase_cost.name is None:
                            cost_name_index = None
                        else:
                            if phase_cost.name not in cost_options:
                                cost_options = [phase_cost.name] + cost_options
                            cost_name_index = cost_options.index(phase_cost.name)
                        phase_cost.name: str | None = st.selectbox(
                            "Cost",
                            options=cost_options,
                            index=cost_name_index,
                            accept_new_options=True,
                            key=f"directcost-name-{phase_cost.unique_key}",
                        )
                        # Create badge if new cost
                        if phase_cost.name is None:
                            st.badge(
                                "New cost, fill in details",
                                icon=":material/exclamation:",
                                color="orange",
                            )

                        phase_cost.cost: float = st.number_input(
                            f"Cost ({currency_code()})",
                            key=f"directcost-cost-{phase_cost.unique_key}",
                            min_value=0.0,
                            step=0.50,
                            value=float(phase_cost.cost),
                        )
                        # Show badge if hours is 0.
                        if phase_cost.cost == 0.0:
                            st.badge(
                                f"Cost is set to {format_currency(0)}",
                                icon=":material/exclamation:",
                                color="orange",
                            )

                        st.button(
                            "Delete direct cost",
                            key=f"delete-direct-cost-{phase_cost.unique_key}",
                            icon=":material/delete:",
                            on_click=delete_direct_cost,
                            args=[phase_cost],
                        )

                with st.container(horizontal=True, horizontal_alignment="left"):
                    st.button(
                        "Add Activity",
                        key=f"add-activity-{phase}",
                        icon=":material/sprint:",
                        on_click=add_activity,
                        args=[phase],
                    )
                    st.button(
                        "Add Direct Cost",
                        key=f"add-direct-cost-{phase}",
                        icon=":material/request_quote:",
                        on_click=add_direct_cost,
                        args=[phase],
                    )
                    st.button(
                        "Next Phase",
                        key=f"next-phase-{phase}",
                        icon=":material/check:",
                        type="primary",
                        on_click=next_tool_step,
                        args=[phase],
                    )

    # Special phase for saving to the database, shown only when a database is configured.
    if DATABASE_TYPE in ("sqlite", "mysql"):
        with st.expander(
            "Save and share your result?",
            expanded=TOOL_STEPS[st.session_state["tool_step"]] == "save",
            key="save-expander",
            on_change="rerun",
        ):
            st.markdown("""
                        If you would like to share your result with others, we will require your permission to save
                        the information you have input into this tool. If you are happy to do so, please click on the
                        button below. You can then share your result with the buttons below.
                        """)
            with st.container(horizontal=True, horizontal_alignment="left"):
                # The tool step advances in the on_click callback, as the expander's state cannot be changed once it
                # is rendered. Saving is not done in the callback, as callbacks run before the script copies unkeyed
                # widget values into session state.
                if st.button(
                    "Save your result to share",
                    icon=":material/save:",
                    type="primary",
                    help="Save your inputs to the database. Saving again updates the same project.",
                    on_click=next_tool_step,
                    args=["save"],
                ):
                    save_to_database()
                st.button(
                    "Do not save my result",
                    key="next-phase-save",
                    icon=":material/close:",
                    on_click=next_tool_step,
                    args=["save"],
                )


# Visualisation pane

# Calculate total costs and total hours.
combined_costs_list: list[Cost] = st.session_state["activity_list"] + st.session_state["cost_list"]
total_cost: float = compute_costs(combined_costs_list)
total_hours: float = compute_hours(st.session_state["activity_list"])


def build_color_map(names: Sequence[str], palette: Sequence[str] | None = None) -> dict[str, str]:
    """Assigns each distinct name a stable colour so a phase or activity keeps the
    same colour across every chart.

    Args:
        names: Category names, in the order they should claim colours.
        palette: Colours to draw from. Defaults to Streamlit's categorical palette
            when it has enough colours, otherwise px.colors.qualitative.Light24.
    """
    distinct: list[str] = list(dict.fromkeys(names))
    if palette is None:
        palette = (
            STREAMLIT_CATEGORICAL_COLORS
            if len(distinct) <= len(STREAMLIT_CATEGORICAL_COLORS)
            else px.colors.qualitative.Light24
        )
    return {name: palette[i % len(palette)] for i, name in enumerate(distinct)}


# Colour maps shared by the charts below. Derived fresh each run (rather than persisted)
# so newly added activities always get a colour; phases always take the same colours and
# activity/direct-cost names keep a consistent colour wherever they appear.
phase_color_map: dict[str, str] = build_color_map(list(RESEARCH_PHASES.values()))
item_color_map: dict[str, str] = build_color_map([item.get_name() or "Unnamed" for item in combined_costs_list])
person_color_map: dict[str, str] = build_color_map(
    [activity.get_person().name or "Unnamed" for activity in st.session_state["activity_list"]]
)

with main_right:
    k1, k2, k3 = st.columns(3)
    k1.metric("Estimated total cost", format_currency(total_cost))
    k2.metric("Estimated labor hours", f"{total_hours:.0f} h")
    k3.metric(
        "Estimated direct costs",
        format_currency(compute_costs(st.session_state["cost_list"])),
    )

    # Costs pie chart
    st.subheader("Total cost breakdown")

    costs_chart_selection = st.pills(
        "**Show cost breakdown for**",
        ["phases", "activities and direct costs"],
        default="phases",
    )
    costs_pie_names: Literal["Phase", "Item"] = "Phase" if costs_chart_selection == "phases" else "Item"

    costs_df = pd.DataFrame(
        {
            "Item": [item.get_name() or "Unnamed" for item in combined_costs_list],
            "Cost": [item.get_total_cost() for item in combined_costs_list],
            "Phase": [RESEARCH_PHASES[item.get_phase()] for item in combined_costs_list],
        }
    )

    costs_pie = px.pie(
        costs_df,
        values="Cost",
        names=costs_pie_names,
        color=costs_pie_names,
        color_discrete_map={**phase_color_map, **item_color_map},
        title="Total Cost Breakdown",
    )
    costs_pie.update_layout(height=720)
    st.plotly_chart(costs_pie, width="stretch")

    # Labour cost bar chart
    st.subheader("Labor activity breakdown")

    st.markdown("""
                Click on the phases and people in the charts below to see the breakdown of costs within each. Click on
                the phase or person again to return to the parent view.
                """)

    labour_df = pd.DataFrame(
        {
            "Activity": [activity.get_name() or "Unnamed" for activity in st.session_state["activity_list"]],
            "Cost": [activity.get_total_cost() for activity in st.session_state["activity_list"]],
            "Hours": [activity.get_hours() for activity in st.session_state["activity_list"]],
            "Phase": [RESEARCH_PHASES[activity.get_phase()] for activity in st.session_state["activity_list"]],
            "Person": [activity.get_person().name or "Unnamed" for activity in st.session_state["activity_list"]],
        }
    )

    sunburst = px.sunburst(
        labour_df,
        path=["Phase", "Person", "Activity"],
        values="Cost",
        color="Phase",
        labels={"Cost": f"Cost ({currency_code()})"},
        color_discrete_map=phase_color_map,
        title="Cost of Labor Breakdown by Phase, Role and Activity",
    )
    # Label each segment with its cost as a percentage of the overall total cost.
    # total_cost includes direct costs, which are not shown in this sunburst, so
    # the percentages of the top-level segments will not sum to 100%.
    node_costs: list[float] = list(sunburst.data[0].values)
    sunburst.data[0].text = [f"{(cost / total_cost * 100):.1f}%" if total_cost else "0.0%" for cost in node_costs]
    sunburst.data[0].texttemplate = "%{label}<br>%{text}"
    sunburst.update_layout(height=720)
    st.plotly_chart(sunburst, width="stretch")
    st.caption(
        "Percentages are calculated as a percentage of the total cost of the "
        "paper, including direct costs that are not shown in this chart."
    )

    # Hours of labour per person bar chart
    hours_per_person_df = (
        labour_df.groupby("Person", as_index=False)["Hours"].sum().sort_values("Hours", ascending=False)
    )

    hours_per_person_chart = px.bar(
        hours_per_person_df,
        x="Person",
        y="Hours",
        color="Person",
        color_discrete_map=person_color_map,
        title="Hours of Labor per Person",
        text_auto=True,
    )
    hours_per_person_chart.update_traces(texttemplate="%{y:.1f} hours", textposition="outside")
    hours_per_person_chart.update_layout(showlegend=False)
    st.plotly_chart(hours_per_person_chart, width="stretch")

    labour_chart_selection = st.pills(
        "**Show labor as**",
        ["Cost", "Hours"],
        default="Cost",
        format_func=lambda option: f"Cost ({currency_code()})" if option == "Cost" else option,
    )

    labour_chart = px.bar(
        labour_df,
        x="Activity",
        y=labour_chart_selection,
        color="Phase",
        color_discrete_map=phase_color_map,
        title="Cost of and Time Spent on Labor Activities",
        text_auto=True,
        labels={"Cost": f"Cost ({currency_code()})"},
    )
    if labour_chart_selection == "Cost":
        labour_chart.update_traces(texttemplate=f"{currency_prefix()}%{{y:,.2f}}", textposition="outside")
        labour_chart.update_yaxes(tickprefix=currency_prefix())
    else:
        labour_chart.update_traces(texttemplate="%{y:.1f} hours", textposition="outside")
    st.plotly_chart(labour_chart, width="stretch")


# -----------------------------------------------
# Social media sharing
# -----------------------------------------------
# Arial is the intended face; the generic fallback lets the PNG renderer substitute a metric-compatible font
# (Liberation Sans, installed in the Docker image) on hosts without Arial.
SOCIAL_MEDIA_FONT: str = "Arial, sans-serif"


def _wrap_text(text: str, max_chars: int) -> list[str]:
    """Greedily wraps text into lines of at most ``max_chars`` characters.

    drawsvg does no line wrapping of its own, so long project titles are split
    here before being handed to a multi-line ``draw.Text``.
    """
    words: list[str] = text.split()
    lines: list[str] = []
    current: str = ""
    for word in words:
        candidate: str = f"{current} {word}".strip()
        if not current or len(candidate) <= max_chars:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def create_social_media_svg(
    country: str,
    international_collaborators: bool,
    project_name: str,
    project_field: str,
    total_cost: float,
    total_hours: float,
    phase_costs: dict[str, float],
) -> draw.Drawing:
    """Builds a portrait social-media card summarising a cost estimate.

    The cost breakdown is drawn as a plain SVG stacked bar (no Plotly/Kaleido),
    so the card renders identically wherever the SVG is displayed.

    Args:
        country: Display name of the researcher's country.
        international_collaborators: Whether the project has collaborators from
            other countries; appends "+ others" after the country name.
        project_name: Title of the paper/project ("" if the user left it blank).
        project_field: Field of science the project sits in.
        total_cost: Estimated total cost in the chosen country's currency.
        total_hours: Estimated total hours of labour.
        phase_costs: Cost in the chosen country's currency per research phase, keyed by phase display name.
    """
    width: int = 1080
    height: int = 1360
    margin: int = 72
    ink: str = "#16263a"
    muted: str = "#3f5064"
    accent: str = "#d6336c"

    image: draw.Drawing = draw.Drawing(width, height, id_prefix="socmed")

    # Background
    gradient = draw.LinearGradient(200, 0, 800, height)
    gradient.add_stop(0, "lightskyblue")
    gradient.add_stop(1, "lightsteelblue")
    image.append(draw.Rectangle(0, 0, width, height, fill=gradient))

    # Eyebrow
    image.append(
        draw.Text(
            "THE COST OF KNOWLEDGE",
            30,
            margin,
            110,
            fill=muted,
            font_family=SOCIAL_MEDIA_FONT,
            font_weight="bold",
            letter_spacing=4,
        )
    )

    # Project title (wrapped, capped at three lines)
    title_size: int = 62
    title_line_height: float = 1.15
    wrapped_title: list[str] = _wrap_text(project_name.strip() or "Untitled research project", 26)
    title_lines: list[str] = wrapped_title[:3]
    if len(wrapped_title) > 3:
        title_lines[-1] = title_lines[-1].rstrip(".") + "…"
    title_top: float = 184
    image.append(
        draw.Text(
            title_lines,
            title_size,
            margin,
            title_top,
            fill=ink,
            font_family=SOCIAL_MEDIA_FONT,
            font_weight="bold",
            line_height=title_line_height,
        )
    )

    # Field of science and country
    subtitle_y: float = title_top + title_size * title_line_height * (len(title_lines) - 1) + 66
    subtitle: str = project_field
    if country.strip():
        country_text: str = country.strip()
        if international_collaborators:
            country_text = f"{country_text} + others"
        subtitle = f"{project_field}  ·  {country_text}"
    image.append(
        draw.Text(
            subtitle,
            34,
            margin,
            subtitle_y,
            fill=muted,
            font_family=SOCIAL_MEDIA_FONT,
        )
    )
    image.append(
        draw.Line(
            margin,
            subtitle_y + 34,
            width - margin,
            subtitle_y + 34,
            stroke="#ffffff",
            stroke_width=2,
            stroke_opacity=0.6,
        )
    )

    # Blurb, sitting between the divider and the headline cost figures.
    blurb_line_height: float = 1.3
    blurb_lines: list[str] = _wrap_text(
        "Using the Cost of Knowledge Calculator, I estimated the following cost for my research publication to be:",
        74,
    )
    blurb_top: float = subtitle_y + 34 + 60
    image.append(
        draw.Text(
            blurb_lines,
            26,
            margin,
            blurb_top,
            fill=muted,
            font_family=SOCIAL_MEDIA_FONT,
            line_height=blurb_line_height,
        )
    )
    blurb_bottom: float = blurb_top + 26 * blurb_line_height * (len(blurb_lines) - 1)

    # Cost breakdown by phase, drawn as a plain SVG stacked bar so no charting
    # library is needed. The block is anchored to the bottom of the card so the
    # layout stays balanced whatever the title length. Streamlit's placeholder
    # palette renders near-black outside the app, so choose real colours here,
    # one stable colour per phase.
    phase_names: list[str] = list(phase_costs.keys())
    palette: dict[str, str] = build_color_map(phase_names, palette=px.colors.qualitative.Bold)
    breakdown_total: float = sum(phase_costs.values())
    visible_phases: list[str] = [name for name in phase_names if phase_costs[name] > 0] or phase_names

    legend_row_h: int = 48
    legend_font: int = 28
    # Bottom of the legend sits above the two footer lines, with generous padding
    # around the larger, centred call-to-action line that follows it.
    legend_last_y: float = height - 150
    legend_first_y: float = legend_last_y - (len(visible_phases) - 1) * legend_row_h
    bar_x: int = margin
    bar_w: int = width - 2 * margin
    bar_h: int = 88
    bar_y: float = legend_first_y - 26 - 46 - bar_h
    bar_label_y: float = bar_y - 24

    # Headline figures, vertically centred between the blurb and the breakdown.
    # The two metrics are stacked with a deliberately tight gap and the block is
    # pushed down from the blurb so a three-line project title still leaves the
    # "Estimated total cost" line clear of the text above it.
    metric_gap: int = 140
    figures_block_h: int = 96 + metric_gap
    zone_top: float = blurb_bottom + 90
    zone_bottom: float = bar_label_y - 40
    figures_y: float = zone_top + max(0.0, (zone_bottom - zone_top - figures_block_h) / 2)
    image.append(
        draw.Text(
            "Estimated total cost",
            30,
            margin,
            figures_y,
            fill=muted,
            font_family=SOCIAL_MEDIA_FONT,
        )
    )
    image.append(
        draw.Text(
            format_currency(total_cost),
            88,
            margin,
            figures_y + 84,
            fill=ink,
            font_family=SOCIAL_MEDIA_FONT,
            font_weight="bold",
        )
    )
    image.append(
        draw.Text(
            "Estimated hours of labor",
            30,
            margin,
            figures_y + metric_gap,
            fill=muted,
            font_family=SOCIAL_MEDIA_FONT,
        )
    )
    image.append(
        draw.Text(
            f"{total_hours:,.0f} hours",
            88,
            margin,
            figures_y + metric_gap + 84,
            fill=ink,
            font_family=SOCIAL_MEDIA_FONT,
            font_weight="bold",
        )
    )

    image.append(
        draw.Text(
            "Where the cost goes",
            30,
            margin,
            bar_label_y,
            fill=muted,
            font_family=SOCIAL_MEDIA_FONT,
        )
    )
    if breakdown_total > 0:
        cursor: float = bar_x
        for name in phase_names:
            segment: float = bar_w * (phase_costs[name] / breakdown_total)
            if segment <= 0:
                continue
            image.append(draw.Rectangle(cursor, bar_y, segment, bar_h, fill=palette[name]))
            cursor += segment
    else:
        image.append(draw.Rectangle(bar_x, bar_y, bar_w, bar_h, fill="#ffffff", fill_opacity=0.4))
    image.append(
        draw.Rectangle(
            bar_x,
            bar_y,
            bar_w,
            bar_h,
            rx=10,
            fill="none",
            stroke="#ffffff",
            stroke_width=3,
        )
    )

    # Legend: one row per phase that has a cost.
    row_index: int = 0
    for name in phase_names:
        amount: float = phase_costs[name]
        if amount <= 0:
            continue
        row_y: float = legend_first_y + row_index * legend_row_h
        share: float = amount / breakdown_total * 100 if breakdown_total else 0.0
        image.append(draw.Rectangle(margin, row_y - 24, 32, 32, rx=7, fill=palette[name]))
        image.append(
            draw.Text(
                name,
                legend_font,
                margin + 48,
                row_y,
                fill=ink,
                font_family=SOCIAL_MEDIA_FONT,
            )
        )
        image.append(
            draw.Text(
                f"{format_currency(amount)}  ({share:.0f}%)",
                legend_font,
                width - margin,
                row_y,
                fill=muted,
                text_anchor="end",
                font_family=SOCIAL_MEDIA_FONT,
            )
        )
        row_index += 1

    image.append(
        draw.Text(
            "Estimate your own Cost of Knowledge at https://costofknowledge.org.",
            28,
            width / 2,
            height - 86,
            text_anchor="middle",
            fill=accent,
            font_weight="bold",
            font_family=SOCIAL_MEDIA_FONT,
        )
    )
    image.append(
        draw.Text(
            "The University of Sydney Cost of Knowledge Team (Alam et al.) and SPARC.",
            24,
            width - margin,
            height - 40,
            text_anchor="end",
            fill=muted,
            font_family=SOCIAL_MEDIA_FONT,
        )
    )
    return image


@st.cache_data(show_spinner=False)
def social_media_svg_to_png(svg: str) -> bytes:
    """Rasterises the social-media card for platforms that do not accept SVG uploads (e.g. LinkedIn, X, Facebook).

    Cached on the SVG markup, so the card is only re-rendered when its content changes.
    """
    return resvg_py.svg_to_bytes(svg_string=svg, sans_serif_family="Liberation Sans")


def share_summary(total_cost: float, total_hours: float) -> str:
    """One-sentence summary of the estimate used as the pre-filled text of social media posts."""
    return (
        f"Using the Cost of Knowledge Calculator, I estimated that my research publication cost "
        f"{format_currency(total_cost)} and {total_hours:,.0f} hours of labor."
    )


def share_link(saved_url: str | None) -> tuple[str, str]:
    """Returns the link shared on social media and by email, and the call to action introducing it.

    Args:
        saved_url: Link to the user's saved result, or None if it has not been saved, in which case the tool's own
            link is shared.
    """
    if saved_url is None:
        return COST_OF_KNOWLEDGE_URL, "Estimate your own Cost of Knowledge"
    return saved_url, "See my result and estimate your own Cost of Knowledge"


# None of the platforms' share links can attach an image, so the user attaches the downloaded PNG themselves.
def linkedin_share_url(total_cost: float, total_hours: float, saved_url: str | None) -> str:
    """Builds a link that opens LinkedIn's post composer pre-filled with a summary of the estimate."""
    url, call_to_action = share_link(saved_url)
    text: str = f"{share_summary(total_cost, total_hours)}\n\n{call_to_action} at {url}"
    return f"https://www.linkedin.com/feed/?shareActive=true&text={quote(text)}"


def x_share_url(total_cost: float, total_hours: float, saved_url: str | None) -> str:
    """Builds a link that opens X's post composer pre-filled with a summary of the estimate and a link to share."""
    url, call_to_action = share_link(saved_url)
    text: str = f"{share_summary(total_cost, total_hours)} {call_to_action}:"
    return f"https://x.com/intent/post?text={quote(text)}&url={quote(url, safe='')}"


def facebook_share_url(saved_url: str | None) -> str:
    """Builds a link that opens Facebook's share dialog for the saved result, or for the tool if it is not saved.

    Facebook's share dialog only accepts a URL; it does not allow pre-filled post text.
    """
    url, _ = share_link(saved_url)
    return f"https://www.facebook.com/sharer/sharer.php?u={quote(url, safe='')}"


def email_share_url(total_cost: float, total_hours: float, saved_url: str | None) -> str:
    """Builds a mailto link that opens the user's email client with a pre-filled summary of the estimate."""
    url, call_to_action = share_link(saved_url)
    subject: str = "The Cost of Knowledge of my research publication"
    # RFC 6068 recommends CRLF line breaks in mailto bodies.
    body: str = f"{share_summary(total_cost, total_hours)}\r\n\r\n{call_to_action} at {url}"
    return f"mailto:?subject={quote(subject)}&body={quote(body)}"


# Streamlit has no native copy-to-clipboard button, so this inline component draws a button styled like st.link_button
# that copies data["url"] to the clipboard. The browser only allows this on secure (https or localhost) pages.
_COPY_LINK_BUTTON = st.components.v2.component(
    "copy_link_button",
    html="""
<button type="button" class="copy-link-button">
  <svg class="icon" viewBox="0 -960 960 960" aria-hidden="true">
    <path d="M360-240q-33 0-56.5-23.5T280-320v-480q0-33 23.5-56.5T360-880h360q33 0 56.5 23.5T800-800v480q0 33-23.5
      56.5T720-240H360Zm0-80h360v-480H360v480ZM200-80q-33 0-56.5-23.5T120-160v-560h80v560h440v80H200Zm160-240v-480
      480Z"/>
  </svg>
  <span class="label"></span>
</button>
""",
    css="""
.copy-link-button {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 2.5rem;
  padding: 0.25rem 0.75rem;
  border: 1px solid var(--st-border-color);
  border-radius: var(--st-button-radius);
  background-color: var(--st-background-color);
  color: var(--st-text-color);
  font-family: var(--st-font);
  font-size: var(--st-base-font-size);
  line-height: 1.6;
  white-space: nowrap;
  cursor: pointer;
}
.copy-link-button:hover {
  border-color: var(--st-primary-color);
  color: var(--st-primary-color);
}
.icon {
  width: 1.25rem;
  height: 1.25rem;
  fill: currentColor;
}
""",
    js="""
export default function (component) {
  const { data, parentElement } = component
  const button = parentElement.querySelector(".copy-link-button")
  const label = parentElement.querySelector(".label")
  if (!button || !label) return

  label.textContent = data.label
  button.title = data.help
  button.onclick = async () => {
    try {
      await navigator.clipboard.writeText(data.url)
      label.textContent = data.copied_label
    } catch {
      // Clipboard access is blocked, e.g. on an insecure page, so let the user copy the link themselves.
      window.prompt("Copy the link below.", data.url)
    }
    setTimeout(() => {
      label.textContent = data.label
    }, 2000)
  }
}
""",
)


def saved_project_url(public_id: str) -> str:
    """Builds the full link that loads the saved project with the given public id."""
    return f"{st.context.url or ''}?{PROJECT_ID_QUERY_PARAM}={public_id}"


def copy_link_button(label: str, url: str, copied_label: str, help: str, key: str) -> None:
    """Draws a button that copies the given URL to the clipboard, showing copied_label for a moment afterwards."""
    _COPY_LINK_BUTTON(
        data={"label": label, "url": url, "copied_label": copied_label, "help": help},
        key=key,
        width="content",
    )


# -----------------------------------------------
# Conclusion
# -----------------------------------------------

st.header(":material/share: Share your result")

st.markdown("""
            Share your result using the buttons below.
            """)

# Rendered fresh each run from the (persisted) project inputs and computed totals,
# so it never needs its own st.session_state entry.
social_media_svg: str = create_social_media_svg(
    country=COUNTRY_NAMES.get(st.session_state["user_country"], ""),
    international_collaborators=st.session_state["international_collaborators"],
    project_name=st.session_state["project_name"] or "",
    project_field=st.session_state["project_field"],
    total_cost=total_cost,
    total_hours=total_hours,
    phase_costs={label: compute_costs(combined_costs_list, phase=key) for key, label in RESEARCH_PHASES.items()},
).as_svg()

_svg_slug: str = (
    "".join(
        char if char.isalnum() else "-" for char in (st.session_state["project_name"] or "cost-of-knowledge").lower()
    ).strip("-")
    or "cost-of-knowledge"
)

with st.container(horizontal=True, horizontal_alignment="center"):
    st.image(social_media_svg, width=540)

# Link to the saved result, which the share buttons use in place of the tool's link once the result is saved. Saving
# happens above in the setup pane, so the buttons update in the same run as the save.
saved_result_url: str | None = (
    saved_project_url(st.session_state["database_public_id"])
    if st.session_state.get("database_public_id") is not None
    else None
)

with st.container(horizontal=True, horizontal_alignment="left"):
    st.download_button(
        "Download image",
        data=social_media_svg_to_png(social_media_svg),
        file_name=f"{_svg_slug}-cost-estimate.png",
        mime="image/png",
        icon=":material/image:",
        type="primary",
    )
    st.link_button(
        "Share on LinkedIn",
        linkedin_share_url(total_cost, total_hours, saved_result_url),
        icon=":material/share:",
        help="Share this tool on LinkedIn. Download the image first and attach it to your post.",
    )
    st.link_button(
        "Share on X",
        x_share_url(total_cost, total_hours, saved_result_url),
        icon=":material/share:",
        help="Share this tool on X. Download the image first and attach it to your post.",
    )
    st.link_button(
        "Share on Facebook",
        facebook_share_url(saved_result_url),
        icon=":material/share:",
        help="Share this tool on Facebook. Download the image first and attach it to your post.",
    )
    st.link_button(
        "Share via email",
        email_share_url(total_cost, total_hours, saved_result_url),
        icon=":material/email:",
        help="Share this tool via email. Download the image first and attach it to your email.",
    )
    # Shown once the result is saved, which happens above in the setup pane, so it appears in the same run as the save.
    if saved_result_url is not None:
        copy_link_button(
            "Copy link to saved result",
            saved_result_url,
            copied_label="Link copied",
            help="Copy a link to your saved result to share it, or to return to it later.",
            key="copy-saved-project-link",
        )


st.markdown("""
            :small[:material/copyright: Copyright 2026 Nurul Alam, Jane Andrew, Max Baker, Janine Coupe, Tai-Joo Koh,
            Ben Lay, Chang-yuan Loh, and Farzana Tanima.
            :material/license: The content on this website is subject to the [Creative Commons Attribution 4.0
            International License](https://creativecommons.org/licenses/by/4.0/).]
            """)
