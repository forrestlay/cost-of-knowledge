import math
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Scholarly Paper Cost Simulator", layout="wide")

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

    labour_hours = base_ra_hours * scale * author_factor * months_factor * revision_factor
    peer_hours = peer_review_hours * scale * revision_factor
    labour_cost = labour_hours * ra_hourly_rate
    peer_review_cost = peer_hours * ra_hourly_rate
    infrastructure_cost = infra_library_cost * scale
    editing_design_cost = (editing_cost + design_cost) * (0.92 if journal_tier == "C" else 1.00)
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


def format_aud(x: float) -> str:
    return f"A${x:,.0f}"


st.title("Scholarly Paper Cost Simulator")
st.caption("Interactive Streamlit simulator for C, B, A and A* paper cost scenarios")

with st.expander("About the assumptions", expanded=False):
    st.write(
        "This simulator starts from a budget structure similar to the uploaded proposal: research assistance at A$73.45/hour, 35% university overhead, and dissemination / support components such as editing, design, and in-kind support."
    )
    st.write(
        "Use the controls to change paper characteristics and instantly see how the cost estimate moves."
    )

single_tab, portfolio_tab, data_tab = st.tabs(["Single paper simulator", "Portfolio simulator", "Data explorer"])

with single_tab:
    st.subheader("Single paper simulator")
    left, right = st.columns([1, 2])

    with left:
        journal_tier = st.selectbox("Journal tier", list(TIER_MULTIPLIERS.keys()), index=3)
        discipline = st.selectbox("Discipline", list(DISCIPLINE_MULTIPLIERS.keys()), index=0)
        region = st.selectbox("Research team region", list(REGION_MULTIPLIERS.keys()), index=0)
        methodology = st.selectbox("Methodology", list(METHOD_MULTIPLIERS.keys()), index=1)
        oa_model = st.selectbox("Publishing model", list(OA_MODELS.keys()), index=0)
        language_level = st.select_slider("Language / writing complexity", options=list(LANGUAGE_COMPLEXITY.keys()), value="Moderate")
        author_count = st.slider("Number of authors", 1, 8, 3)
        project_months = st.slider("Project duration (months)", 3, 24, 9)
        revision_rounds = st.slider("Revision rounds", 0, 4, 2)

        st.markdown("**Cost driver assumptions**")
        ra_hourly_rate = st.number_input("RA hourly rate (AUD)", min_value=30.0, max_value=150.0, value=73.45, step=1.0)
        base_ra_hours = st.slider("Base RA hours", 80, 800, 420, step=10)
        peer_review_hours = st.slider("Peer review / editorial labour hours", 5, 120, 24, step=1)
        infra_library_cost = st.number_input("Infrastructure & library cost (AUD)", min_value=0.0, max_value=20000.0, value=4500.0, step=250.0)
        editing_cost = st.number_input("Editing cost (AUD)", min_value=0.0, max_value=10000.0, value=1674.0, step=100.0)
        design_cost = st.number_input("Design / formatting cost (AUD)", min_value=0.0, max_value=10000.0, value=2000.0, step=100.0)
        conference_cost = st.number_input("Dissemination / conference cost (AUD)", min_value=0.0, max_value=15000.0, value=0.0, step=250.0)
        overhead_rate = st.slider("University overhead rate", 0.0, 0.6, 0.35, 0.01)
        in_kind_support = st.number_input("In-kind support (AUD)", min_value=0.0, max_value=20000.0, value=5000.0, step=250.0)

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

    with right:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Estimated total cost", format_aud(result["total_cost_aud"]))
        k2.metric("Direct cash cost", format_aud(result["total_cost_aud"] - result["in_kind_support_cost_aud"]))
        k3.metric("Labour hours", f"{result['labour_hours']:.0f} h")
        k4.metric("Overhead", format_aud(result["university_overhead_cost_aud"]))

        if result["total_cost_aud"] > 100000:
            st.error("This scenario is above A$100,000. Reduce one or more cost drivers to stay under the cap.")
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
        pie = px.pie(comp_df, names="Component", values="Cost (AUD)", title="Cost breakdown")
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

with portfolio_tab:
    st.subheader("Portfolio simulator")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        n_c = st.number_input("Number of C papers", 0, 50, 3)
    with c2:
        n_b = st.number_input("Number of B papers", 0, 50, 4)
    with c3:
        n_a = st.number_input("Number of A papers", 0, 50, 5)
    with c4:
        n_astar = st.number_input("Number of A* papers", 0, 50, 3)

    portfolio_seed = st.number_input("Simulation seed", 0, 9999, 42)
    rng = np.random.default_rng(int(portfolio_seed))

    tiers = (["C"] * int(n_c)) + (["B"] * int(n_b)) + (["A"] * int(n_a)) + (["A*"] * int(n_astar))
    rows = []
    for i, tier in enumerate(tiers, start=1):
        row = compute_costs(
            journal_tier=tier,
            discipline=rng.choice(list(DISCIPLINE_MULTIPLIERS.keys())),
            region=rng.choice(list(REGION_MULTIPLIERS.keys())),
            methodology=rng.choice(list(METHOD_MULTIPLIERS.keys())),
            author_count=int(rng.integers(1, 7)),
            project_months=int(rng.integers(6, 19)),
            revision_rounds=int(rng.integers(1, 4)),
            ra_hourly_rate=float(np.round(rng.normal(73.45, 4.5), 2)),
            base_ra_hours=float(rng.integers(250, 560)),
            peer_review_hours=float(rng.integers(12, 36)),
            infra_library_cost=float(rng.integers(2500, 6500)),
            editing_cost=float(rng.integers(1200, 2600)),
            design_cost=float(rng.integers(900, 2400)),
            overhead_rate=float(np.clip(rng.normal(0.35, 0.03), 0.20, 0.45)),
            in_kind_support=float(rng.integers(2500, 7000)),
            oa_model=rng.choice(list(OA_MODELS.keys()), p=[0.55, 0.25, 0.20]),
            language_level=rng.choice(list(LANGUAGE_COMPLEXITY.keys()), p=[0.25, 0.55, 0.20]),
            conference_cost=float(rng.choice([0, 0, 1500, 2500, 3500])),
        )
        if row["total_cost_aud"] > 100000:
            ratio = 99500 / row["total_cost_aud"]
            for key in [
                "labour_cost_aud",
                "peer_review_cost_aud",
                "infrastructure_library_cost_aud",
                "editing_design_cost_aud",
                "open_access_cost_aud",
                "conference_cost_aud",
                "university_overhead_cost_aud",
                "in_kind_support_cost_aud",
                "total_cost_aud",
            ]:
                row[key] *= ratio
        row["paper_id"] = f"P{i:03d}"
        rows.append(row)

    portfolio_df = pd.DataFrame(rows)

    if portfolio_df.empty:
        st.info("Add at least one paper to simulate the portfolio.")
    else:
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Portfolio cost", format_aud(portfolio_df["total_cost_aud"].sum()))
        p2.metric("Average per paper", format_aud(portfolio_df["total_cost_aud"].mean()))
        p3.metric("Highest paper cost", format_aud(portfolio_df["total_cost_aud"].max()))
        p4.metric("Paper count", f"{len(portfolio_df)}")

        by_tier = portfolio_df.groupby("journal_tier", as_index=False)["total_cost_aud"].mean()
        st.plotly_chart(
            px.bar(by_tier, x="journal_tier", y="total_cost_aud", title="Average cost by tier", text_auto=True),
            width="stretch",
        )

        scatter = px.scatter(
            portfolio_df,
            x="project_months",
            y="total_cost_aud",
            color="journal_tier",
            size="author_count",
            hover_name="paper_id",
            title="Project months vs total cost",
        )
        st.plotly_chart(scatter, width="stretch")

        st.dataframe(
            portfolio_df[[
                "paper_id", "journal_tier", "discipline", "region", "methodology", "author_count",
                "project_months", "total_cost_aud"
            ]].sort_values(["journal_tier", "total_cost_aud"], ascending=[True, False]),
            width="stretch",
            hide_index=True,
        )

        csv_bytes = portfolio_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download simulated portfolio CSV",
            data=csv_bytes,
            file_name="streamlit_simulated_paper_costs.csv",
            mime="text/csv",
        )

with data_tab:
    st.subheader("Data explorer")
    if DEFAULT_CSV.exists():
        df = pd.read_csv(DEFAULT_CSV)
        st.write("Loaded default dataset:", str(DEFAULT_CSV.name))
    else:
        df = pd.DataFrame()
        st.info("Default CSV not found next to the app. You can still use the simulator tabs above.")

    uploaded = st.file_uploader("Or upload your own CSV", type=["csv"])
    if uploaded is not None:
        df = pd.read_csv(uploaded)
        st.success("Uploaded CSV loaded.")

    if not df.empty:
        st.dataframe(df, width="stretch")
        if {"journal_tier", "total_cost_aud"}.issubset(df.columns):
            st.plotly_chart(
                px.box(df, x="journal_tier", y="total_cost_aud", color="journal_tier", title="Cost distribution by journal tier"),
                width="stretch",
            )
        if {"discipline", "total_cost_aud"}.issubset(df.columns):
            disc = df[["discipline", "total_cost_aud"]].groupby("discipline", as_index=False).mean().sort_values(by="total_cost_aud", ascending=False)
            st.plotly_chart(
                px.bar(disc, x="discipline", y="total_cost_aud", title="Average cost by discipline", text_auto=True),
                width="stretch",
            )
    else:
        st.info("No CSV loaded in the data explorer.")
