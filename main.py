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
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote

import drawsvg as draw
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import resvg_py
import streamlit as st

from src import database, sql_store
from src.calculator_state import (
    DEFAULT_INDIRECT_COST_PERCENTAGE,
    OVERALL_TOTAL_PHASES,
    CalculatorState,
    compute_costs,
    compute_hours,
)
from src.currency_rates import convert_currency
from src.database import DatabaseType, get_database_type, init_database
from src.models import (
    Activity,
    DirectCost,
    Person,
    PersonType,
)
from src.reference_data import (
    COUNTRY_CODES,
    COUNTRY_CURRENCIES,
    COUNTRY_NAMES,
    FIELDS_OF_RESEARCH,
    RESEARCH_PHASES,
    ROLES,
    field_of_research_display_name,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.models import Cost


st.set_page_config(page_title="Cost of Knowledge Calculator", layout="wide")


def calculator_page() -> None:
    """The calculator, which is the rest of this script. The script carries on past navigation to run it."""


# The saved results page is reached only by its URL (e.g. BASE-URL/results), so navigation is hidden and the calculator
# does not link to it.
RESULTS_PAGE: st.Page = st.Page("app_pages/results.py", title="Saved results", url_path="results")
current_page: st.Page = st.navigation(
    [st.Page(calculator_page, title="Cost of Knowledge Calculator", default=True), RESULTS_PAGE], position="hidden"
)
if current_page.url_path == RESULTS_PAGE.url_path:
    RESULTS_PAGE.run()
    st.stop()


COST_OF_KNOWLEDGE_URL: str = "https://costofknowledge.org"


# Anchors of the page's main sections, and the table of contents in the sidebar that links to them.
ARTICLE_ANCHOR: str = "your-article"
PEOPLE_ANCHOR: str = "people-involved"
CALCULATOR_ANCHOR: str = "calculator"
RESULTS_HEADER_ANCHOR: str = "cost-of-your-article"
SHARE_ANCHOR: str = "share-your-result"
TABLE_OF_CONTENTS: list[tuple[str, str]] = [
    (":material/article: Your article", ARTICLE_ANCHOR),
    (":material/groups: People involved", PEOPLE_ANCHOR),
    (":material/request_quote: Calculator", CALCULATOR_ANCHOR),
    (":material/bar_chart: Your results", RESULTS_HEADER_ANCHOR),
    (":material/share: Share your result", SHARE_ANCHOR),
]


# Placeholder hex values that Streamlit's frontend swaps for its theme's categorical
# colour palette (see streamlit/elements/lib/streamlit_plotly_theme.py). Assigning one
# of these to a category keeps that phase or activity on the same Streamlit colour in
# every chart. Charts with more than 10 categories fall back to px.colors.qualitative.Light24.
STREAMLIT_CATEGORICAL_COLORS: list[str] = [f"#{n:06d}" for n in range(1, 11)]


# Preset activities and direct costs offered in the calculator's selectboxes, loaded from data/costs.json.
_COSTS_DATA: dict[str, Any] = json.loads((Path(__file__).parent / "data" / "costs.json").read_text(encoding="utf-8"))
# Names of the preset activities and direct costs of each phase, in the order they appear in costs.json.
ACTIVITY_OPTIONS: dict[str, list[str]] = {
    phase: [activity["name"] for activity in _COSTS_DATA["activities"] if activity["phase"] == phase]
    for phase in RESEARCH_PHASES
}
COST_OPTIONS: dict[str, list[str]] = {
    phase: [cost["name"] for cost in _COSTS_DATA["direct_costs"] if cost["phase"] == phase] for phase in RESEARCH_PHASES
}
# Default hours of each preset activity and default cost in USD of each preset direct cost, keyed by (phase, name), as
# some names (e.g. "Other") appear in more than one phase.
ACTIVITY_DEFAULT_HOURS: dict[tuple[str, str], float] = {
    (activity["phase"], activity["name"]): float(activity["default_hours"]) for activity in _COSTS_DATA["activities"]
}
COST_DEFAULTS_USD: dict[tuple[str, str], float] = {
    (cost["phase"], cost["name"]): float(cost["default_cost"]) for cost in _COSTS_DATA["direct_costs"]
}


# -----------------------------------------------
# Currency
# -----------------------------------------------


def currency_code() -> str:
    """ISO 4217 code (e.g. "USD") of the currency of the country chosen by the user."""
    return COUNTRY_CURRENCIES.get(st.session_state["user_country"], COUNTRY_CURRENCIES["us"])[0]


def currency_prefix() -> str:
    """Prefix put before amounts in the chosen country's currency.

    The currency symbol (e.g. "$"), or the ISO code and a space (e.g. "AED ") for currencies without one.
    """
    code, symbol = COUNTRY_CURRENCIES.get(st.session_state["user_country"], COUNTRY_CURRENCIES["us"])
    return symbol if symbol != code else f"{code} "


def format_currency(x: int | float) -> str:
    """Formats an int or float to a string in the currency of the country chosen by the user."""
    return f"{currency_prefix()}{x:,.0f} ({currency_code()})"


# -----------------------------------------------
# Model variables and database
# -----------------------------------------------


def saved_inputs(state: CalculatorState) -> dict[str, Any]:
    """Returns the inputs of a state that saving compares to decide whether it has changed since it was last saved.

    Leaves out the summary, which is derived.
    """
    data: dict[str, Any] = state.to_dict()
    del data["summary"]
    return data


def load_from_database(public_id: str) -> None:
    """Replaces the calculator's inputs with the project saved in the database under the given public id.

    Must run before any widget is rendered, as it replaces widget state. Saving changes later in the session creates a
    new project, amended from the loaded one.
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
    st.session_state["database_saved_inputs"] = saved_inputs(state)
    st.toast("Loaded the project from the database.", icon=":material/check_circle:")


# -----------------------------------------------
# User and Project
# -----------------------------------------------


def convert_monetary_values():
    """Converts every monetary value to the currency of the newly selected country, then updates user_country."""
    from_code: str = currency_code()
    # The selectbox is None when cleared, which falls back to USD like the blank starting state.
    selected_country: str = st.session_state["user_country_select"] or ""
    to_code: str = COUNTRY_CURRENCIES.get(selected_country, COUNTRY_CURRENCIES["us"])[0]
    st.session_state["user_country"] = selected_country
    if from_code == to_code:
        return

    def convert(amount: int | float) -> float:
        converted: float | None = convert_currency(amount, from_code, to_code)
        return 0.0 if converted is None else round(converted, 2)

    # Check a rate exists for both currencies before changing anything, so values are never left half-converted.
    if convert_currency(1, from_code, to_code) is None:
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
    # Keyed number_inputs keep their widget ID when value= changes, so the browser would keep showing (and send
    # back) the old amount. Writing the converted amount into the widget's state makes Streamlit push it to the
    # browser.
    for direct_cost in st.session_state["cost_list"]:
        direct_cost.cost = convert(direct_cost.cost)
        st.session_state[f"directcost-cost-{direct_cost.unique_key}"] = direct_cost.cost

    st.toast(f"Costs converted from {from_code} to {to_code}.", icon=":material/currency_exchange:")


# -----------------------------------------------
# Study team
# -----------------------------------------------


# Option of the researcher form's role selectbox for entering a salary instead of choosing a preset role.
MANUAL_SALARY_OPTION: str = "manual_salary"
# Keys of the widgets of the form to add a researcher. The dialog to edit a researcher uses its own keys.
ADD_PERSON_FORM_KEY: str = "add-person"


def next_person_key() -> str:
    """Returns an unused unique_key for a new research team member."""
    person_key_list: list[int] = [
        int(person.unique_key) for person in st.session_state["people"].values() if person.unique_key.isdigit()
    ]
    return str(max(person_key_list, default=0) + 1)


def add_overall_total_activities(person: Person) -> None:
    """Adds an "(Overall Total)" activity of 0 hours to each of the first three phases, assigned to the given person."""
    for phase in OVERALL_TOTAL_PHASES:
        activity_key: int = next_activity_key()
        group_key: int = next_activity_group_key()
        activity: Activity = Activity(
            f"{RESEARCH_PHASES[phase]} (Overall Total)", person, phase, 0, activity_key, group_key
        )
        st.session_state["activity_list"].append(activity)
        # Keys are reused, so write the activity's values into its widgets' state, as when a state is loaded.
        st.session_state[f"activity-name-{group_key}"] = activity.name
        st.session_state[f"activity-person-{activity_key}"] = person.unique_key
        st.session_state[f"activity-hours-{activity_key}"] = 0.0


def delete_person(key: str):
    """Deletes a research team member. Their activities are reassigned to the first remaining team member, or deleted
    if there are none left.
    """
    people: dict[str, Person] = st.session_state["people"]
    del people[key]
    replacement: Person | None = next(iter(people.values()), None)
    for activity in list(st.session_state["activity_list"]):
        if not isinstance(activity, Activity) or activity.person.unique_key != key:
            continue
        if replacement is None:
            st.session_state["activity_list"].remove(activity)
        else:
            activity.person = replacement
            st.session_state[f"activity-person-{activity.unique_key}"] = replacement.unique_key


def role_hourly_rate(role: str) -> float:
    """Returns the preset hourly rate of a role in the user's currency.

    The preset rate excludes indirect costs, so the project-wide indirect cost rate is applied to it. The result is
    converted from USD to the user's currency, or left in USD if no exchange rate is available.
    """
    indirect_cost_multiplier: float = 1 + (st.session_state["indirect_cost_percentage"] / 100)
    rate_usd: float = ROLES[role].hourly_rate_usd * indirect_cost_multiplier
    converted_rate: float | None = convert_currency(rate_usd, "USD", currency_code())
    return rate_usd if converted_rate is None else round(converted_rate, 2)


def apply_indirect_cost_rate() -> None:
    """Callback for the indirect cost rate slider. Refreshes the hourly rate of everyone who has a role selected.

    Rates that were calculated from a salary (no role) are left alone.
    """
    for person in st.session_state["people"].values():
        if person.role is not None:
            person.hourly_rate = role_hourly_rate(person.role)


def format_hourly_rate(hourly_rate: int | float) -> str:
    """Formats an hourly rate in the user's currency, e.g. "$85.00 / hour"."""
    return f"{currency_prefix()}{hourly_rate:,.2f} / hour"


def calculate_hourly_rate(key: str, person: Person | None = None) -> None:
    """Shows the inputs to calculate an hourly rate from a salary, inside a researcher form.

    The hourly rate itself is calculated by salary_hourly_rate once the form is submitted.

    Args:
        key: Prefix of the keys of the inputs.
        person: The researcher being edited, if any, whose current rate is kept if no salary is entered.
    """
    st.number_input(f"What is the researcher's salary in {currency_code()}?", step=1, min_value=0, key=f"{key}-salary")
    st.number_input(
        "What is the period for which that salary is paid in months?",
        step=1,
        value=12,
        min_value=1,
        key=f"{key}-months",
    )
    st.number_input(
        "How many hours are they required to work per week?",
        step=1,
        value=40,
        min_value=1,
        key=f"{key}-weekly-hours",
    )
    st.caption(
        f"The project-wide indirect cost rate of {st.session_state['indirect_cost_percentage']}% will be applied. "
        "You can change it in the Indirect Costs section."
    )
    if person is not None and person.role is None:
        st.caption(
            f"Their current hourly rate is {format_hourly_rate(person.hourly_rate)}. Leave the salary at 0 to keep it."
        )


def salary_hourly_rate(key: str) -> float:
    """Calculates the hourly rate from the inputs shown by calculate_hourly_rate, including indirect costs."""
    indirect_cost_multiplier: float = 1 + (st.session_state["indirect_cost_percentage"] / 100)
    return round(
        Person.salary_to_hourly_rate(
            st.session_state[f"{key}-salary"],
            st.session_state[f"{key}-weekly-hours"],
            st.session_state[f"{key}-months"],
            indirect_cost_multiplier,
        ),
        2,
    )


def save_researcher(key: str, person_key: str | None = None) -> None:
    """Callback for a researcher form's submit button. Adds a research team member, or updates an existing one.

    Args:
        key: Prefix of the keys of the form's widgets.
        person_key: unique_key of the researcher to update. If None, a new researcher is added.
    """
    people: dict[str, Person] = st.session_state["people"]
    person: Person | None = people.get(person_key) if person_key is not None else None
    choice: str | None = st.session_state[f"{key}-role"]
    quantity: int = int(st.session_state[f"{key}-quantity"])

    role: str | None = None
    if choice is None:
        st.toast("Choose a role or enter a salary first.", icon=":material/error:")
        return
    if choice == MANUAL_SALARY_OPTION:
        if st.session_state[f"{key}-salary"] > 0:
            hourly_rate: int | float = salary_hourly_rate(key)
        elif person is not None and person.role is None:
            hourly_rate = person.hourly_rate
        else:
            st.toast("Enter the researcher's salary first.", icon=":material/error:")
            return
    else:
        role = choice
        hourly_rate = role_hourly_rate(choice)

    if person is None:
        first_researcher: bool = not people
        person = Person(next_person_key(), PersonType.RESEARCH_TEAM, hourly_rate, role, quantity)
        people[person.unique_key] = person
        # Activities need a researcher to be assigned to, so the starting activities appear with the first one.
        if first_researcher and not any(isinstance(item, Activity) for item in st.session_state["activity_list"]):
            add_overall_total_activities(person)
        # The form clears itself, but not the role selectbox above it.
        st.session_state[f"{key}-role"] = None
        st.toast(f"Added {person.label}.", icon=":material/check_circle:")
    else:
        person.role = role
        person.hourly_rate = hourly_rate
        person.quantity = quantity
    st.session_state[f"{key}-saved"] = True


def researcher_form(key: str, person: Person | None = None) -> None:
    """Shows the form to add a researcher, or to edit the given one.

    The role selectbox sits above the form so that choosing to enter a salary shows its inputs straight away, as inputs
    inside a form only update when it is submitted.

    Args:
        key: Prefix of the keys of the form's widgets.
        person: The researcher to edit. If None, the form adds a new researcher.
    """
    role_key: str = f"{key}-role"
    quantity_key: str = f"{key}-quantity"
    # Seed the widgets' state rather than passing index= or value=, as reused keys keep the value the browser holds.
    if role_key not in st.session_state:
        if person is None:
            st.session_state[role_key] = None
        else:
            st.session_state[role_key] = person.role if person.role in ROLES else MANUAL_SALARY_OPTION
    if person is not None and quantity_key not in st.session_state:
        st.session_state[quantity_key] = person.quantity

    def role_display(option: str, country: str) -> str:
        """Roles are shown by their US name, followed by their local name in the chosen country if it differs."""
        return "Enter a salary manually" if option == MANUAL_SALARY_OPTION else ROLES[option].display_name(country)

    choice: str | None = st.selectbox(
        "Role",
        options=[*ROLES, MANUAL_SALARY_OPTION],
        # Bind the country now, as AppTest calls format_func outside a script run, without st.session_state.
        format_func=lambda option, country=st.session_state["user_country"]: role_display(option, country),
        placeholder="Choose a role to fill in its median hourly rate based on US data, or enter a salary",
        key=role_key,
    )
    with st.form(f"{key}-form", clear_on_submit=person is None, border=False):
        if choice == MANUAL_SALARY_OPTION:
            calculate_hourly_rate(key, person)
        elif choice is not None:
            st.caption(
                f"Hourly rate including the {st.session_state['indirect_cost_percentage']}% indirect cost rate: "
                f"{format_hourly_rate(role_hourly_rate(choice))}"
            )
        st.number_input(
            "Number of researchers with this hourly rate",
            min_value=1,
            step=1,
            key=quantity_key,
        )
        submitted: bool = st.form_submit_button(
            "Add researcher" if person is None else "Save changes",
            icon=":material/person_add:" if person is None else ":material/save:",
            on_click=save_researcher,
            args=[key, None if person is None else person.unique_key],
        )
    # Closes the edit dialog by rerunning the whole script, unless the changes were not valid.
    if submitted and st.session_state.pop(f"{key}-saved", False) and person is not None:
        st.rerun()


@st.dialog("Edit researcher")
def edit_researcher(person: Person) -> None:
    researcher_form(f"edit-person-{person.unique_key}", person)


# -----------------------------------------------
# Calculator
# -----------------------------------------------


def person_option_display(key: str) -> str:
    """Converts a st.session_state["people"] key to a st.selectbox display name."""
    return st.session_state["people"][key].label


def set_activity_person(activity: Activity, counter: int):
    """Callback for st.selectbox to select the person assigned to an activity."""
    people_key: str = st.session_state[f"activity-person-{counter}"]
    activity.person: Person = st.session_state["people"][people_key]


def apply_activity_default(group_activities: list[Activity], group_key: int) -> None:
    """Callback for an activity's name selectbox. Renames the activity and, for a preset activity, fills in its
    default hours from data/costs.json for the first person assigned to it. Custom names leave the hours unchanged.

    Args:
        group_activities: Every Activity sharing the activity's group_key, the first being its first person.
        group_key: group_key of the activity.
    """
    activity_name: str | None = st.session_state[f"activity-name-{group_key}"]
    for group_activity in group_activities:
        group_activity.name = activity_name
    first_activity: Activity = group_activities[0]
    default_hours: float | None = ACTIVITY_DEFAULT_HOURS.get((first_activity.phase, activity_name or ""))
    if default_hours is None:
        return
    first_activity.hours = default_hours
    # The hours number_input ignores value= once it has its own widget state, so write the hours there too.
    st.session_state[f"activity-hours-{first_activity.unique_key}"] = default_hours


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
            next(iter(st.session_state["people"].values())),
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
            next(iter(st.session_state["people"].values())),
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
    st.session_state["cost_list"].append(DirectCost(None, phase, 0.0, max(cost_key_list, default=0) + 1))


def apply_direct_cost_default(direct_cost: DirectCost) -> None:
    """Callback for a direct cost's name selectbox. Renames the cost and, for a preset cost, fills in its default
    cost from data/costs.json. Custom names leave the cost unchanged.

    The default cost is converted from USD to the user's currency, or left in USD if no exchange rate is available.
    """
    direct_cost.name = st.session_state[f"directcost-name-{direct_cost.unique_key}"]
    cost_usd: float | None = COST_DEFAULTS_USD.get((direct_cost.phase, direct_cost.name or ""))
    if cost_usd is None:
        return
    converted_cost: float | None = convert_currency(cost_usd, "USD", currency_code())
    direct_cost.cost = cost_usd if converted_cost is None else round(converted_cost, 2)
    # The cost number_input ignores value= once it has its own widget state, so write the cost there too.
    st.session_state[f"directcost-cost-{direct_cost.unique_key}"] = direct_cost.cost


def delete_direct_cost(direct_cost: DirectCost):
    st.session_state["cost_list"].remove(direct_cost)


def save_to_database() -> None:
    """Saves the calculator's current inputs to the configured database as a new project.

    Saved projects are never overwritten, as their links may have been shared. Saving again after changing the
    inputs creates a new project whose parent is the previously saved or loaded project, and saving again without
    changes keeps the existing project. The public id of the latest project and its inputs are kept in
    st.session_state["database_public_id"] and st.session_state["database_saved_inputs"], so they persist across
    script reruns.
    """
    state: CalculatorState = CalculatorState.from_session_state(st.session_state)
    inputs: dict[str, Any] = saved_inputs(state)
    parent_public_id: str | None = st.session_state.get("database_public_id")
    if parent_public_id is not None and inputs == st.session_state.get("database_saved_inputs"):
        st.toast("No changes since your result was last saved.", icon=":material/check_circle:")
        return
    try:
        with closing(database.connect()) as conn:
            public_id: str = sql_store.save_project(conn, state, parent_public_id)
    except database.DATABASE_ERRORS as error:
        st.toast(f"Could not save to the database: {error}", icon=":material/error:")
        return
    st.session_state["database_public_id"] = public_id
    st.session_state["database_saved_inputs"] = inputs
    st.toast("Saved to the database.", icon=":material/check_circle:")


def load_alam_defaults() -> None:
    """Callback for the "Load defaults from Alam et al. 2026" button. Replaces the activities and direct costs with
    the estimates from Alam et al. (2026), keeping the project and people.

    The direct costs are converted from USD to the user's currency, or left in USD if no exchange rate is available.
    """
    usd_to_currency: float | None = convert_currency(1, "USD", currency_code())
    state: CalculatorState = CalculatorState.from_session_state(st.session_state)
    state.with_default_costs(1.0 if usd_to_currency is None else usd_to_currency).apply_to_session_state(
        st.session_state
    )
    st.toast("Loaded the estimates from Alam et al. (2026).", icon=":material/check_circle:")


# -----------------------------------------------
# Visualisation pane
# -----------------------------------------------


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


# Words left lowercase when title-casing field names, including te reo Māori particles (e.g. "o te Māori").
_TITLE_CASE_MINOR_WORDS: set[str] = {"and", "of", "me", "o", "te"}


def _title_case(text: str) -> str:
    """Capitalises each word of a field name except minor words, e.g. "Agricultural Biotechnology"."""
    words: list[str] = text.split()
    return " ".join(
        word if index > 0 and word in _TITLE_CASE_MINOR_WORDS else word[:1].upper() + word[1:]
        for index, word in enumerate(words)
    )


def create_social_media_svg(
    country: str,
    international_collaborators: bool,
    project_field: str,
    total_cost: float,
    total_hours: float,
    phase_costs: dict[str, float],
    show_hours: bool = False,
) -> draw.Drawing:
    """Builds a portrait social-media card summarising a cost estimate.

    The cost breakdown is drawn as a plain SVG stacked bar (no Plotly/Kaleido),
    so the card renders identically wherever the SVG is displayed.

    Args:
        country: Display name of the researcher's country.
        international_collaborators: Whether the project has collaborators from
            other countries; appends "+ others" after the country name.
        project_field: Name of the Field of Research group the project sits in, shown in the title.
        total_cost: Estimated total cost in the chosen country's currency.
        total_hours: Estimated total hours of labour.
        phase_costs: Cost in the chosen country's currency per research phase, keyed by phase display name.
        show_hours: Whether to show the estimated hours of labor below the total cost.
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

    # Blurb, introducing the title and figures below.
    image.append(
        draw.Text(
            "Using the Cost of Knowledge calculator, I calculated that",
            28,
            margin,
            162,
            fill=muted,
            font_family=SOCIAL_MEDIA_FONT,
        )
    )

    # Title (wrapped, capped at three lines). Some Field of Research names are long, so the font shrinks until the
    # title fits, with the characters per line scaled to match.
    title: str = " ".join(f"My {_title_case(project_field)} paper cost".split())
    title_line_height: float = 1.15
    for title_size in (62, 54, 46, 40):
        wrapped_title: list[str] = _wrap_text(title, int(26 * 62 / title_size))
        if len(wrapped_title) <= 3:
            break
    title_lines: list[str] = wrapped_title[:3]
    if len(wrapped_title) > 3:
        title_lines[-1] = title_lines[-1].rstrip(".") + "…"
    title_top: float = 238
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

    title_bottom: float = title_top + title_size * title_line_height * (len(title_lines) - 1)

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
    # Bottom of the legend sits above the three footer lines, with generous padding
    # around the larger, centred call-to-action line that follows it.
    legend_last_y: float = height - 194
    legend_first_y: float = legend_last_y - (len(visible_phases) - 1) * legend_row_h
    bar_x: int = margin
    bar_w: int = width - 2 * margin
    bar_h: int = 88
    bar_y: float = legend_first_y - 26 - 46 - bar_h
    bar_label_y: float = bar_y - 24

    # Country and divider, sitting just above the breakdown. The country wraps upwards from the divider.
    divider_y: float = bar_label_y - 58
    subtitle: str = country.strip()
    if subtitle and international_collaborators:
        subtitle = f"{subtitle} + international collaborators"
    subtitle_line_height: float = 1.2
    subtitle_lines: list[str] = _wrap_text(subtitle, 48)
    subtitle_y: float = divider_y - 34 - 34 * subtitle_line_height * (len(subtitle_lines) - 1)
    image.append(
        draw.Text(
            subtitle_lines,
            34,
            margin,
            subtitle_y,
            fill=muted,
            font_family=SOCIAL_MEDIA_FONT,
            line_height=subtitle_line_height,
        )
    )
    image.append(
        draw.Line(
            margin,
            divider_y,
            width - margin,
            divider_y,
            stroke="#ffffff",
            stroke_width=2,
            stroke_opacity=0.6,
        )
    )

    # Headline figures, each label below its figure, vertically centred between the title and the country. Offsets
    # are from the top of the block. The hours figure uses a smaller font than the cost to leave room for the
    # breakdown below.
    hours_size: int = 64
    figures_block_h: int = 240 if show_hours else 116
    zone_top: float = title_bottom + 50
    zone_bottom: float = subtitle_y - 26 - 40
    figures_y: float = zone_top + max(0.0, (zone_bottom - zone_top - figures_block_h) / 2)
    image.append(
        draw.Text(
            format_currency(total_cost),
            88,
            margin,
            figures_y + 64,
            fill=ink,
            font_family=SOCIAL_MEDIA_FONT,
            font_weight="bold",
        )
    )
    image.append(
        draw.Text(
            "Estimated total cost",
            30,
            margin,
            figures_y + 108,
            fill=muted,
            font_family=SOCIAL_MEDIA_FONT,
        )
    )
    if show_hours:
        image.append(
            draw.Text(
                f"{total_hours:,.0f} hours",
                hours_size,
                margin,
                figures_y + 190,
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
                figures_y + 232,
                fill=muted,
                font_family=SOCIAL_MEDIA_FONT,
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
            height - 108,
            text_anchor="middle",
            fill=accent,
            font_weight="bold",
            font_family=SOCIAL_MEDIA_FONT,
        )
    )
    # Credit, with the authors on their own line below.
    image.append(
        draw.Text(
            ["The University of Sydney and SPARC.", "Alam, Andrew, Baker, Coupe, Koh, Lay, Loh, and Tanima 2026."],
            24,
            width - margin,
            height - 64,
            text_anchor="end",
            fill=muted,
            font_family=SOCIAL_MEDIA_FONT,
            line_height=28 / 24,
        )
    )
    return image


@st.cache_data(show_spinner=False)
def social_media_svg_to_png(svg: str) -> bytes:
    """Rasterises the social-media card for platforms that do not accept SVG uploads (e.g. LinkedIn, X, Facebook).

    Cached on the SVG markup, so the card is only re-rendered when its content changes.
    """
    return resvg_py.svg_to_bytes(svg_string=svg, sans_serif_family="Liberation Sans")


def share_summary(total_cost: float) -> str:
    """One-sentence summary of the estimate used as the pre-filled text of social media posts."""
    return (
        f"Using the Cost of Knowledge Calculator, I estimated that my research publication cost "
        f"{format_currency(total_cost)}."
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
def linkedin_share_url(total_cost: float, saved_url: str | None) -> str:
    """Builds a link that opens LinkedIn's post composer pre-filled with a summary of the estimate."""
    url, call_to_action = share_link(saved_url)
    text: str = f"{share_summary(total_cost)}\n\n{call_to_action} at {url}"
    return f"https://www.linkedin.com/feed/?shareActive=true&text={quote(text)}"


def x_share_url(total_cost: float, saved_url: str | None) -> str:
    """Builds a link that opens X's post composer pre-filled with a summary of the estimate and a link to share."""
    url, call_to_action = share_link(saved_url)
    text: str = f"{share_summary(total_cost)} {call_to_action}:"
    return f"https://x.com/intent/post?text={quote(text)}&url={quote(url, safe='')}"


def facebook_share_url(saved_url: str | None) -> str:
    """Builds a link that opens Facebook's share dialog for the saved result, or for the tool if it is not saved.

    Facebook's share dialog only accepts a URL; it does not allow pre-filled post text.
    """
    url, _ = share_link(saved_url)
    return f"https://www.facebook.com/sharer/sharer.php?u={quote(url, safe='')}"


def email_share_url(total_cost: float, saved_url: str | None) -> str:
    """Builds a mailto link that opens the user's email client with a pre-filled summary of the estimate."""
    url, call_to_action = share_link(saved_url)
    subject: str = "The Cost of Knowledge of my research publication"
    # RFC 6068 recommends CRLF line breaks in mailto bodies.
    body: str = f"{share_summary(total_cost)}\r\n\r\n{call_to_action} at {url}"
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
    return f"{st.context.url or ''}?{database.PROJECT_ID_QUERY_PARAM}={public_id}"


def copy_link_button(label: str, url: str, copied_label: str, help: str, key: str) -> None:
    """Draws a button that copies the given URL to the clipboard, showing copied_label for a moment afterwards."""
    _COPY_LINK_BUTTON(
        data={"label": label, "url": url, "copied_label": copied_label, "help": help},
        key=key,
        width="content",
    )


# -----------------------------------------------
# Model variables
# -----------------------------------------------


# Populate every calculator input (project details, people, activities, direct costs and progress through the tool)
# with the default state on the first run. CalculatorState.apply_to_session_state is also how a serialised
# calculator is imported, so the defaults and the serialised fields are defined in one place (calculator_state.py).
if "activity_list" not in st.session_state:
    CalculatorState.default().apply_to_session_state(st.session_state)


# Streamlit drops a widget's session state when the widget is not rendered in a run (e.g. on another page), so reseed
# the indirect cost rate slider's state rather than letting it fall back to its minimum.
if "indirect_cost_percentage" not in st.session_state:
    st.session_state["indirect_cost_percentage"] = DEFAULT_INDIRECT_COST_PERCENTAGE

if "user_country_select" not in st.session_state:
    st.session_state["user_country_select"]: str | None = st.session_state["user_country"] or None


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


# Load only when the query parameter changes, so the user's edits are not overwritten by the saved project every rerun.
query_project_id: str | None = st.query_params.get(database.PROJECT_ID_QUERY_PARAM)
if query_project_id is not None and query_project_id != st.session_state.get("loaded_query_project_id"):
    st.session_state["loaded_query_project_id"] = query_project_id
    load_from_database(query_project_id)


# -----------------------------------------------
# Header
# -----------------------------------------------


with st.sidebar:
    st.subheader("Contents")
    for toc_label, toc_anchor in TABLE_OF_CONTENTS:
        st.markdown(f"[{toc_label}](#{toc_anchor})")

st.title("Cost of Knowledge Calculator")
st.markdown(
    """
            <span style="font-size: 1.4rem">**As a researcher, have you thought about what it really costs to take a
            journal article from ideation to publication?**</span>

            "Debates about the economics of scholarly publishing typically focus on subscription prices, article
            processing charges, publisher revenues, and profit margins. Much less attention is paid to the costs
            incurred in producing the research that makes scholarly publishing possible."<sup>1</sup> This tool aims to
            make visible the substantial investment underpinning scholarly publishing.

            Using this tool, you can estimate the full costs involved in the process of preparing and publishing one of
            your refereed journal articles (including the cost of academic labor and institutional resources). Use your
            **best estimate** of the time and costs involved - if you aren't sure, we have provided estimates of the
            median time required for preparing a social science article from Alam et al. (2026), the publication
            accompanying this tool.

            The results of this tool should not be taken to reflect or quantify the value of research, only the costs
            involved in preparing a refereed journal article. Prior literature has established that research provides
            substantial economic and social returns<sup>2</sup>, and with this tool we instead seek to draw attention
            to the resources required for scholarly publishing.
            """,
    unsafe_allow_html=True,
)


with st.expander("About the data", expanded=False):
    st.markdown("""
                The hourly rates offered for each researcher role are median US rates including indirect on-costs, and
                are converted to your country's currency along with the direct costs. You can replace any rate or cost
                with your own figure.
                """)


# -----------------------------------------------
# User and Project
# -----------------------------------------------

st.header(":material/article: Your Refereed Journal Article", anchor=ARTICLE_ANCHOR)
st.markdown("""
            Please fill in some details about the refereed journal article you will estimate the cost for using this
            tool. The country primarily associated with this journal article will determine the currency that is
            displayed in the tool, and any costs already set will be converted based on recent exchange rates.
            """)

with st.container(border=True):
    st.selectbox(
        "The country your research project is primarily associated with/where most of the costs are incurred",
        COUNTRY_CODES,
        format_func=lambda code: COUNTRY_NAMES[code],
        key="user_country_select",
        index=None,
        placeholder="Choose a country. You may type to search for a country.",
        on_change=convert_monetary_values,
        help="The country chosen will determine the currency used for monetary values in this tool and the results "
        "calculated. You may clear the textbox and type to search for a country.",
    )
    st.session_state["international_collaborators"] = st.radio(
        "Does your project have international collaborators outside of the primary country?",
        [False, True],
        index=int(st.session_state["international_collaborators"]),
        format_func=lambda answer: "Yes" if answer else "No",
        horizontal=True,
    )
    # Options are 4-digit Field of Research codes. Keep a broad field name from a project saved before codes were
    # used selectable, so loading it does not fail.
    field_options: list[str] = list(FIELDS_OF_RESEARCH)
    if st.session_state["project_field"] and st.session_state["project_field"] not in FIELDS_OF_RESEARCH:
        field_options = [st.session_state["project_field"], *field_options]
    # Blank (index=None) until a field is chosen; the selectbox returns None then.
    st.session_state["project_field"] = (
        st.selectbox(
            "Field of research your paper/project is located in",
            field_options,
            index=field_options.index(st.session_state["project_field"]) if st.session_state["project_field"] else None,
            placeholder="Choose a field of research. You may type to search for a field of research.",
            format_func=field_of_research_display_name,
        )
        or ""
    )

st.subheader("Indirect Costs")
st.markdown(
    """
    These are costs that you do not incur directly as a researcher, but would still be considered part of
    the cost of preparing and publishing a refereed journal article. These indirect costs include
    **university/institution administrative costs, infrastructure costs including laboratories and equipment,
    journal subscriptions, database and software licenses, and open access agreements**.

    To capture these costs, an Indirect Cost Rate is applied to the hourly cost of labor. By default, we use a
    rate of 40% sourced from Azoulay et al. (2026)<sup>3</sup>, being an approximate middle ground within
    the range of effective indirect cost recovery rates they observe from a sample of US universities.
    """,
    unsafe_allow_html=True,
)
with st.expander("Optional: Adjust indirect cost rate"):
    # The widget's own session_state entry persists the rate across reruns; the salary dialog reads it from there.
    st.markdown(
        """
        If you are aware of your institution's Indirect Cost Rate (also known as an Indirect Cost Recovery rate or
        an On-cost Rate), you may adjust that rate here.
        """
    )
    st.slider(
        "Project-wide indirect cost rate (%)",
        step=1,
        min_value=0,
        max_value=100,
        key="indirect_cost_percentage",
        on_change=apply_indirect_cost_rate,
        help="Applied equally to every hourly rate calculated from a salary.",
    )

# -----------------------------------------------
# Study team
# -----------------------------------------------

st.header(":material/groups: People Involved in the Journal Article Preparation Process", anchor=PEOPLE_ANCHOR)
# TODO: People involved in preparing refereed journal publication - make it consistent. Have AI reword.
st.markdown("""
            Please identify the people involved in preparing the refereed journal article, from ideation to manuscript
            preparation.
            """)

with st.container(border=True):
    st.markdown("**Add a researcher**")
    researcher_form(ADD_PERSON_FORM_KEY)

if not st.session_state["people"]:
    st.info("No researchers added yet. Add at least one to start adding activities to the calculator.")
for key, person in st.session_state["people"].items():
    with st.container(border=True):
        label_column, rate_column, quantity_column, button_column = st.columns(
            [3, 1, 1, 1], vertical_alignment="center"
        )
        # Roles are shown by their US name, followed by their local name in the chosen country if it differs.
        role_name: str = (
            ROLES[person.role].display_name(st.session_state["user_country"])
            if person.role in ROLES
            else "Salary entered manually"
        )
        label_column.markdown(f"**{person.label}**  \n{role_name}")
        rate_column.markdown(f"**Hourly rate**  \n{format_hourly_rate(person.hourly_rate)}")
        quantity_column.markdown(f"**Quantity**  \n{person.quantity}")
        with button_column.container(horizontal=True, horizontal_alignment="left"):
            if st.button(
                "Edit",
                key=f"edit-person-button-{person.unique_key}",
                icon=":material/edit:",
            ):
                # Start the dialog's form from the researcher's current details.
                for form_key in list(st.session_state.keys()):
                    if isinstance(form_key, str) and form_key.startswith(f"edit-person-{person.unique_key}-"):
                        del st.session_state[form_key]
                edit_researcher(person)
            st.button(
                "Delete",
                key=f"delete-person-{person.unique_key}",
                icon=":material/delete:",
                help=f"Delete {person.label}. Their activities are reassigned to the first remaining researcher.",
                on_click=delete_person,
                args=[person.unique_key],
            )

# -----------------------------------------------
# Calculator
# -----------------------------------------------

st.header(":material/request_quote: Calculator", anchor=CALCULATOR_ANCHOR)

st.markdown("""
            Provide your best estimate of the activities and direct costs involved in preparing your refereed
            journal article. If you would like a starting point for filling out this tool, you may load the
            conservative estimates for a social sciences journal article from Alam et al. (2026), the publication
            accompanying this tool.
            """)
st.button(
    "Load defaults from Alam et al. 2026",
    key="load-alam-defaults",
    icon=":material/download:",
    on_click=load_alam_defaults,
    disabled=not st.session_state["people"],
    help=None if st.session_state["people"] else "Add a researcher to assign the activities to first.",
)

# TODO: Include buttons to load information about the activities/phases.
st.markdown("""
            The process has been divided between four distinct phases: **incubation**, **data collection and
            analysis**, **manuscript preparation**, and **peer review and journal editorial work**. You may either
            provide a total estimated hour count for each phase, or add individual activities and direct costs
            to provide estimates on a more granular level.
            """)

for phase, phase_name in RESEARCH_PHASES.items():
    # Handle special phases.
    if phase == "editing":
        st.subheader(phase_name)
        st.markdown("""
                    The cost of peer review and journal editorial work is based on the number of journals
                    submitted to and the average number of review rounds across journal submissions. We
                    assume that peer reviewers and journal editors have an average hourly rate of labour
                    equivalent to the loaded rate of a mid-career associate professor, though you may change
                    this rate below.
                    """)

        # Loading a state writes the sliders' values into their widget state, so seed it here rather than
        # passing value=, which would raise Streamlit's default-value-and-Session-State warning.
        if "review-rounds" not in st.session_state:
            st.session_state["review-rounds"] = st.session_state["review_rounds"]
        if "journal-submissions" not in st.session_state:
            st.session_state["journal-submissions"] = st.session_state["journal_submissions"]
        st.session_state["review_rounds"]: int = st.slider(
            "Average number of review rounds per journal submission",
            min_value=0,
            max_value=20,
            step=1,
            key="review-rounds",
            help="From Raoult(2020) and LeBlanc et al. (2023), we estimate that ",
        )
        st.session_state["peer_review_activity"].review_rounds: int = st.session_state["review_rounds"]

        st.session_state["journal_submissions"]: int = st.slider(
            "Number of journals submitted to",
            min_value=0,
            max_value=20,
            step=1,
            key="journal-submissions",
        )
        st.session_state["peer_review_activity"].journal_submissions: int = st.session_state["journal_submissions"]
        st.session_state["journal_editing_activity"].journal_submissions: int = st.session_state["journal_submissions"]

        # TODO: Remove or state that these rates reflect 40% indirect rate.
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
    else:
        st.subheader(phase_name)
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
                # A newly added activity has no name yet, so leave the selectbox unselected. Seed the widget's
                # state rather than passing index=, as the browser keeps showing (and sends back) the value it
                # already holds for a reused key unless the new value is written into the widget's state.
                current_activity_name: str | None = group_activities[0].name
                activity_options: list[str] = ACTIVITY_OPTIONS.get(phase, [])
                if current_activity_name is not None and current_activity_name not in activity_options:
                    activity_options = [current_activity_name] + activity_options
                activity_name_key: str = f"activity-name-{group_key}"
                if activity_name_key not in st.session_state:
                    st.session_state[activity_name_key] = current_activity_name
                activity_name: str | None = st.selectbox(
                    "Activity",
                    options=activity_options,
                    accept_new_options=True,
                    key=activity_name_key,
                    on_change=apply_activity_default,
                    args=[group_activities, group_key],
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
                    # Seed the widget's state rather than passing index=, as for the activity name. Fall back
                    # to the first person if the assigned person has been removed.
                    activity_person_key: str = f"activity-person-{group_activity.unique_key}"
                    if st.session_state.get(activity_person_key) not in st.session_state["people"]:
                        st.session_state[activity_person_key] = (
                            group_activity.person.unique_key
                            if group_activity.person.unique_key in st.session_state["people"]
                            else next(iter(st.session_state["people"]))
                        )

                    # Only label the first row so the rows below it read as a list.
                    row_label_visibility: str = "visible" if person_index == 0 else "collapsed"
                    person_column, hours_column, delete_column = st.columns([2, 1, 1], vertical_alignment="bottom")
                    person_column.selectbox(
                        "Assigned person",
                        st.session_state["people"].keys(),
                        key=activity_person_key,
                        format_func=person_option_display,
                        label_visibility=row_label_visibility,
                        on_change=set_activity_person,
                        args=[group_activity, group_activity.unique_key],
                    )
                    # Choosing a preset activity writes its default hours into the widget's state, so pass
                    # the "min" sentinel once it exists to avoid Streamlit's default-value-and-Session-State
                    # warning.
                    activity_hours_key: str = f"activity-hours-{group_activity.unique_key}"
                    group_activity.hours: float = hours_column.number_input(
                        "Hours",
                        key=activity_hours_key,
                        min_value=0.0,
                        step=0.5,
                        value="min" if activity_hours_key in st.session_state else float(group_activity.hours),
                        label_visibility=row_label_visibility,
                    )
                    # An activity always keeps its first person, so that row has no delete button.
                    if person_index > 0:
                        delete_column.button(
                            "Del",
                            key=f"delete-activity-person-{group_activity.unique_key}",
                            help=f"Remove {group_activity.person.label} from this activity",
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
                # A newly added cost has no name yet, so leave the selectbox unselected. Seed the widget's state
                # rather than passing index=, as for the activity name.
                cost_options: list[str] = COST_OPTIONS.get(phase, [])
                if phase_cost.name is not None and phase_cost.name not in cost_options:
                    cost_options = [phase_cost.name] + cost_options
                cost_name_key: str = f"directcost-name-{phase_cost.unique_key}"
                if cost_name_key not in st.session_state:
                    st.session_state[cost_name_key] = phase_cost.name
                phase_cost.name: str | None = st.selectbox(
                    "Cost",
                    options=cost_options,
                    accept_new_options=True,
                    key=cost_name_key,
                    on_change=apply_direct_cost_default,
                    args=[phase_cost],
                )
                # Create badge if new cost
                if phase_cost.name is None:
                    st.badge(
                        "New cost, fill in details",
                        icon=":material/exclamation:",
                        color="orange",
                    )

                # Currency conversion writes into the widget's state, so pass the "min" sentinel once it
                # exists to avoid Streamlit's default-value-and-Session-State warning.
                directcost_cost_key: str = f"directcost-cost-{phase_cost.unique_key}"
                phase_cost.cost: float = st.number_input(
                    f"Cost ({currency_code()})",
                    key=directcost_cost_key,
                    min_value=0.0,
                    step=0.50,
                    value="min" if directcost_cost_key in st.session_state else float(phase_cost.cost),
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
                disabled=not st.session_state["people"],
                help=None if st.session_state["people"] else "Add a researcher to assign the activity to first.",
            )
            st.button(
                "Add Direct Cost",
                key=f"add-direct-cost-{phase}",
                icon=":material/request_quote:",
                on_click=add_direct_cost,
                args=[phase],
            )

# Special phase for saving to the database, shown only when a database is configured.
if DATABASE_TYPE in ("sqlite", "mysql"):
    st.subheader("Save and share your result?")
    st.markdown("""
                If you would like to share your result with others, we will require your permission to save
                the information you have input into this tool. If you are happy to do so, please click on the
                button below. You can then share your result with the buttons below.
                """)
    with st.container(horizontal=True, horizontal_alignment="left"):
        if st.button(
            "Save your result to share",
            icon=":material/save:",
            type="primary",
            help="Save your inputs to the database. Saving again after making changes saves them as a new "
            "result, generating a new share link. Old links will not show your changes.",
        ):
            save_to_database()
        st.button(
            "Continue without saving",
            key="close-without-saving",
            icon=":material/close:",
        )


# Visualisation pane


# Calculate total costs and total hours.
combined_costs_list: list[Cost] = st.session_state["activity_list"] + st.session_state["cost_list"]
total_cost: float = compute_costs(combined_costs_list)
total_hours: float = compute_hours(st.session_state["activity_list"])


# Colour maps shared by the charts below. Derived fresh each run (rather than persisted)
# so newly added activities always get a colour; phases always take the same colours and
# activity/direct-cost names keep a consistent colour wherever they appear.
phase_color_map: dict[str, str] = build_color_map(list(RESEARCH_PHASES.values()))
item_color_map: dict[str, str] = build_color_map([item.get_name() or "Unnamed" for item in combined_costs_list])
person_color_map: dict[str, str] = build_color_map(
    [activity.get_person().label for activity in st.session_state["activity_list"]]
)


st.header("The Cost of Your Refereed Journal Article", anchor=RESULTS_HEADER_ANCHOR)


# Scrolls to the header above once after a button that finishes the calculator is clicked. The flag is removed so later
# reruns do not scroll. Streamlit has no scrolling API, so this uses JavaScript.
if st.session_state.pop("scroll_to_results", False):
    st.html(
        f"""
        <script>
            {{
                const resultsHeader = document.getElementById("{RESULTS_HEADER_ANCHOR}");
                if (resultsHeader) {{
                    resultsHeader.scrollIntoView({{ block: "start" }});
                }}
            }}
        </script>
        """,
        unsafe_allow_javascript=True,
    )


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
        "Person": [activity.get_person().label for activity in st.session_state["activity_list"]],
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
# Sunburst traces cannot show a legend, so add an invisible placeholder trace per phase to create
# legend entries. The legend takes up the same space as the pie chart's legend, aligning the two charts.
for phase in (phase for phase in phase_color_map if phase in set(labour_df["Phase"])):
    sunburst.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            marker={"color": phase_color_map[phase], "size": 12, "symbol": "square"},
            name=phase,
            hoverinfo="skip",
        )
    )
sunburst.update_xaxes(visible=False)
sunburst.update_yaxes(visible=False)
sunburst.update_layout(height=720, showlegend=True, legend={"itemclick": False, "itemdoubleclick": False})
st.plotly_chart(sunburst, width="stretch")
st.caption(
    "Percentages are calculated as a percentage of the total cost of the "
    "paper, including direct costs that are not shown in this chart."
)


# Hours of labour per person bar chart
hours_per_person_df = labour_df.groupby("Person", as_index=False)["Hours"].sum().sort_values("Hours", ascending=False)


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
# Conclusion
# -----------------------------------------------


st.header(":material/share: Share your result", anchor=SHARE_ANCHOR)


st.markdown("""
            Share your result using the buttons below.
            """)


st.markdown("""
            You may choose to show the total number of hours on your results image. However, for one-person or small
            teams, this may be used to approximate your salary.
            """)


# Keyed so the choice persists across reruns; hours are hidden by default.
if "share_show_hours" not in st.session_state:
    st.session_state["share_show_hours"] = False
st.toggle("Show estimated hours of labor on the image", key="share_show_hours")


# Rendered fresh each run from the (persisted) project inputs and computed totals,
# so it never needs its own st.session_state entry.
social_media_svg: str = create_social_media_svg(
    country=COUNTRY_NAMES.get(st.session_state["user_country"], ""),
    international_collaborators=st.session_state["international_collaborators"],
    # Only the group name, as the division name would make the title too long for the card. Projects saved before
    # Field of Research codes were used hold a broad field name instead.
    project_field=(
        FIELDS_OF_RESEARCH[st.session_state["project_field"]].name
        if st.session_state["project_field"] in FIELDS_OF_RESEARCH
        else st.session_state["project_field"]
    ),
    total_cost=total_cost,
    total_hours=total_hours,
    phase_costs={label: compute_costs(combined_costs_list, phase=key) for key, label in RESEARCH_PHASES.items()},
    show_hours=st.session_state["share_show_hours"],
).as_svg()


with st.container(horizontal=True, horizontal_alignment="center"):
    st.image(social_media_svg, width=540)


# Link to the saved result, which the share buttons use in place of the tool's link once the result is saved. Saving
# happens above in the setup pane, so the buttons update in the same run as the save.
saved_result_url: str | None = (
    saved_project_url(st.session_state["database_public_id"])
    if st.session_state.get("database_public_id") is not None
    else None
)


# TODO: Add names to our social media share message.
# TODO: Move the save button here.
# TODO: Add messaging above the share posts.


with st.container(horizontal=True, horizontal_alignment="left"):
    st.download_button(
        "Download image",
        data=social_media_svg_to_png(social_media_svg),
        file_name="cost-of-knowledge-estimate.png",
        mime="image/png",
        icon=":material/image:",
        type="primary",
    )
    st.link_button(
        "Share on LinkedIn",
        linkedin_share_url(total_cost, saved_result_url),
        icon=":material/share:",
        help="Share this tool on LinkedIn. Download the image first and attach it to your post.",
    )
    st.link_button(
        "Share on X",
        x_share_url(total_cost, saved_result_url),
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
        email_share_url(total_cost, saved_result_url),
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


st.markdown(
    """
            <sup>1</sup> Alam et al. (2026) The Cost of Knowledge. Preprint available on Zenodo.

            <sup>2</sup> Jones, B. F., & Summers, L. H. (Eds.). (2022). A Calculation of the Social Returns to
            Innovation. In Innovation and Public Policy (pp. 13–60). University of Chicago Press.
            https://doi.org/10.7208/chicago/9780226805597.003.0002;
            Salter, A. J., & Martin, B. R. (2001). The economic benefits of publicly funded basic research: A critical
            review. Research Policy, 30(3), 509–532. https://doi.org/10.1016/S0048-7333(00)00091-3.

            <sup>3</sup> Azoulay, P., Gross, D. P., & Sampat, B. N. (2026). Indirect Cost Recovery in US Innovation
            Policy: History, Evidence, and Avenues for Reform. Entrepreneurship and Innovation Policy and the Economy,
            5, 133–182. https://doi.org/10.1086/738903

            :small[:material/copyright: Copyright 2026 Alam, Andrew, Baker, Coupe, Koh,
            Lay, Loh, and Tanima.
            :material/license: The content on this website is subject to the [Creative Commons Attribution 4.0
            International License](https://creativecommons.org/licenses/by/4.0/).]
            """,
    unsafe_allow_html=True,
)
