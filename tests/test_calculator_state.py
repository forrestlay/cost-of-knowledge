"""Tests for CalculatorState serialisation."""

from __future__ import annotations

import json

import pytest

from src.calculator_state import SCHEMA_VERSION, CalculatorState, default_phase_hours
from src.models import Activity, PeerReview, Person, PersonType


def default_with_researcher() -> CalculatorState:
    """The default state with one researcher, as the calculator has once one has been added."""
    state: CalculatorState = CalculatorState.default()
    state.people["1"] = Person("1", PersonType.RESEARCH_TEAM, 85)
    return state


def modified_state() -> CalculatorState:
    """A state with the Alam et al. (2026) estimates, a second person sharing an activity, a float rate and custom
    project details."""
    state: CalculatorState = default_with_researcher().with_default_costs()
    state.user_country = "au"
    state.international_collaborators = True
    second: Person = Person("2", PersonType.RESEARCH_TEAM, 41.2, "research_scientist", 3)
    state.people["2"] = second
    state.activities.append(Activity("Data collection", second, "data", 20, 11, 4))
    state.peer_review.review_rounds = 5
    state.peer_reviewer.hourly_rate = 100
    return state


def test_default_totals() -> None:
    state: CalculatorState = CalculatorState.default()
    # Peer review and journal editorial work only count once a researcher has been added.
    assert state.total_hours() == 0
    # The default simplified direct costs count from the start: US$246 for data collection and US$3,400 for writing.
    # Publishing costs are excluded by default.
    assert state.total_cost() == pytest.approx(3646)
    state.people["1"] = Person("1", PersonType.RESEARCH_TEAM, 85)
    # Three review rounds of one journal submission is 8 hours, and journal editorial work is 15, at US$85.
    assert state.total_hours() == 23
    assert state.total_cost() == pytest.approx(23 * 85 + 3646)
    del state.people["1"]
    assert state.people == {}
    assert [activity for activity in state.activities if isinstance(activity, Activity)] == []
    assert state.direct_costs == []


def test_with_default_costs_needs_a_researcher() -> None:
    with pytest.raises(ValueError, match="researcher"):
        CalculatorState.default().with_default_costs()


def test_quantity_does_not_change_totals() -> None:
    state: CalculatorState = default_with_researcher().with_default_costs()
    hours: float = state.total_hours()
    cost: float = state.total_cost()
    state.people["1"].quantity = 2
    assert state.total_hours() == hours
    assert state.total_cost() == pytest.approx(cost)


def test_missing_quantity_defaults_to_one() -> None:
    data = modified_state().to_dict()
    del data["people"][1]["quantity"]
    assert CalculatorState.from_dict(data).people["2"].quantity == 1


def test_with_default_costs_totals() -> None:
    state: CalculatorState = default_with_researcher().with_default_costs()
    # 775.5 activity hours, 8 peer review hours and 15 journal editing hours at US$85, plus US$3,646 direct costs.
    assert state.total_hours() == 798.5
    assert state.total_cost() == pytest.approx(798.5 * 85 + 3646)


def test_simplified_totals_ignore_detailed_estimates() -> None:
    state: CalculatorState = default_with_researcher().with_default_costs()
    state.calculator_mode = "simplified"
    state.simplified_hours = {"incubation": {"1": 100.0}}
    state.simplified_direct_costs = {"writing": 500.0}
    # Peer review and journal editorial work count in both modes: 8 + 15 hours.
    assert state.total_hours() == 123
    assert state.total_cost() == pytest.approx(123 * 85 + 500)
    assert state.summary()["phase_costs"]["incubation"] == pytest.approx(100 * 85)
    assert CalculatorState.from_json(state.to_json()) == state


def test_default_phase_hours() -> None:
    assert default_phase_hours() == {"incubation": 286.0, "data": 266.5, "writing": 223.0}


def test_json_round_trip() -> None:
    state: CalculatorState = modified_state()
    restored: CalculatorState = CalculatorState.from_json(state.to_json())
    assert restored == state
    assert restored.total_cost() == pytest.approx(state.total_cost())
    assert restored.summary() == state.summary()


def test_round_trip_preserves_person_identity() -> None:
    restored: CalculatorState = CalculatorState.from_json(modified_state().to_json())
    for activity in restored.activities:
        person: Person = activity.get_person()
        assert (
            person
            is {**restored.people, "Peer reviewer": restored.peer_reviewer, "Journal editor": restored.journal_editor}[
                person.unique_key
            ]
        )

    # A rate change must reach every activity the person works on, as it does in the live calculator.
    restored.people["1"].hourly_rate = 1
    assert all(
        activity.get_person().hourly_rate == 1
        for activity in restored.activities
        if isinstance(activity, Activity) and activity.person.unique_key == "1"
    )


def test_round_trip_preserves_activity_order() -> None:
    state: CalculatorState = modified_state()
    restored: CalculatorState = CalculatorState.from_json(state.to_json())
    assert [type(activity) for activity in restored.activities] == [type(activity) for activity in state.activities]
    assert isinstance(restored.peer_review, PeerReview)


def test_summary_with_phase_labels() -> None:
    state: CalculatorState = CalculatorState.default()
    summary = state.summary(
        {
            "incubation": "Incubation",
            "data": "Data",
            "writing": "Writing",
            "editing": "Editing",
            "publishing": "Publishing",
        }
    )
    assert list(summary["phase_costs"]) == ["Incubation", "Data", "Writing", "Editing", "Publishing"]
    assert sum(summary["phase_costs"].values()) == pytest.approx(summary["total_cost"])


def test_unsupported_schema_version_raises() -> None:
    data = CalculatorState.default().to_dict()
    data["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="schema_version"):
        CalculatorState.from_dict(data)


def test_schema_version_1_names_are_ignored() -> None:
    """Version 1 data, which held the user's, project's and people's names, loads without them."""
    state: CalculatorState = modified_state()
    data = state.to_dict()
    data["schema_version"] = 1
    data["project"].update(user_name="Ada", project_name="A study")
    for person_data in [*data["people"], data["peer_reviewer"], data["journal_editor"]]:
        person_data["name"] = "A name"
        del person_data["role"]
    state.people["2"].role = None
    assert CalculatorState.from_dict(data) == state


def test_missing_peer_review_raises() -> None:
    data = CalculatorState.default().to_dict()
    data["activities"] = [activity for activity in data["activities"] if activity["kind"] != "peer_review"]
    with pytest.raises(ValueError, match="PeerReview"):
        CalculatorState.from_dict(data)


def test_duplicate_person_key_raises() -> None:
    data = default_with_researcher().to_dict()
    data["people"].append(dict(data["people"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        CalculatorState.from_dict(data)


def test_json_is_plain() -> None:
    """The exported JSON only uses plain JSON types, so it can be stored or sent anywhere."""
    data = json.loads(modified_state().to_json())
    assert data["people"][1] == {
        "unique_key": "2",
        "person_type": "RESEARCH_TEAM",
        "hourly_rate": 41.2,
        "role": "research_scientist",
        "quantity": 3,
    }
