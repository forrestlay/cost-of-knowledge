"""Contains various dataclasses and helper functions for the main Cost of Knowledge tool."""

from typing import Protocol
from dataclasses import dataclass, field
from enum import Enum


class PersonType(Enum):
    RESEARCH_TEAM = 0
    OTHER = 1


@dataclass
class Person:
    """Represents a member of the study team and used to calculate cost of labour.

    Attributes:
        name: Person's name (for research team members) or role.
        person_type: Whether person is a research team member or other.
        hourly_rate: Cost of person's labour per hour.
        activities: Activities associated with this Person.
    """

    name: str
    person_type: PersonType
    hourly_rate: int | float
    activities: list[Activity] = field(default_factory=list)

    def __eq__(self, other) -> bool:
        """Custom equality function that checks only if name and hourly_rate are defined and the same on the other
        object.
        """
        return (self.name, self.hourly_rate) == (other.name, other.hourly_rate)

    def salary_to_hourly_rate(
        self,
        salary: int,
        working_hours_weekly: int = 40,
        contract_period_months: int = 12,
    ):
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
            self.hourly_rate: int | float = round(salary / contract_period_hours, 2)


class Cost(Protocol):
    """Base interface for anything that contributes to the total cost of a journal publication."""

    def get_total_cost(self) -> int | float: ...


@dataclass
class Activity:
    """Represents a labour-based activity.
    Assigned to a Person and cost is calculated based on Person's hourly_rate.

    Attributes:
        name: Name of the activity.
        person: Person to who this activity is assigned.
        hours: Number of hours allocated to this activity, used to calculate the total cost.
    """

    name: str
    person: Person
    hours: int | float

    def get_total_cost(self) -> int | float:
        """Returns the total cost of this activity in dollars."""
        total_cost: int | float = self.person.hourly_rate * self.hours
        return total_cost


@dataclass
class DirectCost:
    """Represents a direct cost.

    Attributes:
        name: Name of this cost.
        cost: Value of this cost in dollars.
    """

    name: str
    cost: int | float

    def get_total_cost(self) -> int | float:
        """Returns the total cost of this direct cost in dollars."""
        return self.cost


class Phase:
    """Represents a phase of the journal article preparation process. Acts as a container for activities and costs."""

    name: str
    costs: list[Cost] = []

    def __init__(self, name: str):
        self.name: str = name


class Model:
    """Data model for the entire Cost of Knowledge costing model."""

    people: list[Person] = []
    phases: list[Phase] = []
