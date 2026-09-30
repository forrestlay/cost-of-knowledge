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


def submit_researcher_form(at: AppTest) -> None:
    next(button for button in at.button if button.label == "Add researcher").click()
    run(at)


def add_researcher(at: AppTest, role: str = "assistant_professor", quantity: int = 1) -> Person:
    """Adds a researcher with the given role through the form, and returns them."""
    at.selectbox(key="add-person-role").set_value(role)
    run(at)
    at.number_input(key="add-person-quantity").set_value(quantity)
    submit_researcher_form(at)
    return list(at.session_state["people"].values())[-1]


def add_researcher_at_rate(at: AppTest, hourly_rate: float = 85.0) -> Person:
    """Adds a researcher, then sets their hourly rate directly so that totals are simple to calculate."""
    person: Person = add_researcher(at)
    person.hourly_rate = hourly_rate
    return person


def default_with_researcher() -> CalculatorState:
    state: CalculatorState = CalculatorState.default()
    state.people["1"] = Person("1", PersonType.RESEARCH_TEAM, 85)
    return state


def test_defaults_unchanged() -> None:
    at: AppTest = run_app()
    assert metric_values(at) == ["$0 (USD)", "0 h", "$0 (USD)"]
    assert at.selectbox(key="user_country_select").value is None
    field_select = next(box for box in at.selectbox if box.label.startswith("Field of research"))
    assert field_select.value is None
    assert at.session_state["people"] == {}
    assert at.selectbox(key="add-person-role").value is None
    assert at.slider(key="review-rounds").value == 0
    assert at.slider(key="journal-submissions").value == 0
    assert not any(box.key == "activity-name-1" for box in at.selectbox)
    assert all(button.disabled for button in at.button if button.key and button.key.startswith("add-activity-"))
    assert at.button(key="load-alam-defaults").disabled


def test_first_researcher_adds_starting_activities() -> None:
    at: AppTest = run_app()
    person: Person = add_researcher(at)
    assert person.label == "Researcher 1"
    assert at.selectbox(key="activity-name-1").value == "Incubation (Overall Total)"
    # Peer review and journal editorial work take the first two activity keys.
    assert at.selectbox(key="activity-person-3").value == "1"
    # The form is emptied ready for the next researcher.
    assert at.selectbox(key="add-person-role").value is None
    assert not at.button(key="load-alam-defaults").disabled

    # Later researchers do not add activities.
    add_researcher(at)
    assert len([a for a in at.session_state["activity_list"] if isinstance(a, Activity)]) == 3


def load_alam_defaults(at: AppTest) -> None:
    at.button(key="load-alam-defaults").click()
    run(at)


def test_load_alam_defaults() -> None:
    at: AppTest = run_app()
    add_researcher_at_rate(at)
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
    add_researcher_at_rate(at)
    load_alam_defaults(at)
    add_researcher(at, "lecturer")
    assert at.selectbox(key="activity-name-1").value == "Ideation and conception"
    assert at.number_input(key="activity-hours-1").value == 55.0
    assert at.selectbox(key="activity-person-1").value == "1"
    assert at.selectbox(key="directcost-name-1").value == "Participant incentivization"
    assert not at.warning


def test_load_alam_defaults_keeps_country_and_rates() -> None:
    at: AppTest = run_app()
    at.selectbox(key="user_country_select").set_value("au")
    run(at)
    add_researcher_at_rate(at, 100)
    load_alam_defaults(at)
    cost: float | None = convert_currency(246, "USD", "AUD")
    assert cost is not None
    assert at.selectbox(key="user_country_select").value == "au"
    assert at.session_state["people"]["1"].hourly_rate == 100
    assert at.number_input(key="directcost-cost-1").value == round(cost, 2)


def test_session_state_round_trip() -> None:
    at: AppTest = run_app()
    state: CalculatorState = CalculatorState.from_session_state(AppTestSessionState(at))
    assert CalculatorState.from_json(state.to_json()) == CalculatorState.default()


def test_import_replaces_edited_widgets() -> None:
    at: AppTest = run_app()
    add_researcher_at_rate(at)
    load_alam_defaults(at)
    # Edit widgets so they hold their own state, which the import must override.
    at.number_input(key="activity-hours-1").set_value(1000.0)
    at.slider(key="review-rounds").set_value(10)
    run(at)
    assert metric_values(at)[1] == "1758 h"

    imported: CalculatorState = default_with_researcher().with_default_costs()
    imported.people["1"].hourly_rate = 50.5
    second: Person = Person("2", PersonType.RESEARCH_TEAM, 40, "research_scientist", 2)
    imported.people["2"] = second
    imported.activities.append(Activity("Data collection", second, "data", 100, 11, 4))
    imported.peer_review.review_rounds = 2
    imported.user_country = "us"
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
    assert at.slider(key="review-rounds").value == 2
    assert at.selectbox(key="user_country_select").value == "us"
    assert CalculatorState.from_session_state(AppTestSessionState(at)) == restored


def test_adding_researcher_with_role() -> None:
    at: AppTest = run_app()
    at.selectbox(key="user_country_select").set_value("au")
    run(at)
    role_select = at.selectbox(key="add-person-role")
    assert "Assistant Professor (Australia equivalent: Senior Lecturer)" in role_select.options
    assert role_select.options[-1] == "Enter a salary manually"

    person: Person = add_researcher(at, quantity=3)
    rate: float | None = convert_currency(ROLES["assistant_professor"].hourly_rate_usd * 1.4, "USD", "AUD")
    assert rate is not None
    assert person.role == "assistant_professor"
    assert person.hourly_rate == round(rate, 2)
    assert person.quantity == 3


def test_adding_researcher_with_salary() -> None:
    at: AppTest = run_app()
    at.selectbox(key="add-person-role").set_value("manual_salary")
    run(at)
    at.number_input(key="add-person-salary").set_value(104000)
    at.number_input(key="add-person-quantity").set_value(2)
    submit_researcher_form(at)
    person: Person = at.session_state["people"]["1"]
    # US$104,000 over 52 weeks of 40 hours is US$50 an hour, plus the default 40% indirect cost rate.
    assert person.role is None
    assert person.hourly_rate == 70
    assert person.quantity == 2


def test_editing_researcher() -> None:
    at: AppTest = run_app()
    at.selectbox(key="add-person-role").set_value("manual_salary")
    run(at)
    at.number_input(key="add-person-salary").set_value(104000)
    submit_researcher_form(at)

    at.button(key="edit-person-button-1").click()
    run(at)
    # The dialog starts from the researcher's details.
    assert at.selectbox(key="edit-person-1-role").value == "manual_salary"
    assert at.number_input(key="edit-person-1-quantity").value == 1
    at.number_input(key="edit-person-1-salary").set_value(52000)
    at.number_input(key="edit-person-1-quantity").set_value(4)
    next(button for button in at.button if button.label == "Save changes").click()
    run(at)
    person: Person = at.session_state["people"]["1"]
    assert (person.role, person.hourly_rate, person.quantity) == (None, 35, 4)


def test_adding_researcher_without_salary_is_rejected() -> None:
    at: AppTest = run_app()
    at.selectbox(key="add-person-role").set_value("manual_salary")
    run(at)
    submit_researcher_form(at)
    assert at.session_state["people"] == {}


def test_quantity_does_not_change_totals() -> None:
    at: AppTest = run_app()
    add_researcher_at_rate(at)
    load_alam_defaults(at)
    at.session_state["people"]["1"].quantity = 2
    run(at)
    assert metric_values(at) == ["$71,518 (USD)", "798 h", "$3,646 (USD)"]


def test_deleting_researcher_reassigns_activities() -> None:
    at: AppTest = run_app()
    add_researcher(at)
    add_researcher(at, "lecturer")
    at.session_state["activity_list"][2].person = at.session_state["people"]["2"]
    at.button(key="delete-person-2").click()
    run(at)
    assert list(at.session_state["people"]) == ["1"]
    assert {a.person.unique_key for a in at.session_state["activity_list"] if isinstance(a, Activity)} == {"1"}

    # Deleting the last researcher deletes the activities that were assigned to them.
    at.button(key="delete-person-1").click()
    run(at)
    assert at.session_state["people"] == {}
    assert not any(isinstance(a, Activity) for a in at.session_state["activity_list"])


def test_choosing_activity_fills_default_hours() -> None:
    at: AppTest = run_app()
    add_researcher(at)
    at.selectbox(key="activity-name-1").set_value("Grant applications")
    run(at)
    assert at.number_input(key="activity-hours-3").value == 171.0
    assert next(a for a in at.session_state["activity_list"] if isinstance(a, Activity)).hours == 171.0

    # AppTest cannot enter a custom name (accept_new_options), so check a preset with a default of 0 hours instead.
    at.selectbox(key="activity-name-1").set_value("Other")
    run(at)
    assert at.number_input(key="activity-hours-3").value == 0.0
    assert next(a for a in at.session_state["activity_list"] if isinstance(a, Activity)).name == "Other"


def test_choosing_direct_cost_fills_default_cost() -> None:
    at: AppTest = run_app()
    add_researcher(at)
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
