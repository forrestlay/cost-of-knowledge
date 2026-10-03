"""Countries and research phases shared by the pages of the Cost of Knowledge tool.

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

# Country list loaded from data/country.json. The selectbox shows the country name
# but stores the lowercase country code (e.g. "us") as the value.
_COUNTRY_DATA: list[dict[str, object]] = json.loads(
    (Path(__file__).parent.parent / "data" / "country.json").read_text(encoding="utf-8")
)
COUNTRY_NAMES: dict[str, str] = {str(country["code"]): str(country["name"]) for country in _COUNTRY_DATA}
COUNTRY_CODES: list[str] = sorted(COUNTRY_NAMES, key=lambda code: COUNTRY_NAMES[code])
# ISO 4217 currency code (e.g. "USD") and symbol (e.g. "$") for each country code.
COUNTRY_CURRENCIES: dict[str, tuple[str, str]] = {
    str(country["code"]): (
        str(country["currency_code"]),
        str(country["currency_symbol"]),
    )
    for country in _COUNTRY_DATA
}


@dataclass(frozen=True)
class ResearcherRole:
    """A level of university or public research institution researcher, loaded from data/roles.json.

    Attributes:
        key: Identifier stored with a Person, e.g. "assistant_professor".
        sector: "university" or "public_research".
        us_label: Name of the role in the US, which every country is shown.
        hourly_rate_usd: Preset hourly rate of labor including indirect on-costs, in USD.
        local_labels: Name of the equivalent role in other countries, keyed by country code.
    """

    key: str
    sector: str
    us_label: str
    hourly_rate_usd: float
    local_labels: dict[str, str]

    def display_name(self, country: str) -> str:
        """Returns the role's local name followed by the US role its salary is based on, if the country has a
        different local name, otherwise the US label.

        Args:
            country: Lowercase country code, e.g. "au" gives "Senior Lecturer (based on median salary for a US
                Assistant Professor)".
        """
        local_label: str | None = self.local_labels.get(country)
        if local_label is None or local_label == self.us_label:
            return self.us_label
        return f"{local_label} (based on median salary for a US {self.us_label})"

    def short_display_name(self, country: str) -> str:
        """Returns only the role's local name when the country has one, otherwise the US label.

        Args:
            country: Lowercase country code, e.g. "au" gives "Senior Lecturer" for an Assistant Professor.
        """
        return self.local_labels.get(country, self.us_label)


# Researcher roles in display order, keyed by ResearcherRole.key.
ROLES: dict[str, ResearcherRole] = {
    str(role["key"]): ResearcherRole(
        key=str(role["key"]),
        sector=str(role["sector"]),
        us_label=str(role["us_label"]),
        hourly_rate_usd=float(role["hourly_rate_usd"]),
        local_labels={str(code): str(label) for code, label in role.get("local_labels", {}).items()},
    )
    for role in json.loads((Path(__file__).parent.parent / "data" / "roles.json").read_text(encoding="utf-8"))["roles"]
}


@dataclass(frozen=True)
class FieldOfResearch:
    """A Field of Research group (4-digit code) and the division (2-digit code) it belongs to, loaded from
    data/fields_of_research.json.
    """

    code: str
    name: str
    division_code: str
    division_name: str

    @property
    def display_name(self) -> str:
        """Returns the field as "[Division name]/[Group name]"."""
        return f"{self.division_name}/{self.name}"


# Field of Research groups in display order, keyed by their 4-digit code (e.g. "3501").
FIELDS_OF_RESEARCH: dict[str, FieldOfResearch] = {
    str(field["code"]): FieldOfResearch(
        code=str(field["code"]),
        name=str(field["name"]),
        division_code=str(field["division"]["code"]),
        division_name=str(field["division"]["name"]),
    )
    for field in json.loads(
        (Path(__file__).parent.parent / "data" / "fields_of_research.json").read_text(encoding="utf-8")
    )
}


def field_of_research_display_name(code: str) -> str:
    """Returns a Field of Research code's display name, or the value itself if it is not a known code.

    Projects saved before Field of Research codes were used hold a broad field name (e.g. "Social sciences") instead.
    """
    field: FieldOfResearch | None = FIELDS_OF_RESEARCH.get(code)
    return code if field is None else field.display_name


RESEARCH_PHASES: dict[str, str] = {
    "incubation": "Incubation",
    "data": "Data collection and analysis",
    "writing": "Manuscript preparation",
    "editing": "Peer review and journal editorial work",
    "publishing": "Publishing",
}


def currency_code(country: str) -> str:
    """ISO 4217 code (e.g. "USD") of a country's currency, falling back to USD for an unknown country."""
    return COUNTRY_CURRENCIES.get(country, COUNTRY_CURRENCIES["us"])[0]


def currency_prefix(country: str) -> str:
    """Prefix put before amounts in a country's currency.

    The currency symbol (e.g. "$"), or the ISO code and a space (e.g. "AED ") for currencies without one.
    """
    code, symbol = COUNTRY_CURRENCIES.get(country, COUNTRY_CURRENCIES["us"])
    return symbol if symbol != code else f"{code} "


def format_currency(amount: float, country: str) -> str:
    """Formats an amount as a string in a country's currency, e.g. "$1,234 (USD)"."""
    return f"{currency_prefix(country)}{amount:,.0f} ({currency_code(country)})"
