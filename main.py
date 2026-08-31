from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from models import Person, PersonType, Cost, Activity, DirectCost

st.set_page_config(page_title="Cost of Knowledge Calculator", layout="wide")

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
]

RESEARCH_PHASES: dict[str, str] = {
    "incubation": "Incubation",
    "data": "Data collection and analysis",
    "writing": "Manuscript preparation",
    "editing": "Peer review and journal editorial work",
}


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


def compute_hours(activities: list[Activity], phase: str | None = None) -> float:
    """Calculates the total labour hours of activities in the given list.

    Args:
        costs: A list of Activity items.
        phase: If not None (default), only calculates hours for the given RESEARCH_PHASE key.
    """
    total_hours: float = 0.0
    for activity in activities:
        if phase is None or phase == activity.phase:
            total_hours += activity.hours
    return total_hours


def format_usd(x: int | float) -> str:
    """Formats an int or float to a string displaying US$."""
    return f"US${x:,.0f}"


# -----------------------------------------------
# Model variables
# -----------------------------------------------
if "people" not in st.session_state:
    default_person: Person = Person(
        name="Associate Professor",
        unique_key="1",
        person_type=PersonType.RESEARCH_TEAM,
        hourly_rate=85,
    )
    peer_reviewer: Person = Person(
        name="Peer reviewer",
        unique_key="Peer reviewer",
        person_type=PersonType.OTHER,
        hourly_rate=85,
    )
    journal_editor: Person = Person(
        name="Journal editor",
        unique_key="Journal editor",
        person_type=PersonType.OTHER,
        hourly_rate=85,
    )
    st.session_state["people"]: dict[str, Person] = {
        peer_reviewer.unique_key: peer_reviewer,
        journal_editor.unique_key: journal_editor,
        default_person.unique_key: default_person,
    }

if "activity_list" not in st.session_state:
    st.session_state["activity_list"]: list[Activity] = [
        Activity(
            "Ideation and conception", st.session_state["people"]["1"], "incubation", 55
        ),
        Activity("Ethics approval", st.session_state["people"]["1"], "incubation", 60),
        Activity(
            "Grant applications", st.session_state["people"]["1"], "incubation", 171
        ),
        Activity("Data collection", st.session_state["people"]["1"], "data", 34),
        Activity(
            "Interview transcription", st.session_state["people"]["1"], "data", 42.5
        ),
        Activity("Data analysis", st.session_state["people"]["1"], "data", 112.5),
        Activity(
            "Writing and manuscript preparation",
            st.session_state["people"]["1"],
            "writing",
            100,
        ),
        Activity(
            "Conferencing (labour)", st.session_state["people"]["1"], "writing", 123
        ),
        Activity(
            "Peer review", st.session_state["people"]["Peer reviewer"], "editing", 9
        ),
        Activity(
            "Journal editorial work",
            st.session_state["people"]["Journal editor"],
            "editing",
            15,
        ),
    ]

if "cost_list" not in st.session_state:
    st.session_state["cost_list"]: list[DirectCost] = [
        DirectCost("Participant incentivization", "data", 246),
        DirectCost("Conferencing (direct costs)", "writing", 3400),
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

st.subheader("People Involved in the Article Preperation Process")
st.markdown("""
            Fill in the details of the people who are involved in the preparation of your journal article.
            Details have been pre-filled for the peer reviewer and journal editor roles.
            The hourly rates below will be used to calculate the cost of labour for most of the steps involved in the
            journal preparation process.
            """)

if "study_team_finalised" not in st.session_state:
    st.session_state[
        "study_team_finalised"
    ]: bool = False  # Expands study team expander until team is finalised.


def add_person(key: str):
    st.session_state["people"][key] = Person(
        name="New person",
        unique_key=key,
        person_type=PersonType.RESEARCH_TEAM,
        hourly_rate=85,
    )


def delete_person(key: str):
    del st.session_state["people"][key]


@st.dialog("Calculate your hourly rate")
def calculate_hourly_rate(person: Person):
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
    if st.button("Calculate"):
        person.salary_to_hourly_rate(salary, weekly_hours, months)
        st.rerun()


def team_finalised():
    st.session_state["study_team_finalised"]: bool = True


person_counter: int = 1  # Used to set a unique key for each person.

with st.expander("Roles", expanded=not st.session_state["study_team_finalised"]):
    for key, person in st.session_state["people"].items():
        with st.container(border=True):
            try:
                person_name_index = ROLES.index(person.name)
            except ValueError:
                person_name_index = 1
            person.name: str = st.selectbox(
                "Name",
                options=ROLES,
                index=person_name_index,
                accept_new_options=True,
                key=f"person-name-{person_counter}",
            )
            person.hourly_rate: int | float = st.number_input(
                "Hourly wage",
                value=person.hourly_rate,
                key=f"person-rate-{person_counter}",
            )
            with st.container(horizontal=True, horizontal_alignment="left"):
                if st.button(
                    "Calculate hourly wage using salary",
                    key=f"calculate-hourly-wage-{person_counter}",
                ):
                    calculate_hourly_rate(person)
                if (
                    person_counter > 3
                    and person.person_type == PersonType.RESEARCH_TEAM
                ):
                    st.button(
                        f"Delete {person.name}",
                        key=f"delete-person-{person_counter}",
                        icon=":material/delete:",
                        on_click=delete_person,
                        args=[key],
                    )
        person_counter += 1

    with st.container(horizontal=True, horizontal_alignment="left"):
        add_person_key = str(
            person_counter - 2
        )  # Subtract 2 to account for peer reviewer and journal editor roles.
        st.button(
            "Add person/role",
            key="add-person",
            icon=":material/add:",
            on_click=add_person,
            args=[add_person_key],
        )
        st.button(
            "Finalize team",
            key="confirm-team",
            type="primary",
            icon=":material/check:",
            on_click=team_finalised,
        )

# -----------------------------------------------
# Calculator
# -----------------------------------------------


def person_option_display(key: str):
    """Converts a st.session_state["people"] key to a display name."""
    person: Person = st.session_state["people"][key]
    if person.person_type == PersonType.RESEARCH_TEAM:
        return f"{key}: {person.name}"
    else:
        return key

# TODO: Fix this method to actually set the person.
def set_activity_person(activity: Activity):
    """Callback for st.selectbox to select the person assigned to an activity."""
    activity.person: Person = st.session_state["people"][
        st.session_state["update_activity_person"]
    ]


st.subheader("Calculator")

main_left, main_right = st.columns([1, 2])

with main_left:
    cost_counter = 1  # Used to give each cost input a unique key

    for phase, phase_name in RESEARCH_PHASES.items():
        with st.expander(phase_name):
            phase_activities: list[Activity] = [
                activity
                for activity in st.session_state["activity_list"]
                if activity.phase == phase
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
                        key=f"activity-name-{cost_counter}",
                        value=phase_activity.name,
                    )
                    st.session_state["update_activity_person"]: str = st.selectbox(
                        "Assigned person",
                        st.session_state["people"].keys(),
                        key=f"activity-person-{cost_counter}",
                        index=activity_person_index,
                        format_func=person_option_display,
                        on_change=set_activity_person,
                        args=[phase_activity],
                    )
                    phase_activity.hours: float = st.number_input(
                        "Total hours",
                        key=f"activity-hours-{cost_counter}",
                        min_value=0.0,
                        step=0.5,
                        value=float(phase_activity.hours),
                    )
                cost_counter += 1

            phase_costs: list[DirectCost] = [
                direct_cost
                for direct_cost in st.session_state["cost_list"]
                if direct_cost.phase == phase
            ]
            for phase_cost in phase_costs:
                with st.container(border=True):
                    phase_cost.name: str = st.text_input(
                        "Cost",
                        key=f"directcost-name-{cost_counter}",
                        value=phase_cost.name,
                    )
                    phase_cost.cost: float = st.number_input(
                        "Cost US$",
                        key=f"directcost-cost-{cost_counter}",
                        min_value=0.0,
                        step=0.50,
                        value=float(phase_cost.cost),
                    )
                cost_counter += 1

combined_costs_list: list[Cost] = st.session_state["activity_list"] + st.session_state["cost_list"]  # ty:ignore[invalid-assignment]
total_cost: float = compute_costs(combined_costs_list)
total_hours: float = compute_hours(st.session_state["activity_list"])

with main_right:
    k1, k2, k3 = st.columns(3)
    k1.metric("Estimated total cost", format_usd(total_cost))
    k2.metric("Estimated labor hours", f"{total_hours:.0f} h")
    k3.metric("Estimated direct costs", format_usd(compute_costs(st.session_state["cost_list"])))  # ty:ignore[invalid-argument-type]

    phase_df = pd.DataFrame(
        {
            "Phase": [
                "Incubation",
                "Data collection and analysis",
                "Writing",
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
        phase_df, names="Phase", values="Cost (USD)", title="Cost breakdown"
    )
    st.plotly_chart(pie, width="stretch")

    labour_df = pd.DataFrame(
        {
            "Activity": [activity.name for activity in st.session_state["activity_list"]],
            "Cost (USD)": [activity.get_total_cost() for activity in st.session_state["activity_list"]],
        }
    )

    waterfall = px.bar(
        labour_df,
        x="Activity",
        y="Cost (USD)",
        title="Cost of Labor Activities",
        text_auto=True,
    )
    st.plotly_chart(waterfall, width="stretch")