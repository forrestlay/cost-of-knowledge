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

import pandas as pd
import plotly.express as px
import streamlit as st

from models import (
    BaseActivity,
    Person,
    PersonType,
    Cost,
    Activity,
    DirectCost,
    JournalEditing,
    PeerReview,
)

st.set_page_config(page_title="Cost of Knowledge Calculator", layout="wide")

TOOL_STEPS: list[str] = [
    "people",
    "incubation",
    "data",
    "writing",
    "editing",
    "end",
]

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

# TODO: Add dict of lists with preset activities and costs.
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
    ],
    "writing": [
        "Proofreading and Editing Services",
    ],
}

# Setup session variable to track progress through CoK tool.
if "tool_step" not in st.session_state:
    st.session_state["tool_step"]: int = 0


def compute_costs(costs: list[Cost], phase: str | None = None) -> float:
    """Calculates the total cost of activities and direct costs in the given list.

    Args:
        costs: A list of Cost items (Activities or DirectCosts).
        phase: If not None (default), only calculates costs for the given RESEARCH_PHASE key.
    """
    total_cost: float = 0.0
    for cost_item in costs:
        if phase is None or phase == cost_item.phase:
            total_cost += cost_item.get_total_cost()
    return total_cost


def compute_hours(activities: list[BaseActivity], phase: str | None = None) -> float:
    """Calculates the total labour hours of activities in the given list.

    Args:
        costs: A list of Activity items.
        phase: If not None (default), only calculates hours for the given RESEARCH_PHASE key.
    """
    total_hours: float = 0.0
    for activity in activities:
        if phase is None or phase == activity.get_phase():
            total_hours += activity.get_hours()
    return total_hours


def format_usd(x: int | float) -> str:
    """Formats an int or float to a string displaying US$."""
    return f"US${x:,.0f}"


# -----------------------------------------------
# Model variables
# -----------------------------------------------

# Create initial people roles.
if "people" not in st.session_state:
    default_person: Person = Person(
        name="Associate Professor",
        unique_key="1",
        person_type=PersonType.RESEARCH_TEAM,
        hourly_rate=85,
    )

    st.session_state["people"]: dict[str, Person] = {
        default_person.unique_key: default_person,
    }

if "peer_reviewer" not in st.session_state:
    st.session_state["peer_reviewer"]: Person = Person(
        name="Peer reviewer",
        unique_key="Peer reviewer",
        person_type=PersonType.OTHER,
        hourly_rate=85,
    )

if "journal_editor" not in st.session_state:
    st.session_state["journal_editor"]: Person = Person(
        name="Journal editor",
        unique_key="Journal editor",
        person_type=PersonType.OTHER,
        hourly_rate=85,
    )

# Populate initial list of activities and costs.
if "peer_review_activity" not in st.session_state:
    st.session_state["peer_review_activity"]: PeerReview = PeerReview(
        person=st.session_state["peer_reviewer"],
        review_rounds=3,
        journal_submissions=1,
        unique_key=9,
    )

if "journal_editing_activity" not in st.session_state:
    st.session_state["journal_editing_activity"]: JournalEditing = JournalEditing(
        person=st.session_state["journal_editor"],
        journal_submissions=1,
        unique_key=10,
    )

if "activity_list" not in st.session_state:
    st.session_state["activity_list"]: list[BaseActivity] = [
        Activity(
            "Ideation and conception",
            st.session_state["people"]["1"],
            "incubation",
            55,
            1,
        ),
        Activity(
            "Ethics approval", st.session_state["people"]["1"], "incubation", 60, 2
        ),
        Activity(
            "Grant applications", st.session_state["people"]["1"], "incubation", 171, 3
        ),
        Activity("Data collection", st.session_state["people"]["1"], "data", 48.5, 4),
        Activity(
            "Interview transcription", st.session_state["people"]["1"], "data", 60.5, 5
        ),
        Activity("Data analysis", st.session_state["people"]["1"], "data", 157.5, 6),
        Activity(
            "Writing and manuscript preparation",
            st.session_state["people"]["1"],
            "writing",
            100,
            7,
        ),
        Activity(
            "Conferencing (labor)", st.session_state["people"]["1"], "writing", 123, 8
        ),
        st.session_state["peer_review_activity"],
        st.session_state["journal_editing_activity"],
    ]

# Create peer review and journal editorial variables.
if "journal_submissions" not in st.session_state:
    st.session_state["journal_submissions"]: int = 1
if "review_rounds" not in st.session_state:
    st.session_state["review_rounds"]: int = 3

if "cost_list" not in st.session_state:
    st.session_state["cost_list"]: list[DirectCost] = [
        DirectCost("Participant incentivization", "data", 246, 1),
        DirectCost("Conferencing (direct costs)", "writing", 3400, 2),
    ]

# -----------------------------------------------
# Header
# -----------------------------------------------

st.title("Cost of Knowledge Calculator")
st.caption(
    "The tool will enable you to calculate the approximate cost of preparing a refereed journal article from conception to publication."
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
# Study team
# -----------------------------------------------

st.subheader("People Involved in the Article Preparation Process")
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
            int(person.unique_key)
            for person in st.session_state["people"].values()
            if person.unique_key.isdigit()
        ]
        key = str(max(person_key_list) + 1)
    st.session_state["people"][key] = Person(
        name="New person",
        unique_key=key,
        person_type=PersonType.RESEARCH_TEAM,
        hourly_rate=85,
    )


def delete_person(key: str):
    del st.session_state["people"][key]


# Create session variables to track if the salary calculation dialog has run.
if "salary_calculation_result" not in st.session_state:
    st.session_state["salary_calculation_result"]: int | float | None = None
if "salary_calculation_person" not in st.session_state:
    st.session_state["salary_calculation_person"]: Person | None = None


@st.dialog("Calculate your hourly rate")
def calculate_hourly_rate(person: Person, key: str):
    salary: int = st.number_input("What is your salary?", step=1, min_value=0)
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
        st.session_state["salary_calculation_result"] = Person.salary_to_hourly_rate(
            salary, weekly_hours, months, indirect_cost_multiplier
        )
        st.session_state["salary_calculation_person"] = person

        # Hack to get salary calculation to stick. The default value on the st.number_input overrides the calculated
        # value, which makes it difficult to change this variable outside of the input itself.
        st.session_state[f"person-rate-{key}"] = st.session_state[
            "salary_calculation_result"
        ]
        st.rerun()


def next_tool_step(current_step: str):
    """Navigates to the next step in the tool, opening the relevant expander.

    Args:
        current_step: The current step, matching a string in TOOL_STEPS.
    """
    if (
        st.session_state["tool_step"] < len(TOOL_STEPS) - 1
        and current_step == TOOL_STEPS[st.session_state["tool_step"]]
    ):
        st.session_state["tool_step"]: int = 1 + st.session_state["tool_step"]
    else:
        st.rerun()  # Rerun script to close expandable.


# Check if tool is at the people step, expand Roles expander if True.
people_step: bool = (
    True if TOOL_STEPS[st.session_state["tool_step"]] == "people" else False
)

with st.expander("Roles", expanded=people_step):
    for key, person in st.session_state["people"].items():
        with st.container(border=True):
            # Check if person name is in the roles list.
            try:
                person_name_index = ROLES.index(person.name)
            except ValueError:
                person_name_index = 1

            # Inputs
            person.name: str = st.selectbox(
                "Name",
                options=ROLES,
                index=person_name_index,
                accept_new_options=True,
                key=f"person-name-{person.unique_key}",
            )
            person.hourly_rate: int | float = st.number_input(
                "Hourly rate of labor including indirect on-costs",
                value=person.hourly_rate,
                key=f"person-rate-{person.unique_key}",
            )
            with st.container(horizontal=True, horizontal_alignment="left"):
                if st.button(
                    "Calculate hourly wage using salary",
                    key=f"calculate-hourly-wage-{person.unique_key}",
                ):
                    calculate_hourly_rate(person, person.unique_key)
                if (
                    person.person_type == PersonType.RESEARCH_TEAM
                    and int(person.unique_key) > 1
                ):
                    st.button(
                        f"Delete {person.name}",
                        key=f"delete-person-{person.unique_key}",
                        icon=":material/delete:",
                        on_click=delete_person,
                        args=[person.unique_key],
                    )

            # Check if the calculation dialog was run
            if (
                st.session_state["salary_calculation_person"] is not None
                and st.session_state["salary_calculation_person"] == person
                and st.session_state["salary_calculation_result"] is not None
            ):
                person.hourly_rate: int | float = st.session_state[
                    "salary_calculation_result"
                ]
                st.session_state["salary_calculation_person"] = None
                st.session_state["salary_calculation_result"] = None

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
        return f"{key}: {person.name}"
    else:
        return key


def person_option_decode(display_string: str):
    """Converts a st.selectbox display name to a st.session_state["people"] key."""
    return display_string.split(":")[0]


def set_activity_person(activity: Activity, counter: int):
    """Callback for st.selectbox to select the person assigned to an activity."""
    people_key: str = person_option_decode(
        st.session_state[f"activity-person-{counter}"]
    )
    activity.person: Person = st.session_state["people"][people_key]


def add_activity(phase: str):
    activity_key_list: list[int] = [
        activity.unique_key for activity in st.session_state["activity_list"]
    ]
    st.session_state["activity_list"].append(
        Activity(
            "New Activity",
            st.session_state["people"]["1"],
            phase,
            0.0,
            max(activity_key_list) + 1,
        )
    )


def delete_activity(activity: Activity):
    st.session_state["activity_list"].remove(activity)


def add_direct_cost(phase: str):
    cost_key_list: list[int] = [
        direct_cost.unique_key for direct_cost in st.session_state["cost_list"]
    ]
    st.session_state["cost_list"].append(
        DirectCost("New Cost", phase, 0.0, max(cost_key_list) + 1)
    )


def delete_direct_cost(direct_cost: DirectCost):
    st.session_state["cost_list"].remove(direct_cost)


st.subheader("Calculator")

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
        phase_expand: bool = (
            True if TOOL_STEPS[st.session_state["tool_step"]] == phase else False
        )

        # Handle special phases.
        if phase == "editing":
            with st.expander(phase_name, expanded=phase_expand):
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
                st.session_state[
                    "peer_review_activity"
                ].review_rounds: int = st.session_state["review_rounds"]

                st.session_state["journal_submissions"]: int = st.slider(
                    "Number of journals submitted to",
                    min_value=1,
                    max_value=20,
                    value=st.session_state["journal_submissions"],
                    step=1,
                    key="journal-submissions",
                )
                st.session_state[
                    "peer_review_activity"
                ].journal_submissions: int = st.session_state["journal_submissions"]
                st.session_state[
                    "journal_editing_activity"
                ].journal_submissions: int = st.session_state["journal_submissions"]

                st.session_state["peer_reviewer"].hourly_rate: int | float = (
                    st.number_input(
                        "Hourly rate of peer reviewer",
                        value=st.session_state["peer_reviewer"].hourly_rate,
                    )
                )
                st.session_state["journal_editor"].hourly_rate: int | float = (
                    st.number_input(
                        "Hourly rate of journal editor",
                        value=st.session_state["journal_editor"].hourly_rate,
                    )
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
            with st.expander(phase_name, expanded=phase_expand):
                phase_activities: list[Activity] = [
                    activity
                    for activity in st.session_state["activity_list"]
                    if isinstance(activity, Activity) and activity.get_phase() == phase
                ]
                for phase_activity in phase_activities:
                    try:  # Get index of person in list of people.
                        activity_person_index: int = list(
                            st.session_state["people"].keys()
                        ).index(phase_activity.person.unique_key)
                    except ValueError:
                        activity_person_index: int = 2

                    with st.container(border=True):
                        phase_activity.name: str = st.text_input(
                            "Activity",
                            key=f"activity-name-{phase_activity.unique_key}",
                            value=phase_activity.name,
                        )
                        # Create badge if new activity
                        if phase_activity.name == "New Activity":
                            st.badge(
                                "New activity, fill in details",
                                icon=":material/exclamation:",
                                color="orange",
                            )

                        st.session_state["update_activity_person"]: str = st.selectbox(
                            "Assigned person",
                            st.session_state["people"].keys(),
                            key=f"activity-person-{phase_activity.unique_key}",
                            index=activity_person_index,
                            format_func=person_option_display,
                            on_change=set_activity_person,
                            args=[phase_activity, phase_activity.unique_key],
                        )

                        phase_activity.hours: float = st.number_input(
                            "Total hours",
                            key=f"activity-hours-{phase_activity.unique_key}",
                            min_value=0.0,
                            step=0.5,
                            value=float(phase_activity.get_hours()),
                        )
                        # Show badge if hours is 0.
                        if phase_activity.get_hours() == 0.0:
                            st.badge(
                                "Hours are set to 0",
                                icon=":material/exclamation:",
                                color="orange",
                            )

                        st.button(
                            "Delete activity",
                            key=f"delete-activity-{phase_activity.unique_key}",
                            icon=":material/delete:",
                            on_click=delete_activity,
                            args=[phase_activity],
                        )

                phase_costs: list[DirectCost] = [
                    direct_cost
                    for direct_cost in st.session_state["cost_list"]
                    if direct_cost.phase == phase
                ]
                for phase_cost in phase_costs:
                    with st.container(border=True):
                        phase_cost.name: str = st.text_input(
                            "Cost",
                            key=f"directcost-name-{phase_cost.unique_key}",
                            value=phase_cost.name,
                        )
                        # Create badge if new cost
                        if phase_cost.name == "New Cost":
                            st.badge(
                                "New cost, fill in details",
                                icon=":material/exclamation:",
                                color="orange",
                            )

                        phase_cost.cost: float = st.number_input(
                            "Cost US$",
                            key=f"directcost-cost-{phase_cost.unique_key}",
                            min_value=0.0,
                            step=0.50,
                            value=float(phase_cost.cost),
                        )
                        # Show badge if hours is 0.
                        if phase_cost.cost == 0.0:
                            st.badge(
                                "Cost is set to $0",
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

# Visualisation pane

# Calculate total costs and total hours.
combined_costs_list: list[Cost] = (
    st.session_state["activity_list"] + st.session_state["cost_list"]
)  # ty:ignore[invalid-assignment]
total_cost: float = compute_costs(combined_costs_list)
total_hours: float = compute_hours(st.session_state["activity_list"])

with main_right:
    k1, k2, k3 = st.columns(3)
    k1.metric("Estimated total cost", format_usd(total_cost))
    k2.metric("Estimated labor hours", f"{total_hours:.0f} h")
    k3.metric(
        "Estimated direct costs",
        format_usd(compute_costs(st.session_state["cost_list"])),  # ty:ignore[invalid-argument-type]
    )

    st.markdown("""
                Click on the phases and people in the charts below to see the breakdown of costs within each.
                """)

    # Pie chart
    phase_df = pd.DataFrame(
        {
            "Phase": [
                "Incubation",
                "Data collection and analysis",
                "Manuscript preparation",
                "Peer review and journal editorial work",
            ],
            "Cost (USD)": [
                compute_costs(combined_costs_list, "incubation"),
                compute_costs(combined_costs_list, "data"),
                compute_costs(combined_costs_list, "writing"),
                compute_costs(combined_costs_list, "editing"),
            ],
        }
    )
    pie = px.pie(
        phase_df, names="Phase", values="Cost (USD)", title="Total Cost Breakdown"
    )
    st.plotly_chart(pie, width="stretch")

    # Labour cost bar chart
    labour_df = pd.DataFrame(
        {
            "Activity": [
                activity.get_name() for activity in st.session_state["activity_list"]
            ],
            "Cost (USD)": [
                activity.get_total_cost()
                for activity in st.session_state["activity_list"]
            ],
            "Hours": [
                activity.get_hours() for activity in st.session_state["activity_list"]
            ],
            "Phase": [
                RESEARCH_PHASES[activity.get_phase()]
                for activity in st.session_state["activity_list"]
            ],
            "Person": [
                activity.get_person().name
                for activity in st.session_state["activity_list"]
            ],
        }
    )

    sunburst = px.sunburst(
        labour_df,
        path=["Phase", "Person", "Activity"],
        values="Cost (USD)",
        title="Cost of Labor Breakdown by Phase, Role and Activity",
    )
    sunburst.update_layout(height=800)
    st.plotly_chart(sunburst, width="stretch")

    labour_chart_selection = st.pills(
        "**Show labor as**", ["Cost (USD)", "Hours"], default="Cost (USD)"
    )

    labour_chart = px.bar(
        labour_df,
        x="Activity",
        y=labour_chart_selection,
        color="Phase",
        title="Cost of and Time Spent on Labor Activities",
        text_auto=True,
    )
    if labour_chart_selection == "Cost (USD)":
        labour_chart.update_traces(texttemplate="%{y:$.2f}", textposition="outside")
    else:
        labour_chart.update_traces(
            texttemplate="%{y:.1f} hours", textposition="outside"
        )
    labour_chart.update_yaxes(tickprefix="$")
    st.plotly_chart(labour_chart, width="stretch")


# -----------------------------------------------
# Conclusion
# -----------------------------------------------

st.subheader("Share your result")

st.markdown("""
            Share your result using the buttons below.
            """)

with st.container(horizontal=True, horizontal_alignment="left"):
    st.button("Email result", icon=":material/email:")

# TODO: Determine licensing of this code.
st.markdown("""
            :small[:material/copyright: Copyright 2026 Nurul Alam, Jane Andrew, Max Baker, Janine Coupe, Tai-Joo Koh, Ben Lay,
            Chang-yuan Loh, and Farzana Tanima.
            :material/license: The Cost of Knowledge Tool is licensed under the Apache License, Version 2.0.]
            """)
