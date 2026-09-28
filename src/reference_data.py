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

RESEARCH_PHASES: dict[str, str] = {
    "incubation": "Incubation",
    "data": "Data collection and analysis",
    "writing": "Manuscript preparation",
    "editing": "Peer review and journal editorial work",
}
