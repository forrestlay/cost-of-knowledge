"""Serialisable snapshot of every input to the Cost of Knowledge calculator.

A CalculatorState holds everything that contributes to the calculator's totals, charts and social media image, and
can be converted to and from a dict or JSON, or copied into and out of Streamlit's session state.

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

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.models import (
    Activity,
    BaseActivity,
    DirectCost,
    JournalEditing,
    PeerReview,
    Person,
    PersonType,
)
from src.reference_data import RESEARCH_PHASES, ROLES

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping, Sequence

    from src.models import Cost

# Key type of st.session_state (streamlit.elements.lib.utils.Key). Mapping key types are invariant, so session state
# parameters must use it rather than str to accept st.session_state.
type SessionStateKey = str | int

# Bump when the serialised format changes, and teach CalculatorState.from_dict to read the older versions.
# Version 2 removed the user's name, the project's name and people's names, and added people's roles. Version 1 data
# is read by ignoring the names, with no roles.
SCHEMA_VERSION: int = 2
SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (1, 2)
# Project-wide indirect cost rate (%) applied to hourly rates calculated from a salary. Projects saved before the rate
# was stored are loaded with this rate.
DEFAULT_INDIRECT_COST_PERCENTAGE: int = 40

# Keys of the widgets in main.py whose values are held in st.session_state. A keyed widget takes its value from
# session state and ignores its value=/index= argument, so these must be cleared when a new state is applied or the
# widgets would keep showing (and writing back) the previous calculator's values.
WIDGET_KEY_PREFIXES: tuple[str, ...] = (
    "person-role-",  # Researchers: role selectbox
    "person-rate-",  # Researchers: hourly rate number_input
    "activity-name-",  # Calculator: activity name selectbox
    "activity-person-",  # Calculator: assigned person selectbox
    "activity-hours-",  # Calculator: hours number_input
    "directcost-name-",  # Calculator: direct cost name selectbox
    "directcost-cost-",  # Calculator: direct cost number_input
)
WIDGET_KEYS: tuple[str, ...] = (
    "user_country_select",  # You and your project: country selectbox
    "indirect_cost_percentage",  # Indirect Costs: project-wide indirect cost rate slider
    "review-rounds",  # Peer review and journal editorial work: review rounds slider
    "journal-submissions",  # Peer review and journal editorial work: journal submissions slider
)
# Conservative estimates of the activities and costs of a social sciences journal article from Alam et al. (2026),
# loaded from data/default_costs.json, and the starting hourly rate of the calculator's people.
_DEFAULT_COSTS: dict[str, Any] = json.loads(
    (Path(__file__).parent.parent / "data" / "default_costs.json").read_text(encoding="utf-8")
)
# Phases that start with an "(Overall Total)" activity. The editing phase has its own peer review and journal editorial
# work activities instead.
OVERALL_TOTAL_PHASES: tuple[str, ...] = ("incubation", "data", "writing")


def compute_costs(costs: Sequence[Cost], phase: str | None = None) -> float:
    """Calculates the total cost of activities and direct costs in the given list.

    Args:
        costs: A list of Cost items (Activities or DirectCosts).
        phase: If not None (default), only calculates costs for the given RESEARCH_PHASE key.
    """
    total_cost: float = 0.0
    for cost_item in costs:
        if phase is None or phase == cost_item.phase:
            total_cost += cost_item.get_total_cost()
    return total_cost


def compute_hours(activities: Sequence[BaseActivity], phase: str | None = None) -> float:
    """Calculates the total labour hours of activities in the given list.

    Args:
        costs: A list of Activity items.
        phase: If not None (default), only calculates hours for the given RESEARCH_PHASE key.
    """
    total_hours: float = 0.0
    for activity in activities:
        if phase is None or phase == activity.get_phase():
            total_hours += activity.get_hours()
    return total_hours


def _activity_from_dict(data: Mapping[str, Any], people: Mapping[str, Person]) -> BaseActivity:
    """Creates the right BaseActivity subclass for a serialised activity, based on its ``kind``."""
    kind: str = data.get("kind", "activity")
    if kind == "activity":
        return Activity.from_dict(data, people)
    if kind == "peer_review":
        return PeerReview.from_dict(data, people)
    if kind == "journal_editing":
        return JournalEditing.from_dict(data, people)
    raise ValueError(f"Unknown activity kind {kind!r}.")


@dataclass
class CalculatorState:
    """Every input to the calculator.

    Attributes:
        user_country: Lowercase country code of the country the project is associated with (e.g. "us"), or "" if not
            yet chosen, in which case amounts are in USD.
        international_collaborators: Whether the project has collaborators outside the primary country.
        project_field: 4-digit Field of Research code of the project (a key of reference_data.FIELDS_OF_RESEARCH), or
            a broad field name (e.g. "Social sciences") for projects saved before codes were used.
        indirect_cost_percentage: Project-wide indirect cost rate, as a percentage of the direct hourly rate.
        people: Research team members, keyed by unique_key, in display order.
        peer_reviewer: The Person assigned to the peer review activity.
        journal_editor: The Person assigned to the journal editorial work activity.
        activities: Every activity in calculator order, including exactly one PeerReview and one JournalEditing.
            Activities reference Persons in people, peer_reviewer or journal_editor by object identity.
        direct_costs: Direct costs in calculator order.
    """

    user_country: str
    international_collaborators: bool
    project_field: str
    indirect_cost_percentage: int
    people: dict[str, Person]
    peer_reviewer: Person
    journal_editor: Person
    activities: list[BaseActivity]
    direct_costs: list[DirectCost]

    @property
    def peer_review(self) -> PeerReview:
        """The peer review activity in activities."""
        return next(activity for activity in self.activities if isinstance(activity, PeerReview))

    @property
    def journal_editing(self) -> JournalEditing:
        """The journal editorial work activity in activities."""
        return next(activity for activity in self.activities if isinstance(activity, JournalEditing))

    @classmethod
    def default(cls) -> CalculatorState:
        """Returns the calculator's starting state, with one "(Overall Total)" activity of 0 hours in each of the first
        three phases, no peer review or journal editorial work and no direct costs.
        """
        hourly_rate: int | float = _DEFAULT_COSTS["hourly_rate_usd"]
        default_person: Person = Person(
            unique_key="1",
            person_type=PersonType.RESEARCH_TEAM,
            hourly_rate=hourly_rate,
        )
        peer_reviewer: Person = Person(
            unique_key="Peer reviewer",
            person_type=PersonType.OTHER,
            hourly_rate=hourly_rate,
        )
        journal_editor: Person = Person(
            unique_key="Journal editor",
            person_type=PersonType.OTHER,
            hourly_rate=hourly_rate,
        )
        # Each Activity below is one person's share of an activity. Activities sharing a group_key form a single
        # activity in the calculator, so the initial activities each start with one person and a group_key matching
        # their key. The names match the "(Overall Total)" activities in data/costs.json.
        activities: list[BaseActivity] = [
            Activity(f"{RESEARCH_PHASES[phase]} (Overall Total)", default_person, phase, 0, key, key)
            for key, phase in enumerate(OVERALL_TOTAL_PHASES, start=1)
        ]
        activities += [
            PeerReview(person=peer_reviewer, review_rounds=0, journal_submissions=0, unique_key=len(activities) + 1),
            JournalEditing(person=journal_editor, journal_submissions=0, unique_key=len(activities) + 2),
        ]
        return cls(
            user_country="",  # Blank until chosen. Amounts are in USD until then.
            international_collaborators=False,
            project_field="",  # Blank until chosen
            indirect_cost_percentage=DEFAULT_INDIRECT_COST_PERCENTAGE,
            people={default_person.unique_key: default_person},
            peer_reviewer=peer_reviewer,
            journal_editor=journal_editor,
            activities=activities,
            direct_costs=[],
        )

    def with_default_costs(self, usd_to_currency: float = 1.0) -> CalculatorState:
        """Returns a copy of this state with its activities and direct costs replaced by the conservative estimates for
        a social sciences journal article from Alam et al. (2026), loaded from data/default_costs.json.

        The project, people and hourly rates are kept. Every activity is assigned to the first research team member,
        and the peer reviewer and journal editor keep their rates.

        Args:
            usd_to_currency: Exchange rate from USD to the currency of this state's monetary values, applied to the
                direct costs.
        """
        state: CalculatorState = CalculatorState.from_dict(self.to_dict())
        first_person: Person = next(iter(state.people.values()))
        # As in default(), each activity starts with one person and a group_key matching its key.
        activities: list[BaseActivity] = [
            Activity(activity["name"], first_person, activity["phase"], activity["hours"], key, key)
            for key, activity in enumerate(_DEFAULT_COSTS["activities"], start=1)
        ]
        peer_review: Mapping[str, Any] = _DEFAULT_COSTS["peer_review"]
        journal_editing: Mapping[str, Any] = _DEFAULT_COSTS["journal_editing"]
        activities += [
            PeerReview(
                person=state.peer_reviewer,
                review_rounds=peer_review["review_rounds"],
                journal_submissions=peer_review["journal_submissions"],
                unique_key=len(activities) + 1,
            ),
            JournalEditing(
                person=state.journal_editor,
                journal_submissions=journal_editing["journal_submissions"],
                unique_key=len(activities) + 2,
            ),
        ]
        state.activities = activities
        state.direct_costs = [
            DirectCost(cost["name"], cost["phase"], round(cost["cost"] * usd_to_currency, 2), key)
            for key, cost in enumerate(_DEFAULT_COSTS["direct_costs"], start=1)
        ]
        return state

    # -----------------------------------------------
    # Totals
    # -----------------------------------------------

    def total_cost(self) -> float:
        """Total cost of every activity and direct cost in US$."""
        return compute_costs([*self.activities, *self.direct_costs])  # ty:ignore[invalid-argument-type]

    def total_hours(self) -> float:
        """Total hours of labour across every activity."""
        return compute_hours(self.activities)

    def summary(self, phase_labels: Mapping[str, str] | None = None) -> dict[str, Any]:
        """Derived totals for this state. Written alongside exports for reference and ignored on import.

        Args:
            phase_labels: Optional mapping of phase key to display name (e.g. reference_data.RESEARCH_PHASES). Phases
                are keyed by their phase key when omitted.
        """
        combined: list[Cost] = [*self.activities, *self.direct_costs]  # ty:ignore[invalid-assignment]
        phases: list[str] = list(dict.fromkeys(item.phase for item in combined))
        if phase_labels is not None:
            phases = list(dict.fromkeys([*phase_labels, *phases]))
        return {
            "total_cost": self.total_cost(),
            "total_hours": self.total_hours(),
            "phase_costs": {
                (phase_labels or {}).get(phase, phase): compute_costs(combined, phase=phase) for phase in phases
            },
        }

    # -----------------------------------------------
    # Dict and JSON
    # -----------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Returns a JSON-serialisable dict of this state. Activities reference people by their unique_key."""
        return {
            "schema_version": SCHEMA_VERSION,
            "project": {
                "user_country": self.user_country,
                "international_collaborators": self.international_collaborators,
                "project_field": self.project_field,
                "indirect_cost_percentage": self.indirect_cost_percentage,
            },
            "people": [person.to_dict() for person in self.people.values()],
            "peer_reviewer": self.peer_reviewer.to_dict(),
            "journal_editor": self.journal_editor.to_dict(),
            "activities": [activity.to_dict() for activity in self.activities],  # ty:ignore[unresolved-attribute]
            "direct_costs": [direct_cost.to_dict() for direct_cost in self.direct_costs],
            "summary": self.summary(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CalculatorState:
        """Creates a CalculatorState from a dict produced by ``to_dict``. The ``summary`` block is ignored, as are the
        user, project and people names written by schema version 1.

        Raises:
            ValueError: If the schema version is unsupported, or the data is inconsistent (duplicate person keys, an
                activity referencing an unknown person, or not exactly one peer review and journal editing activity).
        """
        schema_version: Any = data.get("schema_version")
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"Unsupported calculator schema_version {schema_version!r}.")

        people: dict[str, Person] = {}
        for person_data in data["people"]:
            person: Person = Person.from_dict(person_data)
            if person.unique_key in people:
                raise ValueError(f"Duplicate person unique_key {person.unique_key!r}.")
            people[person.unique_key] = person
        peer_reviewer: Person = Person.from_dict(data["peer_reviewer"])
        journal_editor: Person = Person.from_dict(data["journal_editor"])

        all_people: dict[str, Person] = dict(people)
        for special_person in (peer_reviewer, journal_editor):
            if special_person.unique_key in all_people:
                raise ValueError(f"Duplicate person unique_key {special_person.unique_key!r}.")
            all_people[special_person.unique_key] = special_person

        activities: list[BaseActivity] = [
            _activity_from_dict(activity_data, all_people) for activity_data in data["activities"]
        ]
        for special_type in (PeerReview, JournalEditing):
            count: int = sum(isinstance(activity, special_type) for activity in activities)
            if count != 1:
                raise ValueError(f"Expected exactly one {special_type.__name__} activity, found {count}.")

        project: Mapping[str, Any] = data["project"]
        return cls(
            user_country=project["user_country"],
            international_collaborators=bool(project["international_collaborators"]),
            project_field=project["project_field"],
            indirect_cost_percentage=int(project.get("indirect_cost_percentage", DEFAULT_INDIRECT_COST_PERCENTAGE)),
            people=people,
            peer_reviewer=peer_reviewer,
            journal_editor=journal_editor,
            activities=activities,
            direct_costs=[DirectCost.from_dict(cost_data) for cost_data in data["direct_costs"]],
        )

    def to_json(self, indent: int | None = 2) -> str:
        """Serialises this state to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, text: str | bytes) -> CalculatorState:
        """Creates a CalculatorState from a JSON string produced by ``to_json``."""
        return cls.from_dict(json.loads(text))

    # -----------------------------------------------
    # Streamlit session state
    # -----------------------------------------------

    @classmethod
    def from_session_state(cls, session_state: Mapping[SessionStateKey, Any]) -> CalculatorState:
        """Captures the calculator's current inputs from st.session_state.

        The returned state shares its model objects with session state; use
        ``CalculatorState.from_dict(state.to_dict())`` for an independent copy.
        """
        return cls(
            user_country=session_state["user_country"],
            international_collaborators=session_state["international_collaborators"],
            project_field=session_state["project_field"],
            indirect_cost_percentage=session_state["indirect_cost_percentage"],
            people=session_state["people"],
            peer_reviewer=session_state["peer_reviewer"],
            journal_editor=session_state["journal_editor"],
            activities=list(session_state["activity_list"]),
            direct_costs=list(session_state["cost_list"]),
        )

    def apply_to_session_state(self, session_state: MutableMapping[SessionStateKey, Any]) -> None:
        """Loads this state into st.session_state, replacing the calculator's current inputs.

        Must be called before the calculator's widgets are rendered in a script run, i.e. from a widget callback, or
        followed by st.rerun(). Streamlit raises an exception if the state of a widget that has already been rendered
        in the current run is modified.
        """
        # Clear stale widget state first so every widget picks up the values below.
        for key in list(session_state.keys()):
            if isinstance(key, str) and (key.startswith(WIDGET_KEY_PREFIXES) or key in WIDGET_KEYS):
                del session_state[key]

        peer_review: PeerReview = self.peer_review
        journal_editing: JournalEditing = self.journal_editing

        session_state["user_country"] = self.user_country
        # The country selectbox has no index=, so seed its widget state or it would show the first country in the list.
        # None leaves it blank.
        session_state["user_country_select"] = self.user_country or None
        session_state["international_collaborators"] = self.international_collaborators
        session_state["project_field"] = self.project_field
        session_state["indirect_cost_percentage"] = self.indirect_cost_percentage
        session_state["people"] = self.people
        session_state["peer_reviewer"] = self.peer_reviewer
        session_state["journal_editor"] = self.journal_editor
        session_state["peer_review_activity"] = peer_review
        session_state["journal_editing_activity"] = journal_editing
        session_state["activity_list"] = self.activities
        session_state["cost_list"] = self.direct_costs
        session_state["review_rounds"] = peer_review.review_rounds
        session_state["journal_submissions"] = peer_review.journal_submissions
        # The hourly rate inputs have an int min_value, so passing a float rate (e.g. one calculated from a salary)
        # as their value= would raise. Seed their widget state instead, as the salary dialog does.
        for key, person in self.people.items():
            session_state[f"person-rate-{key}"] = person.hourly_rate
        # Keys are reused (e.g. activity-hours-1 names whichever activity has unique_key 1), so the browser keeps
        # showing, and sends back on the next rerun, the value it already holds for a key unless the new value is
        # written into the widget's state. value= alone only reaches a widget the browser has not seen before.
        for key, person in self.people.items():
            # A role no longer in ROLES would show as the first role, so leave its selectbox unselected instead.
            session_state[f"person-role-{key}"] = person.role if person.role in ROLES else None
        for activity in self.activities:
            if isinstance(activity, Activity):
                session_state[f"activity-name-{activity.group_key}"] = activity.name
                session_state[f"activity-person-{activity.unique_key}"] = activity.person.unique_key
                session_state[f"activity-hours-{activity.unique_key}"] = float(activity.hours)
        for direct_cost in self.direct_costs:
            session_state[f"directcost-name-{direct_cost.unique_key}"] = direct_cost.name
            session_state[f"directcost-cost-{direct_cost.unique_key}"] = float(direct_cost.cost)
        session_state["review-rounds"] = peer_review.review_rounds
        session_state["journal-submissions"] = peer_review.journal_submissions
