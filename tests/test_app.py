"""End-to-end tests importing a serialised calculator into the running Streamlit app."""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from pathlib import Path
from typing import Any

from streamlit.runtime.state.common import TESTING_KEY
from streamlit.testing.v1 import AppTest

from src.calculator_state import CalculatorState, SessionStateKey
from src.currency_rates import convert_currency
from src.models import Activity, Person, PersonType
from src.reference_data import ROLES

MAIN: str = str(Path(__file__).parent.parent / "main.py")


class AppTestSessionState(MutableMapping[SessionStateKey, Any]):
    """Adapts AppTest's session state, which cannot be iterated, to the mapping st.session_state provides in an app."""

    def __init__(self, at: AppTest) -> None:
        self._state = at.session_state

    def __getitem__(self, key: SessionStateKey) -> Any:
        return self._state[str(key)]

    def __setitem__(self, key: SessionStateKey, value: Any) -> None:
        self._state[str(key)] = value

    def __delitem__(self, key: SessionStateKey) -> None:
        del self._state[str(key)]

    def __iter__(self) -> Iterator[SessionStateKey]:
        return iter(list(self._state.filtered_state))

    def __len__(self) -> int:
        return len(self._state.filtered_state)


def metric_values(at: AppTest) -> list[str]:
    return [metric.value for metric in at.metric]


def run(at: AppTest) -> None:
    """Runs the app, working around main.person_option_display reading st.session_state.

    AppTest calls a selectbox's format_func outside of a script run, where st.session_state is unavailable, so the
    "Assigned person" selectboxes cannot format their value. Swap in an equivalent that reads AppTest's session state.
    """
    if TESTING_KEY in at.session_state and "people" in at.session_state:
        people: dict[str, Person] = at.session_state["people"]
        for selectbox in at.selectbox:
            if selectbox.key and selectbox.key.startswith("activity-person-"):
                at.session_state[TESTING_KEY][selectbox.id] = lambda key: people[key].label
    at.run()
    assert not at.exception


def run_app() -> AppTest:
    at: AppTest = AppTest.from_file(MAIN, default_timeout=30)
    run(at)
    return at


def test_defaults_unchanged() -> None:
    at: AppTest = run_app()
    assert metric_values(at) == ["$0 (USD)", "0 h", "$0 (USD)"]
    assert at.selectbox(key="user_country_select").value == "us"
    assert at.selectbox(key="activity-name-1").value == "Incubation (Overall Total)"
    assert at.slider(key="review-rounds").value == 0
    assert at.slider(key="journal-submissions").value == 0


def load_alam_defaults(at: AppTest) -> None:
    at.button(key="load-alam-defaults").click()
    run(at)


def test_load_alam_defaults() -> None:
    at: AppTest = run_app()
    load_alam_defaults(at)
    assert metric_values(at) == ["$71,518 (USD)", "798 h", "$3,646 (USD)"]
    # The loaded hours and costs must survive later reruns, not only the one straight after loading.
    run(at)
    run(at)
    assert metric_values(at) == ["$71,518 (USD)", "798 h", "$3,646 (USD)"]
    assert at.number_input(key="activity-hours-1").value == 55.0
    assert at.number_input(key="directcost-cost-1").value == 246.0
    assert at.selectbox(key="activity-name-1").value == "Ideation and conception"
    assert at.slider(key="review-rounds").value == 3


def test_editing_people_keeps_loaded_activities() -> None:
    at: AppTest = run_app()
    load_alam_defaults(at)
    at.number_input(key="person-rate-1").set_value(100)
    run(at)
    at.button(key="add-person").click()
    run(at)
    assert at.selectbox(key="activity-name-1").value == "Ideation and conception"
    assert at.number_input(key="activity-hours-1").value == 55.0
    assert at.selectbox(key="activity-person-1").value == "1"
    assert at.selectbox(key="directcost-name-1").value == "Participant incentivization"
    assert not at.warning


def test_load_alam_defaults_keeps_country_and_rates() -> None:
    at: AppTest = run_app()
    at.selectbox(key="user_country_select").set_value("au")
    run(at)
    at.number_input(key="person-rate-1").set_value(100)
    run(at)
    load_alam_defaults(at)
    cost: float | None = convert_currency(246, "USD", "AUD")
    assert cost is not None
    assert at.selectbox(key="user_country_select").value == "au"
    assert at.number_input(key="person-rate-1").value == 100
    assert at.number_input(key="directcost-cost-1").value == round(cost, 2)


def test_session_state_round_trip() -> None:
    at: AppTest = run_app()
    state: CalculatorState = CalculatorState.from_session_state(AppTestSessionState(at))
    assert CalculatorState.from_json(state.to_json()) == CalculatorState.default()


def test_import_replaces_edited_widgets() -> None:
    at: AppTest = run_app()
    load_alam_defaults(at)
    # Edit widgets so they hold their own state, which the import must override.
    at.number_input(key="activity-hours-1").set_value(1000.0)
    at.number_input(key="person-rate-1").set_value(10)
    at.slider(key="review-rounds").set_value(10)
    run(at)
    assert metric_values(at)[1] == "1758 h"

    imported: CalculatorState = CalculatorState.default().with_default_costs()
    imported.people["1"].hourly_rate = 50.5
    second: Person = Person("2", PersonType.RESEARCH_TEAM, 40, "research_scientist")
    imported.people["2"] = second
    imported.activities.append(Activity("Data collection", second, "data", 100, 11, 4))
    imported.peer_review.review_rounds = 2
    restored: CalculatorState = CalculatorState.from_json(imported.to_json())

    restored.apply_to_session_state(AppTestSessionState(at))
    # Rerun without re-sending the values of the widgets rendered before the import, as happens when the state is
    # applied from a widget callback in the running app. at.run() would send the stale, now deleted, widget values.
    at._run()
    assert not at.exception

    assert metric_values(at) == [
        f"${restored.total_cost():,.0f} (USD)",
        f"{restored.total_hours():.0f} h",
        "$3,646 (USD)",
    ]
    assert at.number_input(key="activity-hours-1").value == 55.0
    assert at.number_input(key="person-rate-1").value == 50.5
    assert at.number_input(key="person-rate-2").value == 40
    assert at.selectbox(key="person-role-1").value is None
    assert at.selectbox(key="person-role-2").value == "research_scientist"
    assert at.slider(key="review-rounds").value == 2
    assert at.selectbox(key="user_country_select").value == "us"
    assert CalculatorState.from_session_state(AppTestSessionState(at)) == restored


def test_choosing_role_fills_hourly_rate() -> None:
    at: AppTest = run_app()
    at.selectbox(key="user_country_select").set_value("au")
    run(at)
    role_select = at.selectbox(key="person-role-1")
    assert "Assistant Professor (US) / Lecturer (Australia)" in role_select.options

    role_select.set_value("assistant_professor")
    run(at)
    rate: float | None = convert_currency(ROLES["assistant_professor"].hourly_rate_usd, "USD", "AUD")
    assert rate is not None
    assert at.number_input(key="person-rate-1").value == round(rate, 2)
    assert at.session_state["people"]["1"].role == "assistant_professor"
    assert at.session_state["people"]["1"].hourly_rate == round(rate, 2)


def test_choosing_activity_fills_default_hours() -> None:
    at: AppTest = run_app()
    at.selectbox(key="activity-name-1").set_value("Grant applications")
    run(at)
    assert at.number_input(key="activity-hours-1").value == 171.0
    assert at.session_state["activity_list"][0].hours == 171.0

    # AppTest cannot enter a custom name (accept_new_options), so check a preset with a default of 0 hours instead.
    at.selectbox(key="activity-name-1").set_value("Other")
    run(at)
    assert at.number_input(key="activity-hours-1").value == 0.0
    assert at.session_state["activity_list"][0].name == "Other"


def test_choosing_direct_cost_fills_default_cost() -> None:
    at: AppTest = run_app()
    at.selectbox(key="user_country_select").set_value("au")
    run(at)
    load_alam_defaults(at)
    at.selectbox(key="directcost-name-1").set_value("Software")
    run(at)
    assert at.number_input(key="directcost-cost-1").value == 0.0

    at.selectbox(key="directcost-name-1").set_value("Participant incentivization")
    run(at)
    cost: float | None = convert_currency(246, "USD", "AUD")
    assert cost is not None
    assert at.number_input(key="directcost-cost-1").value == round(cost, 2)
    assert at.session_state["cost_list"][0].cost == round(cost, 2)


def test_field_of_research_select() -> None:
    at: AppTest = run_app()
    field_select = next(box for box in at.selectbox if box.label.startswith("Field of research"))
    assert field_select.value == "3501"
    assert field_select.options[0] == "Agricultural, veterinary and food sciences/Agricultural biotechnology"

    # A broad field name saved before Field of Research codes were used stays selected.
    imported: CalculatorState = CalculatorState.default()
    imported.project_field = "Social sciences"
    imported.apply_to_session_state(AppTestSessionState(at))
    at._run()
    assert not at.exception
    field_select = next(box for box in at.selectbox if box.label.startswith("Field of research"))
    assert field_select.value == "Social sciences"
    assert field_select.options[0] == "Social sciences"
