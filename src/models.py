"""Contains various dataclasses and helper functions for the main Cost of Knowledge tool.

Copyright 2026 Nurul Alam, Ben Lay

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping


def _resolve_person(data: Mapping[str, Any], people: Mapping[str, Person]) -> Person:
    """Looks up the Person referenced by a serialised activity's ``person_key``.

    Raises:
        ValueError: If no Person with that key exists in ``people``.
    """
    person_key: str = str(data["person_key"])
    if person_key not in people:
        raise ValueError(f"Activity references unknown person_key {person_key!r}.")
    return people[person_key]


class PersonType(Enum):
    RESEARCH_TEAM = 0
    OTHER = 1


@dataclass
class Person:
    """Represents a member of the study team or someone involved in the publication process and used to calculate cost
    of labour.

    People are not named, so that no personal information is collected. Research team members are identified as
    "Researcher 1", "Researcher 2", etc. by their unique_key, and other people by their unique_key alone (e.g.
    "Peer reviewer").

    Attributes:
        unique_key: Unique identifier for this person.
        person_type: Whether person is a research team member or other.
        hourly_rate: Cost of person's labour per hour.
        role: Key of the person's role in reference_data.ROLES (e.g. "assistant_professor"), or None if not chosen.
        quantity: Number of people who share this hourly rate. Recorded for display only; it does not affect costs.
    """

    unique_key: str
    person_type: PersonType
    hourly_rate: int | float
    role: str | None = None
    quantity: int = 1

    @property
    def label(self) -> str:
        """Display name of this person, e.g. "Researcher 1", "Researcher Set 1" (quantity of 2 or more) or "Peer
        reviewer"."""
        if self.person_type == PersonType.RESEARCH_TEAM:
            prefix: str = "Researcher Set" if self.quantity >= 2 else "Researcher"
            return f"{prefix} {self.unique_key}"
        return self.unique_key

    @classmethod
    def salary_to_hourly_rate(
        self,
        salary: int,
        working_hours_weekly: int = 40,
        contract_period_months: int = 12,
        indirect_cost_multiplier: float = 1.0,
    ) -> int | float:
        """Converts a base salary to an hourly rate. Options to set the number of months and the hours of work per week.
        Leave and public holidays are not excluded as it is assumed the person is paid for those periods as well.

        Args:
            salary: A person's base annual salary.
        """
        if salary < 0 or working_hours_weekly < 0 or contract_period_months < 0:
            raise ValueError("Values must be positive.")

        contract_period_weeks = contract_period_months / 12 * 52
        contract_period_hours = contract_period_weeks * working_hours_weekly

        if salary > 0:
            return salary / contract_period_hours * indirect_cost_multiplier
        return 0

    def to_dict(self) -> dict[str, Any]:
        """Returns a JSON-serialisable dict of this person."""
        return {
            "unique_key": self.unique_key,
            "person_type": self.person_type.name,
            "hourly_rate": self.hourly_rate,
            "role": self.role,
            "quantity": self.quantity,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Person:
        """Creates a Person from a dict produced by ``to_dict``.

        Ignores the "name" key written by schema version 1, which has no "role" key. Data saved before quantities
        existed has no "quantity" key, and is loaded with a quantity of 1.
        """
        return cls(
            unique_key=str(data["unique_key"]),
            person_type=PersonType[data["person_type"]],
            hourly_rate=data["hourly_rate"],
            role=data.get("role"),
            quantity=int(data.get("quantity") or 1),
        )


class Cost(Protocol):
    """Base interface for anything that contributes to the total cost of a journal publication."""

    phase: str

    def get_name(self) -> str | None: ...

    def get_total_cost(self) -> int | float: ...

    def get_phase(self) -> str: ...


class BaseActivity(ABC):
    @abstractmethod
    def get_name(self) -> str | None: ...

    @abstractmethod
    def get_person(self) -> Person: ...

    @abstractmethod
    def get_hours(self) -> int | float: ...

    @abstractmethod
    def get_total_cost(self) -> int | float: ...

    @abstractmethod
    def get_phase(self) -> str: ...


@dataclass
class Activity(BaseActivity):
    """Represents the labour of one Person on an activity.
    Assigned to a Person and cost is calculated based on Person's hourly_rate.

    An activity can involve several people, each working their own number of hours. Every person on an activity is
    represented by a separate Activity sharing the same name, phase and group_key.

    Attributes:
        name: Name of the activity. May be None while a newly added activity is unnamed.
        person: Person to who this activity is assigned.
        phase: Phase of research this activity belongs to.
        hours: Number of hours allocated to this activity, used to calculate the total cost.
        unique_key: Unique numerical identifier for this activity.
        group_key: Numerical identifier shared by every person assigned to the same activity.
    """

    name: str | None
    person: Person
    phase: str
    hours: int | float
    unique_key: int
    group_key: int

    def get_name(self) -> str | None:
        """Returns name of this activity."""
        return self.name

    def get_person(self) -> Person:
        """Returns person attached to this activity."""
        return self.person

    def get_hours(self) -> int | float:
        """Returns the total hours associated with this activity."""
        return self.hours

    def get_total_cost(self) -> int | float:
        """Returns the total cost of this activity in dollars."""
        total_cost: int | float = self.person.hourly_rate * self.get_hours()
        return total_cost

    def get_phase(self) -> str:
        """Returns the phase of journal publication preparation this is assigned to."""
        return self.phase

    def to_dict(self) -> dict[str, Any]:
        """Returns a JSON-serialisable dict of this activity. The person is stored by its unique_key."""
        return {
            "kind": "activity",
            "name": self.name,
            "person_key": self.person.unique_key,
            "phase": self.phase,
            "hours": self.hours,
            "unique_key": self.unique_key,
            "group_key": self.group_key,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], people: Mapping[str, Person]) -> Activity:
        """Creates an Activity from a dict produced by ``to_dict``.

        Args:
            data: The serialised activity.
            people: Every Person the activity could be assigned to, keyed by unique_key.
        """
        return cls(
            name=data["name"],
            person=_resolve_person(data, people),
            phase=data["phase"],
            hours=data["hours"],
            unique_key=int(data["unique_key"]),
            group_key=int(data["group_key"]),
        )


@dataclass
class DirectCost:
    """Represents a direct cost.

    Attributes:
        name: Name of this cost. May be None while a newly added cost is unnamed.
        phase: Phase of research this cost belongs to.
        cost: Value of this cost in dollars.
        unique_key: Unique numerical identifier for this direct cost.
    """

    name: str | None
    phase: str
    cost: int | float
    unique_key: int

    def get_name(self) -> str | None:
        return self.name

    def get_total_cost(self) -> int | float:
        """Returns the total cost of this direct cost in dollars."""
        return self.cost

    def get_phase(self) -> str:
        """Returns the phase of journal publication preparation this is assigned to."""
        return self.phase

    def to_dict(self) -> dict[str, Any]:
        """Returns a JSON-serialisable dict of this direct cost."""
        return {
            "name": self.name,
            "phase": self.phase,
            "cost": self.cost,
            "unique_key": self.unique_key,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DirectCost:
        """Creates a DirectCost from a dict produced by ``to_dict``."""
        return cls(
            name=data["name"],
            phase=data["phase"],
            cost=data["cost"],
            unique_key=int(data["unique_key"]),
        )


@dataclass
class PeerReview(BaseActivity):
    """Represents peer review activities.
    Assigned to a Person and cost is calculated based on Person's hourly_rate.

    Attributes:
        name: Name of the activity.
        person: Person to who this activity is assigned.
        phase: Phase of research this activity belongs to.
        hours: Number of hours allocated to this activity, used to calculate the total cost.
        unique_key: Unique numerical identifier for this activity.
    """

    person: Person
    review_rounds: int
    journal_submissions: int
    name: str = "Peer review"
    phase: str = "editing"
    initial_round_hours: int | float = 4
    subsequent_round_hours: int | float = 2
    unique_key: int = 1

    def get_name(self) -> str:
        """Returns name of this activity."""
        return self.name

    def get_person(self) -> Person:
        """Returns person attached to this activity."""
        return self.person

    def get_hours(self) -> int | float:
        """Returns the total hours associated with this activity."""
        if self.review_rounds <= 0:
            return 0
        hours_per_submission: int | float = self.initial_round_hours + (
            self.subsequent_round_hours * (self.review_rounds - 1)
        )
        hours: int | float = self.journal_submissions * hours_per_submission
        return hours

    def get_total_cost(self) -> int | float:
        """Returns the total cost of this activity in dollars."""
        total_cost: int | float = self.person.hourly_rate * self.get_hours()
        return total_cost

    def get_phase(self) -> str:
        """Returns the phase of journal publication preparation this is assigned to."""
        return self.phase

    def to_dict(self) -> dict[str, Any]:
        """Returns a JSON-serialisable dict of this activity. The person is stored by its unique_key."""
        return {
            "kind": "peer_review",
            "name": self.name,
            "person_key": self.person.unique_key,
            "phase": self.phase,
            "review_rounds": self.review_rounds,
            "journal_submissions": self.journal_submissions,
            "initial_round_hours": self.initial_round_hours,
            "subsequent_round_hours": self.subsequent_round_hours,
            "unique_key": self.unique_key,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], people: Mapping[str, Person]) -> PeerReview:
        """Creates a PeerReview from a dict produced by ``to_dict``.

        Args:
            data: The serialised activity.
            people: Every Person the activity could be assigned to, keyed by unique_key.
        """
        return cls(
            person=_resolve_person(data, people),
            review_rounds=int(data["review_rounds"]),
            journal_submissions=int(data["journal_submissions"]),
            name=data["name"],
            phase=data["phase"],
            initial_round_hours=data["initial_round_hours"],
            subsequent_round_hours=data["subsequent_round_hours"],
            unique_key=int(data["unique_key"]),
        )


@dataclass
class JournalEditing(BaseActivity):
    """Represents journal editorial work activities.
    Assigned to a Person and cost is calculated based on Person's hourly_rate.

    Attributes:
        name: Name of the activity.
        person: Person to who this activity is assigned.
        phase: Phase of research this activity belongs to.
        hours: Number of hours allocated to this activity, used to calculate the total cost.
        unique_key: Unique numerical identifier for this activity.
    """

    person: Person
    journal_submissions: int
    name: str = "Journal editorial work"
    phase: str = "editing"
    hours_per_submission: int | float = 15
    unique_key: int = 1

    def get_name(self) -> str:
        """Returns name of this activity."""
        return self.name

    def get_person(self) -> Person:
        """Returns person attached to this activity."""
        return self.person

    def get_hours(self) -> int | float:
        """Returns the total hours associated with this activity."""
        hours: int | float = self.journal_submissions * self.hours_per_submission
        return hours

    def get_total_cost(self) -> int | float:
        """Returns the total cost of this activity in dollars."""
        total_cost: int | float = self.person.hourly_rate * self.get_hours()
        return total_cost

    def get_phase(self) -> str:
        """Returns the phase of journal publication preparation this is assigned to."""
        return self.phase

    def to_dict(self) -> dict[str, Any]:
        """Returns a JSON-serialisable dict of this activity. The person is stored by its unique_key."""
        return {
            "kind": "journal_editing",
            "name": self.name,
            "person_key": self.person.unique_key,
            "phase": self.phase,
            "journal_submissions": self.journal_submissions,
            "hours_per_submission": self.hours_per_submission,
            "unique_key": self.unique_key,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], people: Mapping[str, Person]) -> JournalEditing:
        """Creates a JournalEditing from a dict produced by ``to_dict``.

        Args:
            data: The serialised activity.
            people: Every Person the activity could be assigned to, keyed by unique_key.
        """
        return cls(
            person=_resolve_person(data, people),
            journal_submissions=int(data["journal_submissions"]),
            name=data["name"],
            phase=data["phase"],
            hours_per_submission=data["hours_per_submission"],
            unique_key=int(data["unique_key"]),
        )
