"""End-to-end tests importing a serialised calculator into the running Streamlit app."""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from pathlib import Path
from typing import Any

from streamlit.runtime.state.common import TESTING_KEY
from streamlit.testing.v1 import AppTest

from src.calculator_state import OVERALL_TOTAL_PHASES, CalculatorState, SessionStateKey
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
    # The results are hidden until the cost is calculated, so show them from the first run.
    if "show_results" not in at.session_state:
        at.session_state["show_results"] = True
    at.run()
    assert not at.exception


def run_app(mode: str = "detailed") -> AppTest:
    """Runs the app in the given calculator mode. Most tests exercise the detailed calculator, so it is the default."""
    at: AppTest = AppTest.from_file(MAIN, default_timeout=30)
    run(at)
    if mode != at.radio(key="calculator-mode").value:
        at.radio(key="calculator-mode").set_value(mode)
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
    # Nothing counts until a researcher has been added, including the peer review and journal editorial work.
    assert metric_values(at) == ["$0 (USD)", "0 h", "$0 (USD)"]
    assert at.selectbox(key="user_country_select").value is None
    field_select = next(box for box in at.selectbox if box.label.startswith("Field of research"))
    assert field_select.value is None
    assert at.session_state["people"] == {}
    assert at.selectbox(key="add-person-role").value is None
    assert at.slider(key="review-rounds").value == 3
    assert at.slider(key="journal-submissions").value == 1
    assert not any(box.key == "activity-name-1" for box in at.selectbox)
    assert all(button.disabled for button in at.button if button.key and button.key.startswith("add-activity-"))
    assert at.button(key="load-alam-defaults").disabled


def test_first_researcher_starts_without_activities() -> None:
    at: AppTest = run_app()
    person: Person = add_researcher(at)
    assert person.label == "Researcher 1"
    assert not any(isinstance(a, Activity) for a in at.session_state["activity_list"])
    assert at.session_state["cost_list"] == []
    # The form is emptied ready for the next researcher.
    assert at.selectbox(key="add-person-role").value is None
    assert not at.button(key="load-alam-defaults").disabled
    # Each researcher gets an hours slider in the form to add an activity.
    assert at.slider(key="add-item-hours-1").value == 0.0
    assert at.slider(key="add-item-hours-1").max == 800.0
    add_researcher(at)
    assert at.slider(key="add-item-hours-2").value == 0.0


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
    first_activity: Activity = next(a for a in at.session_state["activity_list"] if isinstance(a, Activity))
    assert (first_activity.name, first_activity.hours) == ("Ideation and conception", 55.0)
    assert at.session_state["cost_list"][0].cost == 246.0
    # Each activity and direct cost is listed with buttons to edit and delete it.
    assert at.button(key="item-activity-1-edit")
    assert at.button(key="item-direct-cost-1-delete")
    assert at.slider(key="review-rounds").value == 3


def test_editing_people_keeps_loaded_activities() -> None:
    at: AppTest = run_app()
    add_researcher_at_rate(at)
    load_alam_defaults(at)
    add_researcher(at, "lecturer")
    first_activity: Activity = next(a for a in at.session_state["activity_list"] if isinstance(a, Activity))
    assert (first_activity.name, first_activity.hours, first_activity.person.unique_key) == (
        "Ideation and conception",
        55.0,
        "1",
    )
    assert at.session_state["cost_list"][0].name == "Participant incentivization"
    assert at.button(key="item-activity-1-edit")
    # The share section always shows a notice about hours on the results image; no other warning should appear.
    assert not [w for w in at.warning if "total number of hours" not in w.value]


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
    assert at.session_state["cost_list"][0].cost == round(cost, 2)


def test_session_state_round_trip() -> None:
    at: AppTest = run_app("simplified")
    state: CalculatorState = CalculatorState.from_session_state(AppTestSessionState(at))
    expected: CalculatorState = CalculatorState.default()
    assert CalculatorState.from_json(state.to_json()) == expected


def test_import_replaces_edited_widgets() -> None:
    at: AppTest = run_app()
    add_researcher_at_rate(at)
    load_alam_defaults(at)
    # Edit widgets so they hold their own state, which the import must override.
    at.slider(key="add-item-hours-1").set_value(300.0)
    at.slider(key="review-rounds").set_value(10)
    run(at)
    # 798 hours, and the peer review going from 8 to 22 hours.
    assert metric_values(at)[1] == "812 h"

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
    assert at.slider(key="add-item-hours-1").value == 0.0
    assert at.button(key="item-activity-1-edit")
    assert at.slider(key="review-rounds").value == 2
    assert at.selectbox(key="user_country_select").value == "us"
    assert CalculatorState.from_session_state(AppTestSessionState(at)) == restored


def test_adding_researcher_with_role() -> None:
    at: AppTest = run_app()
    at.selectbox(key="user_country_select").set_value("au")
    run(at)
    role_select = at.selectbox(key="add-person-role")
    assert "Senior Lecturer (based on median salary for a US Assistant Professor)" in role_select.options
    assert role_select.options[-2:] == ["Enter a salary manually", "Enter an hourly rate manually"]

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


def test_adding_researcher_with_hourly_rate() -> None:
    at: AppTest = run_app()
    at.selectbox(key="add-person-role").set_value("manual_hourly_rate")
    run(at)
    at.number_input(key="add-person-hourly-rate").set_value(50.0)
    submit_researcher_form(at)
    person: Person = at.session_state["people"]["1"]
    # US$50 an hour, plus the default 40% indirect cost rate.
    assert person.role is None
    assert person.hourly_rate == 70


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
    first, second = at.session_state["people"].values()
    at.session_state["activity_list"].extend(
        [
            Activity("Solo", second, "data", 10, 3, 1),
            Activity("Shared", first, "data", 5, 4, 2),
            Activity("Shared", second, "data", 7, 5, 2),
        ]
    )
    at.button(key="delete-person-2").click()
    run(at)
    assert list(at.session_state["people"]) == ["1"]
    activities: list[Activity] = [a for a in at.session_state["activity_list"] if isinstance(a, Activity)]
    # Hours of an activity both researchers worked on are added together.
    assert [(a.name, a.person.unique_key, a.hours) for a in activities] == [("Solo", "1", 10), ("Shared", "1", 12)]

    # Deleting the last researcher deletes the activities that were assigned to them.
    at.button(key="delete-person-1").click()
    run(at)
    assert at.session_state["people"] == {}
    assert not any(isinstance(a, Activity) for a in at.session_state["activity_list"])


def test_adding_activity() -> None:
    at: AppTest = run_app()
    add_researcher(at)
    add_researcher(at, "lecturer")
    # Choosing a preset fills in its default hours for the first researcher.
    at.selectbox(key="add-item-name").set_value("Grant applications")
    run(at)
    assert at.slider(key="add-item-hours-1").value == 171.0
    assert at.slider(key="add-item-hours-2").value == 0.0
    at.slider(key="add-item-hours-2").set_value(20.5)
    next(button for button in at.button if button.label == "Add activity").click()
    run(at)
    activities: list[Activity] = [a for a in at.session_state["activity_list"] if isinstance(a, Activity)]
    assert [(a.name, a.phase, a.person.unique_key, a.hours) for a in activities] == [
        ("Grant applications", "incubation", "1", 171.0),
        ("Grant applications", "incubation", "2", 20.5),
    ]
    assert len({a.group_key for a in activities}) == 1
    # The form is emptied, and the activity listed under its phase.
    assert at.selectbox(key="add-item-name").value is None
    assert at.slider(key="add-item-hours-1").value == 0.0
    assert at.button(key=f"item-activity-{activities[0].group_key}-edit")
    assert metric_values(at)[1] == f"{171 + 20.5 + 23:.0f} h"


def test_adding_activity_needs_a_name_and_hours() -> None:
    at: AppTest = run_app()
    add_researcher(at)
    # Without a name, nothing is added.
    next(button for button in at.button if button.label == "Add activity").click()
    run(at)
    assert not any(isinstance(a, Activity) for a in at.session_state["activity_list"])
    # Without hours, nothing is added.
    at.selectbox(key="add-item-name").set_value("Other")
    run(at)
    assert at.slider(key="add-item-hours-1").value == 0.0
    next(button for button in at.button if button.label == "Add activity").click()
    run(at)
    assert not any(isinstance(a, Activity) for a in at.session_state["activity_list"])


def test_editing_and_deleting_activity() -> None:
    at: AppTest = run_app()
    add_researcher_at_rate(at)
    add_researcher(at, "lecturer")
    at.selectbox(key="add-item-phase").set_value("data")
    run(at)
    at.selectbox(key="add-item-name").set_value("Data analysis")
    run(at)
    next(button for button in at.button if button.label == "Add activity").click()
    run(at)
    group_key: int = next(a for a in at.session_state["activity_list"] if isinstance(a, Activity)).group_key

    at.button(key=f"item-activity-{group_key}-edit").click()
    run(at)
    edit_key: str = f"edit-item-activity-{group_key}"
    assert at.selectbox(key=f"{edit_key}-name").value == "Data analysis"
    assert at.slider(key=f"{edit_key}-hours-1").value == 157.5
    at.slider(key=f"{edit_key}-hours-1").set_value(0.0)
    at.slider(key=f"{edit_key}-hours-2").set_value(10.0)
    next(button for button in at.button if button.label == "Save changes").click()
    run(at)
    activities: list[Activity] = [a for a in at.session_state["activity_list"] if isinstance(a, Activity)]
    # The first researcher was removed from the activity, and the second added.
    assert [(a.person.unique_key, a.hours) for a in activities] == [("2", 10.0)]

    at.button(key=f"item-activity-{group_key}-delete").click()
    run(at)
    assert not any(isinstance(a, Activity) for a in at.session_state["activity_list"])


def test_adding_editing_and_deleting_direct_cost() -> None:
    at: AppTest = run_app()
    add_researcher(at)
    at.selectbox(key="user_country_select").set_value("au")
    run(at)
    at.radio(key="add-item-kind").set_value("direct_cost")
    at.selectbox(key="add-item-phase").set_value("data")
    run(at)
    # The presets are those of the chosen phase, and choosing one fills in its default cost in the user's currency.
    assert "Participant incentivization" in at.selectbox(key="add-item-name").options
    at.selectbox(key="add-item-name").set_value("Participant incentivization")
    run(at)
    cost: float | None = convert_currency(246, "USD", "AUD")
    assert cost is not None
    assert at.number_input(key="add-item-cost").value == round(cost, 2)
    next(button for button in at.button if button.label == "Add direct cost").click()
    run(at)
    assert [(c.name, c.phase, c.cost) for c in at.session_state["cost_list"]] == [
        ("Participant incentivization", "data", round(cost, 2))
    ]
    assert at.selectbox(key="add-item-name").value is None
    assert at.number_input(key="add-item-cost").value == 0.0

    at.button(key="item-direct-cost-1-edit").click()
    run(at)
    assert at.number_input(key="edit-item-direct_cost-1-cost").value == round(cost, 2)
    at.number_input(key="edit-item-direct_cost-1-cost").set_value(500.0)
    next(button for button in at.button if button.label == "Save changes").click()
    run(at)
    assert at.session_state["cost_list"][0].cost == 500.0

    at.button(key="item-direct-cost-1-delete").click()
    run(at)
    assert at.session_state["cost_list"] == []


def test_field_of_research_select() -> None:
    at: AppTest = run_app("simplified")
    field_select = next(box for box in at.selectbox if box.label.startswith("Field of research"))
    # No field is chosen until the user picks one.
    assert field_select.value is None
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


def test_simplified_is_the_default_mode() -> None:
    at: AppTest = AppTest.from_file(MAIN, default_timeout=30)
    run(at)
    assert at.radio(key="calculator-mode").value == "simplified"
    assert not any(box.key == "activity-name-1" for box in at.selectbox)
    assert not any(button.key == "load-alam-defaults" for button in at.button)
    assert [cost.key for cost in at.number_input if cost.key and cost.key.startswith("simplified-cost-")] == [
        f"simplified-cost-{phase}" for phase in OVERALL_TOTAL_PHASES
    ]


def test_simplified_starts_at_zero_and_loads_defaults_for_first_researcher() -> None:
    at: AppTest = run_app("simplified")
    add_researcher_at_rate(at)
    add_researcher(at, "lecturer")
    run(at)
    assert at.slider(key="simplified-hours-incubation-1").value == 0.0
    assert at.slider(key="simplified-hours-incubation-1").max == 800.0
    assert at.number_input(key="simplified-cost-data").value == 0.0
    # Only the 23 hours of peer review and journal editorial work, at US$85.
    assert metric_values(at) == [f"${23 * 85:,.0f} (USD)", "23 h", "$0 (USD)"]

    at.button(key="load-simplified-defaults").click()
    run(at)
    assert at.slider(key="simplified-hours-incubation-1").value == 286.0
    assert at.slider(key="simplified-hours-data-1").value == 266.5
    assert at.slider(key="simplified-hours-writing-1").value == 223.0
    assert at.slider(key="simplified-hours-incubation-2").value == 0.0
    # 775.5 hours of research and 23 hours of peer review and journal editorial work, at US$85.
    assert metric_values(at) == [f"${(775.5 + 23) * 85 + 3646:,.0f} (USD)", f"{775.5 + 23:.0f} h", "$3,646 (USD)"]


def test_simplified_estimates() -> None:
    at: AppTest = run_app("simplified")
    add_researcher_at_rate(at)
    at.slider(key="simplified-hours-incubation-1").set_value(100.0)
    at.slider(key="simplified-hours-data-1").set_value(0.0)
    at.slider(key="simplified-hours-writing-1").set_value(0.0)
    at.number_input(key="simplified-cost-data").set_value(250.0)
    run(at)
    assert metric_values(at) == [f"${(100 + 23) * 85 + 250:,.0f} (USD)", "123 h", "$250 (USD)"]

    # The detailed estimates are separate, and the mode chosen decides which count.
    at.radio(key="calculator-mode").set_value("detailed")
    run(at)
    assert metric_values(at) == ["$1,955 (USD)", "23 h", "$0 (USD)"]
    at.radio(key="calculator-mode").set_value("simplified")
    run(at)
    assert at.slider(key="simplified-hours-incubation-1").value == 100.0
    assert at.number_input(key="simplified-cost-data").value == 250.0
    assert metric_values(at) == [f"${(100 + 23) * 85 + 250:,.0f} (USD)", "123 h", "$250 (USD)"]


def test_simplified_direct_costs_convert_with_currency() -> None:
    at: AppTest = run_app("simplified")
    at.number_input(key="simplified-cost-data").set_value(100.0)
    run(at)
    at.selectbox(key="user_country_select").set_value("au")
    run(at)
    cost: float | None = convert_currency(100, "USD", "AUD")
    assert cost is not None
    assert at.number_input(key="simplified-cost-data").value == round(cost, 2)


def test_deleting_researcher_moves_simplified_hours() -> None:
    at: AppTest = run_app("simplified")
    add_researcher(at)
    add_researcher(at, "lecturer")
    at.slider(key="simplified-hours-incubation-1").set_value(286.0)
    at.slider(key="simplified-hours-data-1").set_value(266.5)
    at.slider(key="simplified-hours-incubation-2").set_value(50.0)
    at.slider(key="simplified-hours-data-2").set_value(600.0)
    run(at)
    at.button(key="delete-person-1").click()
    run(at)
    assert list(at.session_state["people"]) == ["2"]
    assert at.slider(key="simplified-hours-incubation-2").value == 336.0
    # The hours are capped at the slider's maximum.
    assert at.slider(key="simplified-hours-data-2").value == 800.0


def test_sunburst_only_shown_in_detailed_mode() -> None:
    # AppTest cannot read Plotly charts, so look for the caption shown beneath the sunburst.
    def sunburst_caption_shown(at: AppTest) -> bool:
        return any(caption.value.startswith("Percentages are calculated") for caption in at.caption)

    at: AppTest = run_app("simplified")
    assert not sunburst_caption_shown(at)
    at.radio(key="calculator-mode").set_value("detailed")
    run(at)
    assert sunburst_caption_shown(at)


def test_researcher_slider_labels_show_role_and_hourly_rate() -> None:
    at: AppTest = run_app("simplified")
    add_researcher(at, "assistant_professor")
    at.selectbox(key="add-person-role").set_value("manual_salary")
    run(at)
    at.number_input(key="add-person-salary").set_value(104000)
    submit_researcher_form(at)
    role_rate: str = f"${ROLES['assistant_professor'].hourly_rate_usd * 1.4:,.2f} / hour"
    label: str = at.slider(key="simplified-hours-incubation-1").label
    assert label == f"Researcher 1 ({ROLES['assistant_professor'].short_display_name('')}) hours ({role_rate})"
    # A researcher with a salary instead of a role has no role in the label.
    assert at.slider(key="simplified-hours-incubation-2").label == "Researcher 2 hours ($70.00 / hour)"
    # The slider in the form to add an activity is labelled the same way.
    detailed: AppTest = run_app("detailed")
    add_researcher(detailed, "assistant_professor")
    assert detailed.slider(key="add-item-hours-1").label == label


def test_clear_all_researchers_asks_for_confirmation() -> None:
    at: AppTest = run_app("simplified")
    assert at.button(key="clear-people").disabled
    add_researcher(at)
    add_researcher(at, "lecturer")
    assert not at.button(key="clear-people").disabled

    # Clicking the button opens the confirmation dialog rather than deleting anything.
    at.button(key="clear-people").click()
    run(at)
    assert not at.exception
    assert at.button(key="confirm-clear-people")
    assert len(at.session_state["people"]) == 2

    at.button(key="cancel-clear-people").click()
    run(at)
    assert len(at.session_state["people"]) == 2

    # AppTest reruns the whole script when a button is clicked, so the dialog, which the real app reruns as a fragment,
    # is closed again by then and its confirm button cannot be clicked. Deleting the researchers is covered by the
    # tests of deleting a researcher.
