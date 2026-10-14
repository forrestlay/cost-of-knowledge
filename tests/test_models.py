"""Tests for the dict round-trips of the calculator models."""

from __future__ import annotations

import pytest

from src.models import Activity, DirectCost, JournalEditing, PeerReview, Person, PersonType


@pytest.fixture
def people() -> dict[str, Person]:
    return {
        "1": Person("1", PersonType.RESEARCH_TEAM, 52.75, "assistant_professor"),
        "Peer reviewer": Person("Peer reviewer", PersonType.OTHER, 85),
    }


def test_person_round_trip(people: dict[str, Person]) -> None:
    person: Person = people["1"]
    data = person.to_dict()
    assert data["person_type"] == "RESEARCH_TEAM"
    assert Person.from_dict(data) == person


def test_person_has_no_name(people: dict[str, Person]) -> None:
    assert "name" not in people["1"].to_dict()
    # Names written by schema version 1 are ignored.
    assert Person.from_dict({**people["1"].to_dict(), "name": "Ada"}) == people["1"]


def test_person_with_base_hourly_rate_round_trip() -> None:
    person: Person = Person("1", PersonType.RESEARCH_TEAM, 43.75, base_hourly_rate=31.25)
    assert Person.from_dict(person.to_dict()) == person
    # Data saved before schema version 6 has no base hourly rate.
    data = person.to_dict()
    del data["base_hourly_rate"]
    assert Person.from_dict(data).base_hourly_rate is None


def test_apply_indirect_cost_rate() -> None:
    person: Person = Person("1", PersonType.RESEARCH_TEAM, 71.5, base_hourly_rate=55)
    person.apply_indirect_cost_rate(50)
    assert person.hourly_rate == 82.5
    person.apply_indirect_cost_rate(0)
    assert person.hourly_rate == 55
    # Rounded to the cent.
    rounded: Person = Person("2", PersonType.RESEARCH_TEAM, 0, base_hourly_rate=31.25)
    rounded.apply_indirect_cost_rate(33)
    assert rounded.hourly_rate == 41.56
    # A person without a base hourly rate, such as one with a role, keeps their rate.
    fixed: Person = Person("3", PersonType.RESEARCH_TEAM, 85, "associate_professor")
    fixed.apply_indirect_cost_rate(50)
    assert fixed.hourly_rate == 85


def test_person_without_role_round_trip(people: dict[str, Person]) -> None:
    person: Person = people["Peer reviewer"]
    assert person.to_dict()["role"] is None
    assert Person.from_dict(person.to_dict()) == person
    # Schema version 1 has no role.
    data = person.to_dict()
    del data["role"]
    assert Person.from_dict(data) == person


def test_person_label(people: dict[str, Person]) -> None:
    assert people["1"].label == "Researcher 1"
    assert people["Peer reviewer"].label == "Peer reviewer"


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


def test_peer_review_hours_scale_with_peer_reviewers(people: dict[str, Person]) -> None:
    peer_review: PeerReview = PeerReview(people["Peer reviewer"], review_rounds=3, journal_submissions=2)
    # 2 submissions of 4 + 2 * 2 hours each.
    assert peer_review.get_hours() == 16
    peer_review.peer_reviewers = 3
    assert peer_review.get_hours() == 48
    assert PeerReview.from_dict(peer_review.to_dict(), people) == peer_review


def test_peer_review_without_peer_reviewers_has_one(people: dict[str, Person]) -> None:
    data = PeerReview(people["Peer reviewer"], review_rounds=2, journal_submissions=1, peer_reviewers=4).to_dict()
    del data["peer_reviewers"]
    assert PeerReview.from_dict(data, people).peer_reviewers == 1


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
