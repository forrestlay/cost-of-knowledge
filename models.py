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

from typing import Protocol
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class PersonType(Enum):
    RESEARCH_TEAM = 0
    OTHER = 1


@dataclass
class Person:
    """Represents a member of the study team or someone involved in the publication process and used to calculate cost
    of labour.

    Attributes:
        name: Person's name (for research team members) or role.
        unique_key: Unique identifier for this person.
        person_type: Whether person is a research team member or other.
        hourly_rate: Cost of person's labour per hour.
    """

    name: str
    unique_key: str
    person_type: PersonType
    hourly_rate: int | float

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
        else:
            return 0

    def to_str(self) -> str:
        return_str: str = f"{self.name},{str(self.hourly_rate)}"
        return return_str

    @classmethod
    def from_str(input: str) -> Person:
        values: list[str] = input.split(",")
        name: str = values[0]
        unique_key: str = values[1]
        hourly_rate: float = float(values[2])
        return Person(name, unique_key, PersonType.RESEARCH_TEAM, hourly_rate)


class Cost(Protocol):
    """Base interface for anything that contributes to the total cost of a journal publication."""

    phase: str

    def get_total_cost(self) -> int | float: ...


class BaseActivity(ABC):
    @abstractmethod
    def get_name(self) -> str: ...

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
    """Represents a labour-based activity.
    Assigned to a Person and cost is calculated based on Person's hourly_rate.

    Attributes:
        name: Name of the activity.
        person: Person to who this activity is assigned.
        phase: Phase of research this activity belongs to.
        hours: Number of hours allocated to this activity, used to calculate the total cost.
        unique_key: Unique numerical identifier for this activity.
    """

    name: str
    person: Person
    phase: str
    hours: int | float
    unique_key: int

    def get_name(self) -> str:
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
        total_cost: int | float = self.person.hourly_rate * self.hours
        return total_cost
    
    def get_phase(self) -> str:
        """Returns the phase of journal publication preparation this is assigned to."""
        return self.phase


@dataclass
class DirectCost:
    """Represents a direct cost.

    Attributes:
        name: Name of this cost.
        phase: Phase of research this cost belongs to.
        cost: Value of this cost in dollars.
        unique_key: Unique numerical identifier for this direct cost.
    """

    name: str
    phase: str
    cost: int | float
    unique_key: int

    def get_total_cost(self) -> int | float:
        """Returns the total cost of this direct cost in dollars."""
        return self.cost
    
    def get_phase(self) -> str:
        """Returns the phase of journal publication preparation this is assigned to."""
        return self.phase


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
