from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from models import Person, PersonType

st.set_page_config(page_title="Cost of Knowledge Calculator", layout="wide")

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CSV = BASE_DIR / "simulated_paper_costs_by_tier.csv"

TIER_MULTIPLIERS = {"C": 0.72, "B": 0.84, "A": 0.94, "A*": 1.00}
DISCIPLINE_MULTIPLIERS = {
    "Accounting & Finance": 1.00,
    "Management": 0.96,
    "Economics": 1.03,
    "Information Systems": 0.99,
    "Interdisciplinary": 1.06,
}
REGION_MULTIPLIERS = {
    "Australia/NZ": 1.00,
    "North America": 1.08,
    "Europe": 1.04,
    "Asia": 0.92,
    "Global Team": 1.06,
}
METHOD_MULTIPLIERS = {
    "Conceptual": 0.82,
    "Archival/Empirical": 1.00,
    "Survey": 0.96,
    "Experiment": 1.08,
    "Qualitative": 1.02,
    "Mixed Methods": 1.12,
}
OA_MODELS = {
    "Subscription / closed": 0,
    "Hybrid open access": 3500,
    "Gold open access": 5200,
}
LANGUAGE_COMPLEXITY = {"Low": 0.96, "Moderate": 1.00, "High": 1.08}


def compute_costs(
    journal_tier: str,
    discipline: str,
    region: str,
    methodology: str,
    author_count: int,
    project_months: int,
    revision_rounds: int,
    ra_hourly_rate: float,
    base_ra_hours: float,
    peer_review_hours: float,
    infra_library_cost: float,
    editing_cost: float,
    design_cost: float,
    overhead_rate: float,
    in_kind_support: float,
    oa_model: str,
    language_level: str,
    conference_cost: float,
):
    scale = (
        TIER_MULTIPLIERS[journal_tier]
        * DISCIPLINE_MULTIPLIERS[discipline]
        * REGION_MULTIPLIERS[region]
        * METHOD_MULTIPLIERS[methodology]
        * LANGUAGE_COMPLEXITY[language_level]
    )

    author_factor = 1 + max(author_count - 2, 0) * 0.045
    months_factor = 1 + max(project_months - 9, 0) * 0.018
    revision_factor = 1 + max(revision_rounds - 1, 0) * 0.07

    labour_hours = (
        base_ra_hours * scale * author_factor * months_factor * revision_factor
    )
    peer_hours = peer_review_hours * scale * revision_factor
    labour_cost = labour_hours * ra_hourly_rate
    peer_review_cost = peer_hours * ra_hourly_rate
    infrastructure_cost = infra_library_cost * scale
    editing_design_cost = (editing_cost + design_cost) * (
        0.92 if journal_tier == "C" else 1.00
    )
    open_access_cost = OA_MODELS[oa_model]
    direct_cash = (
        labour_cost
        + peer_review_cost
        + infrastructure_cost
        + editing_design_cost
        + open_access_cost
        + conference_cost
    )
    overhead_cost = direct_cash * overhead_rate
    total_cost = direct_cash + overhead_cost + in_kind_support

    return {
        "journal_tier": journal_tier,
        "discipline": discipline,
        "region": region,
        "methodology": methodology,
        "author_count": author_count,
        "project_months": project_months,
        "revision_rounds": revision_rounds,
        "ra_hourly_rate": ra_hourly_rate,
        "labour_hours": labour_hours,
        "peer_review_hours": peer_hours,
        "labour_cost_aud": labour_cost,
        "peer_review_cost_aud": peer_review_cost,
        "infrastructure_library_cost_aud": infrastructure_cost,
        "editing_design_cost_aud": editing_design_cost,
        "open_access_cost_aud": open_access_cost,
        "conference_cost_aud": conference_cost,
        "university_overhead_cost_aud": overhead_cost,
        "in_kind_support_cost_aud": in_kind_support,
        "total_cost_aud": total_cost,
    }


def format_usd(x: int | float) -> str:
    return f"US${x:,.0f}"


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

st.subheader("Study Team")
st.markdown("""
            Fill in the details of the people on your team who contributed to the preparation of your journal article.
            Your salary will be used to calculate the cost of labour for most of the steps involved in the journal
            preparation process.

            Alternatively, if your team has many people, you may add the average salary of each level of academic in
            your team (for example, add one person representing all Professors on your team, another person representing
            all lecturers on your team, etc.).
            """)

if "people" not in st.session_state:
    default_person: Person = Person(
        name="Primary Investigator",
        person_type=PersonType.RESEARCH_TEAM,
        hourly_rate=85,
    )
    st.session_state["people"]: list[Person] = [default_person]

if "study_team_finalised" not in st.session_state:
    st.session_state[
        "study_team_finalised"
    ]: bool = False  # Expands study team expander until team is finalised.


def add_person():
    st.session_state["people"].append(
        Person(name="New person", person_type=PersonType.RESEARCH_TEAM, hourly_rate=85)
    )


def delete_person(person: Person):
    st.session_state["people"].remove(person)


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

with st.expander(
    "Modify your study team", expanded=not st.session_state["study_team_finalised"]
):
    for person in st.session_state["people"]:
        with st.container(border=True):
            person.name: str = st.text_input("Name", value=person.name)
            person.hourly_rate: int | float = st.number_input(
                "Hourly wage", value=person.hourly_rate
            )
            with st.container(horizontal=True, horizontal_alignment="left"):
                if st.button(
                    "Calculate hourly wage using salary",
                    key=f"calculate-hourly-wage-{person_counter}",
                ):
                    calculate_hourly_rate(person)
                if person_counter > 1:
                    st.button(
                        f"Delete {person.name}",
                        key=f"delete-person-{person_counter}",
                        icon=":material/delete:",
                        on_click=delete_person,
                        args=[person],
                    )
        person_counter += 1

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
            on_click=team_finalised,
        )

# -----------------------------------------------
# Calculator
# -----------------------------------------------

st.subheader("Calculator")

main_left, main_right = st.columns([1, 2])

with main_left:
    journal_tier = st.selectbox("Journal tier", list(TIER_MULTIPLIERS.keys()), index=3)
    discipline = st.selectbox(
        "Discipline", list(DISCIPLINE_MULTIPLIERS.keys()), index=0
    )
    region = st.selectbox(
        "Research team region", list(REGION_MULTIPLIERS.keys()), index=0
    )
    methodology = st.selectbox("Methodology", list(METHOD_MULTIPLIERS.keys()), index=1)
    oa_model = st.selectbox("Publishing model", list(OA_MODELS.keys()), index=0)
    language_level = st.select_slider(
        "Language / writing complexity",
        options=list(LANGUAGE_COMPLEXITY.keys()),
        value="Moderate",
    )
    author_count = st.slider("Number of authors", 1, 8, 3)
    project_months = st.slider("Project duration (months)", 3, 24, 9)
    revision_rounds = st.slider("Revision rounds", 0, 4, 2)

    st.markdown("**Cost driver assumptions**")
    ra_hourly_rate = st.number_input(
        "RA hourly rate (AUD)", min_value=30.0, max_value=150.0, value=73.45, step=1.0
    )
    base_ra_hours = st.slider("Base RA hours", 80, 800, 420, step=10)
    peer_review_hours = st.slider(
        "Peer review / editorial labour hours", 5, 120, 24, step=1
    )
    infra_library_cost = st.number_input(
        "Infrastructure & library cost (AUD)",
        min_value=0.0,
        max_value=20000.0,
        value=4500.0,
        step=250.0,
    )
    editing_cost = st.number_input(
        "Editing cost (AUD)", min_value=0.0, max_value=10000.0, value=1674.0, step=100.0
    )
    design_cost = st.number_input(
        "Design / formatting cost (AUD)",
        min_value=0.0,
        max_value=10000.0,
        value=2000.0,
        step=100.0,
    )
    conference_cost = st.number_input(
        "Dissemination / conference cost (AUD)",
        min_value=0.0,
        max_value=15000.0,
        value=0.0,
        step=250.0,
    )
    overhead_rate = st.slider("University overhead rate", 0.0, 0.6, 0.35, 0.01)
    in_kind_support = st.number_input(
        "In-kind support (AUD)",
        min_value=0.0,
        max_value=20000.0,
        value=5000.0,
        step=250.0,
    )

result = compute_costs(
    journal_tier,
    discipline,
    region,
    methodology,
    author_count,
    project_months,
    revision_rounds,
    ra_hourly_rate,
    base_ra_hours,
    peer_review_hours,
    infra_library_cost,
    editing_cost,
    design_cost,
    overhead_rate,
    in_kind_support,
    oa_model,
    language_level,
    conference_cost,
)

with main_right:
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Estimated total cost", format_usd(result["total_cost_aud"]))
    k2.metric(
        "Direct cash cost",
        format_usd(result["total_cost_aud"] - result["in_kind_support_cost_aud"]),
    )
    k3.metric("Labour hours", f"{result['labour_hours']:.0f} h")
    k4.metric("Overhead", format_usd(result["university_overhead_cost_aud"]))

    if result["total_cost_aud"] > 100000:
        st.error(
            "This scenario is above A$100,000. Reduce one or more cost drivers to stay under the cap."
        )
    else:
        st.success("This scenario is within the A$100,000 cap.")

    comp_df = pd.DataFrame(
        {
            "Component": [
                "Labour",
                "Peer review",
                "Infrastructure & library",
                "Editing & design",
                "Open access",
                "Conference / dissemination",
                "University overhead",
                "In-kind support",
            ],
            "Cost (AUD)": [
                result["labour_cost_aud"],
                result["peer_review_cost_aud"],
                result["infrastructure_library_cost_aud"],
                result["editing_design_cost_aud"],
                result["open_access_cost_aud"],
                result["conference_cost_aud"],
                result["university_overhead_cost_aud"],
                result["in_kind_support_cost_aud"],
            ],
        }
    )
    pie = px.pie(
        comp_df, names="Component", values="Cost (AUD)", title="Cost breakdown"
    )
    st.plotly_chart(pie, width="stretch")

    waterfall = px.bar(
        comp_df,
        x="Component",
        y="Cost (AUD)",
        title="Component values",
        text_auto=True,
    )
    st.plotly_chart(waterfall, width="stretch")

    detail_df = pd.DataFrame(
        [
            ["Journal tier", journal_tier],
            ["Discipline", discipline],
            ["Region", region],
            ["Methodology", methodology],
            ["Publishing model", oa_model],
            ["Language complexity", language_level],
            ["Authors", author_count],
            ["Project months", project_months],
            ["Revision rounds", revision_rounds],
            ["RA hourly rate", f"A${ra_hourly_rate:,.2f}"],
        ],
        columns=["Field", "Value"],
    )
    st.dataframe(detail_df, width="stretch", hide_index=True)
