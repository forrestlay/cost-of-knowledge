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
from typing import TYPE_CHECKING, Any

from models import (
    Activity,
    BaseActivity,
    DirectCost,
    JournalEditing,
    PeerReview,
    Person,
    PersonType,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping, Sequence

    from models import Cost

# Key type of st.session_state (streamlit.elements.lib.utils.Key). Mapping key types are invariant, so session state
# parameters must use it rather than str to accept st.session_state.
type SessionStateKey = str | int

# Bump when the serialised format changes, and teach CalculatorState.from_dict to read the older versions.
SCHEMA_VERSION: int = 1

# Keys of the widgets in main.py whose values are held in st.session_state. A keyed widget takes its value from
# session state and ignores its value=/index= argument, so these must be cleared when a new state is applied or the
# widgets would keep showing (and writing back) the previous calculator's values.
WIDGET_KEY_PREFIXES: tuple[str, ...] = (
    "person-name-",  # People or Roles: name selectbox
    "person-rate-",  # People or Roles: hourly rate number_input
    "activity-name-",  # Calculator: activity name selectbox
    "activity-person-",  # Calculator: assigned person selectbox
    "activity-hours-",  # Calculator: hours number_input
    "directcost-name-",  # Calculator: direct cost name selectbox
    "directcost-cost-",  # Calculator: direct cost number_input
)
WIDGET_KEYS: tuple[str, ...] = (
    "user_country_select",  # You and your project: country selectbox
    "review-rounds",  # Peer review and journal editorial work: review rounds slider
    "journal-submissions",  # Peer review and journal editorial work: journal submissions slider
)
# Expander keys are f"{step}-expander". Clearing them lets each expander fall back to its expanded= argument, which
# main.py derives from the restored tool_step.
EXPANDER_KEY_SUFFIX: str = "-expander"


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
        user_name: Name of the tool user.
        user_country: Lowercase country code of the country the project is associated with (e.g. "us").
        international_collaborators: Whether the project has collaborators outside the primary country.
        project_name: Name of the paper or project.
        project_field: Field of science the project is located in.
        people: Research team members, keyed by unique_key, in display order.
        peer_reviewer: The Person assigned to the peer review activity.
        journal_editor: The Person assigned to the journal editorial work activity.
        activities: Every activity in calculator order, including exactly one PeerReview and one JournalEditing.
            Activities reference Persons in people, peer_reviewer or journal_editor by object identity.
        direct_costs: Direct costs in calculator order.
        tool_step: Index into main.TOOL_STEPS of the user's progress through the tool.
    """

    user_name: str | None
    user_country: str
    international_collaborators: bool
    project_name: str | None
    project_field: str
    people: dict[str, Person]
    peer_reviewer: Person
    journal_editor: Person
    activities: list[BaseActivity]
    direct_costs: list[DirectCost]
    tool_step: int = 0

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
        """Returns the calculator's pre-populated starting state."""
        default_person: Person = Person(
            name="Associate Professor",
            unique_key="1",
            person_type=PersonType.RESEARCH_TEAM,
            hourly_rate=85,
        )
        peer_reviewer: Person = Person(
            name="Peer reviewer",
            unique_key="Peer reviewer",
            person_type=PersonType.OTHER,
            hourly_rate=85,
        )
        journal_editor: Person = Person(
            name="Journal editor",
            unique_key="Journal editor",
            person_type=PersonType.OTHER,
            hourly_rate=85,
        )
        # Each Activity below is one person's share of an activity. Activities sharing a group_key form a single
        # activity in the calculator, so the initial activities each start with one person and a group_key matching
        # their key.
        activities: list[BaseActivity] = [
            Activity("Ideation and conception", default_person, "incubation", 55, 1, 1),
            Activity("Ethics approval", default_person, "incubation", 60, 2, 2),
            Activity("Grant applications", default_person, "incubation", 171, 3, 3),
            Activity("Data collection", default_person, "data", 48.5, 4, 4),
            Activity("Interview transcription", default_person, "data", 60.5, 5, 5),
            Activity("Data analysis", default_person, "data", 157.5, 6, 6),
            Activity("Writing and manuscript preparation", default_person, "writing", 100, 7, 7),
            Activity("Conferencing (labor)", default_person, "writing", 123, 8, 8),
            PeerReview(person=peer_reviewer, review_rounds=3, journal_submissions=1, unique_key=9),
            JournalEditing(person=journal_editor, journal_submissions=1, unique_key=10),
        ]
        return cls(
            user_name=None,
            user_country="us",
            international_collaborators=False,
            project_name=None,
            project_field="Social sciences",
            people={default_person.unique_key: default_person},
            peer_reviewer=peer_reviewer,
            journal_editor=journal_editor,
            activities=activities,
            direct_costs=[
                DirectCost("Participant incentivization", "data", 246, 1),
                DirectCost("Conferencing (direct costs)", "writing", 3400, 2),
            ],
        )

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
            phase_labels: Optional mapping of phase key to display name (e.g. main.RESEARCH_PHASES). Phases are keyed
                by their phase key when omitted.
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
                "user_name": self.user_name,
                "user_country": self.user_country,
                "international_collaborators": self.international_collaborators,
                "project_name": self.project_name,
                "project_field": self.project_field,
            },
            "people": [person.to_dict() for person in self.people.values()],
            "peer_reviewer": self.peer_reviewer.to_dict(),
            "journal_editor": self.journal_editor.to_dict(),
            "activities": [activity.to_dict() for activity in self.activities],  # ty:ignore[unresolved-attribute]
            "direct_costs": [direct_cost.to_dict() for direct_cost in self.direct_costs],
            "tool_step": self.tool_step,
            "summary": self.summary(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CalculatorState:
        """Creates a CalculatorState from a dict produced by ``to_dict``. The ``summary`` block is ignored.

        Raises:
            ValueError: If the schema version is unsupported, or the data is inconsistent (duplicate person keys, an
                activity referencing an unknown person, or not exactly one peer review and journal editing activity).
        """
        schema_version: Any = data.get("schema_version")
        if schema_version != SCHEMA_VERSION:
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
            user_name=project["user_name"],
            user_country=project["user_country"],
            international_collaborators=bool(project["international_collaborators"]),
            project_name=project["project_name"],
            project_field=project["project_field"],
            people=people,
            peer_reviewer=peer_reviewer,
            journal_editor=journal_editor,
            activities=activities,
            direct_costs=[DirectCost.from_dict(cost_data) for cost_data in data["direct_costs"]],
            tool_step=int(data.get("tool_step", 0)),
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
            user_name=session_state["user_name"] or None,
            user_country=session_state["user_country"],
            international_collaborators=session_state["international_collaborators"],
            project_name=session_state["project_name"] or None,
            project_field=session_state["project_field"],
            people=session_state["people"],
            peer_reviewer=session_state["peer_reviewer"],
            journal_editor=session_state["journal_editor"],
            activities=list(session_state["activity_list"]),
            direct_costs=list(session_state["cost_list"]),
            tool_step=session_state.get("tool_step", 0),
        )

    def apply_to_session_state(self, session_state: MutableMapping[SessionStateKey, Any]) -> None:
        """Loads this state into st.session_state, replacing the calculator's current inputs.

        Must be called before the calculator's widgets are rendered in a script run, i.e. from a widget callback, or
        followed by st.rerun(). Streamlit raises an exception if the state of a widget that has already been rendered
        in the current run is modified.
        """
        # Clear stale widget state first so every widget picks up the values below.
        for key in list(session_state.keys()):
            if isinstance(key, str) and (
                key.startswith(WIDGET_KEY_PREFIXES) or key in WIDGET_KEYS or key.endswith(EXPANDER_KEY_SUFFIX)
            ):
                del session_state[key]

        peer_review: PeerReview = self.peer_review
        journal_editing: JournalEditing = self.journal_editing

        session_state["tool_step"] = self.tool_step
        session_state["user_name"] = self.user_name
        session_state["user_name_input"] = self.user_name or ""
        session_state["user_country"] = self.user_country
        # The country selectbox has no index=, so seed its widget state or it would show the first country in the list.
        session_state["user_country_select"] = self.user_country
        session_state["international_collaborators"] = self.international_collaborators
        session_state["project_name"] = self.project_name
        session_state["project_field"] = self.project_field
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
