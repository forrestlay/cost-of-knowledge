"""Tests for CalculatorState serialisation."""

from __future__ import annotations

import json

import pytest

from calculator_state import SCHEMA_VERSION, CalculatorState
from models import Activity, PeerReview, Person, PersonType


def modified_state() -> CalculatorState:
    """A default state with a second person sharing an activity, a float rate and custom project details."""
    state: CalculatorState = CalculatorState.default()
    state.user_name = "Ada"
    state.project_name = "A study"
    state.user_country = "au"
    state.international_collaborators = True
    state.tool_step = 3
    second: Person = Person("Research Assistant", "2", PersonType.RESEARCH_TEAM, 41.2)
    state.people["2"] = second
    state.activities.append(Activity("Data collection", second, "data", 20, 11, 4))
    state.peer_review.review_rounds = 5
    state.peer_reviewer.hourly_rate = 100
    return state


def test_default_totals() -> None:
    state: CalculatorState = CalculatorState.default()
    # 775.5 activity hours, 8 peer review hours and 15 journal editing hours at US$85, plus US$3,646 direct costs.
    assert state.total_hours() == 798.5
    assert state.total_cost() == pytest.approx(798.5 * 85 + 3646)


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
        assert person is {**restored.people, "Peer reviewer": restored.peer_reviewer,
                          "Journal editor": restored.journal_editor}[person.unique_key]

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
    summary = state.summary({"incubation": "Incubation", "data": "Data", "writing": "Writing", "editing": "Editing"})
    assert list(summary["phase_costs"]) == ["Incubation", "Data", "Writing", "Editing"]
    assert sum(summary["phase_costs"].values()) == pytest.approx(summary["total_cost"])


def test_unsupported_schema_version_raises() -> None:
    data = CalculatorState.default().to_dict()
    data["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="schema_version"):
        CalculatorState.from_dict(data)


def test_missing_peer_review_raises() -> None:
    data = CalculatorState.default().to_dict()
    data["activities"] = [activity for activity in data["activities"] if activity["kind"] != "peer_review"]
    with pytest.raises(ValueError, match="PeerReview"):
        CalculatorState.from_dict(data)


def test_duplicate_person_key_raises() -> None:
    data = CalculatorState.default().to_dict()
    data["people"].append(dict(data["people"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        CalculatorState.from_dict(data)


def test_json_is_plain() -> None:
    """The exported JSON only uses plain JSON types, so it can be stored or sent anywhere."""
    data = json.loads(modified_state().to_json())
    assert data["people"][1] == {
        "name": "Research Assistant",
        "unique_key": "2",
        "person_type": "RESEARCH_TEAM",
        "hourly_rate": 41.2,
    }
