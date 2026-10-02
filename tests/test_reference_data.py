"""Tests for the reference data loaded from the data folder."""

from __future__ import annotations

from src.reference_data import COUNTRY_NAMES, FIELDS_OF_RESEARCH, ROLES, field_of_research_display_name


def test_roles_are_valid() -> None:
    assert ROLES
    for key, role in ROLES.items():
        assert role.key == key
        assert role.sector in {"university", "public_research"}
        assert role.hourly_rate_usd > 0
        assert set(role.local_labels) <= set(COUNTRY_NAMES)


def test_role_display_name() -> None:
    role = ROLES["assistant_professor"]
    assert role.display_name("us") == "Assistant Professor"
    assert role.display_name("au") == "Senior Lecturer (based on median salary for a US Assistant Professor)"
    # Countries without a local label, or whose local label matches the US one, show only the US label.
    assert role.display_name("fr") == "Assistant Professor"
    assert ROLES["research_assistant"].display_name("au") == "Research Assistant"


def test_role_short_display_name() -> None:
    role = ROLES["assistant_professor"]
    assert role.short_display_name("us") == "Assistant Professor"
    assert role.short_display_name("au") == "Senior Lecturer"
    assert role.short_display_name("fr") == "Assistant Professor"


def test_fields_of_research() -> None:
    assert len(FIELDS_OF_RESEARCH) == 213
    field = FIELDS_OF_RESEARCH["3501"]
    assert field.display_name == "Commerce, management, tourism and services/Accounting, auditing and accountability"
    assert field_of_research_display_name("3501") == field.display_name
    # Broad field names saved before Field of Research codes were used are shown as they are.
    assert field_of_research_display_name("Social sciences") == "Social sciences"
