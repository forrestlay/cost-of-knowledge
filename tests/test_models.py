"""Tests for the dict round-trips of the calculator models."""

from __future__ import annotations

import pytest

from models import Activity, DirectCost, JournalEditing, PeerReview, Person, PersonType


@pytest.fixture
def people() -> dict[str, Person]:
    return {
        "1": Person("Ada", "1", PersonType.RESEARCH_TEAM, 52.75),
        "Peer reviewer": Person("Peer reviewer", "Peer reviewer", PersonType.OTHER, 85),
    }


def test_person_round_trip(people: dict[str, Person]) -> None:
    person: Person = people["1"]
    data = person.to_dict()
    assert data["person_type"] == "RESEARCH_TEAM"
    assert Person.from_dict(data) == person


def test_unnamed_person_round_trip() -> None:
    person: Person = Person(None, "2", PersonType.RESEARCH_TEAM, 85)
    assert Person.from_dict(person.to_dict()) == person


def test_activity_round_trip_resolves_person(people: dict[str, Person]) -> None:
    activity: Activity = Activity("Data analysis", people["1"], "data", 12.5, 4, 3)
    data = activity.to_dict()
    assert data["person_key"] == "1"
    assert "person" not in data

    restored: Activity = Activity.from_dict(data, people)
    assert restored == activity
    assert restored.person is people["1"]


def test_peer_review_round_trip(people: dict[str, Person]) -> None:
    peer_review: PeerReview = PeerReview(
        people["Peer reviewer"], review_rounds=4, journal_submissions=2, initial_round_hours=5, unique_key=9
    )
    restored: PeerReview = PeerReview.from_dict(peer_review.to_dict(), people)
    assert restored == peer_review
    assert restored.get_hours() == peer_review.get_hours()


def test_journal_editing_round_trip(people: dict[str, Person]) -> None:
    journal_editing: JournalEditing = JournalEditing(
        people["Peer reviewer"], journal_submissions=3, hours_per_submission=10, unique_key=10
    )
    assert JournalEditing.from_dict(journal_editing.to_dict(), people) == journal_editing


def test_direct_cost_round_trip() -> None:
    direct_cost: DirectCost = DirectCost(None, "writing", 99.5, 3)
    assert DirectCost.from_dict(direct_cost.to_dict()) == direct_cost


def test_unknown_person_key_raises(people: dict[str, Person]) -> None:
    data = Activity("Data analysis", people["1"], "data", 1, 1, 1).to_dict()
    data["person_key"] = "missing"
    with pytest.raises(ValueError, match="missing"):
        Activity.from_dict(data, people)
