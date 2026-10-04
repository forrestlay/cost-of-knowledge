"""Sources USD exchange rates from the exchangeratesapi.io API for the Cost of Knowledge tool.

Rates are fetched at most once per day and saved to data/exchange_rates.json, which is reused for the rest of that day.
The API key is read from the EXCHANGE_RATES_API_KEY Streamlit secret in .streamlit/secrets.toml,
or failing that from the EXCHANGE_RATES_API_KEY environment variable.

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

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlencode

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

logger: logging.Logger = logging.getLogger(__name__)

EXCHANGE_RATES_API_URL: str = "https://api.exchangeratesapi.io/v1/latest"
EXCHANGE_RATES_SECRET: str = "EXCHANGE_RATES_API_KEY"
EXCHANGE_RATES_FILE: Path = Path(__file__).parent.parent / "data" / "exchange_rates.json"
DEFAULT_EXCHANGE_RATES_FILE: Path = Path(__file__).parent.parent / "data" / "exchange_rates_default.json"


class RateLimitError(RuntimeError):
    """Raised when the exchange rate API's usage limit has been reached."""


class SavedRates(TypedDict):
    """Contents of EXCHANGE_RATES_FILE."""

    date: str  # ISO format date the rates were fetched.
    base: str
    rates: dict[str, float]


def _read_rates_file(path: Path = EXCHANGE_RATES_FILE) -> SavedRates | None:
    """Returns the exchange rates saved at path, or None if the file is missing or unreadable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None


def _write_rates_file(data: SavedRates) -> None:
    """Saves exchange rates, writing to a temporary file first so a concurrent reader never sees a partial file."""
    temp_file: Path = EXCHANGE_RATES_FILE.with_suffix(".json.tmp")
    temp_file.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    temp_file.replace(EXCHANGE_RATES_FILE)


def _newer_default_rates(saved: SavedRates | None) -> dict[str, float] | None:
    """Returns the default rates if they exist and are dated later than saved (or nothing is saved), else None."""
    default: SavedRates | None = _read_rates_file(DEFAULT_EXCHANGE_RATES_FILE)
    if default is None:
        return None
    # ISO format dates compare correctly as strings.
    if saved is None or default.get("date", "") > saved.get("date", ""):
        return default["rates"]
    return None


def _get_api_key() -> str | None:
    """Returns the API key from Streamlit secrets, falling back to the environment variable of the same name."""
    try:
        api_key: str | None = st.secrets.get(EXCHANGE_RATES_SECRET)
    except StreamlitSecretNotFoundError:
        api_key = None
    return api_key or os.environ.get(EXCHANGE_RATES_SECRET)


def _fetch_usd_rates(api_key: str) -> dict[str, float]:
    """Queries exchangeratesapi.io for the latest rates, expressed as units of each currency per 1 USD.

    The free API plan only returns EUR-based rates, so the rates are requested with the default base and rebased to USD.

    Raises:
        RateLimitError: If the API's usage limit has been reached (HTTP 429).
        RuntimeError: If the API request fails or returns an error.
    """
    url: str = f"{EXCHANGE_RATES_API_URL}?{urlencode({'access_key': api_key})}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            payload: dict = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 429:
            raise RateLimitError("Exchange rate API usage limit reached") from None
        raise RuntimeError(f"Exchange rate request failed: HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        # Don't include the URL in the message, it contains the API key.
        raise RuntimeError(f"Exchange rate request failed: {type(error).__name__}") from None

    if not payload.get("success"):
        raise RuntimeError(f"Exchange rate API returned an error: {payload.get('error')}")

    rates: dict[str, float] = payload["rates"]
    usd_rate: float = rates["USD"]
    return {code: rate / usd_rate for code, rate in rates.items()}


@st.cache_data(ttl="1h", show_spinner=False)
def _load_usd_rates(today: str) -> dict[str, float] | None:
    """Returns today's USD exchange rates, querying the API only if they haven't already been saved today.

    If no API key is set or the API's usage limit has been reached, whichever of the default rates and the most recently
    saved rates is newer is used instead. If the API can't be queried for any other reason, the most recently saved
    rates are used. Cached for an hour so that a failing API isn't queried on every rerun.

    Args:
        today: Today's date in ISO format. Part of the cache key so the cache turns over each day.
    """
    saved: SavedRates | None = _read_rates_file()
    if saved is not None and saved.get("date") == today:
        return saved["rates"]

    api_key: str | None = _get_api_key()
    if api_key:
        try:
            rates: dict[str, float] = _fetch_usd_rates(api_key)
        except RateLimitError as error:
            default_rates: dict[str, float] | None = _newer_default_rates(saved)
            if default_rates is not None:
                logger.warning("%s, using default exchange rates.", error)
                return default_rates
            logger.warning("%s, using saved exchange rates.", error)
        except (RuntimeError, KeyError, ZeroDivisionError) as error:
            logger.warning("Could not update exchange rates: %s", error)
        else:
            _write_rates_file(SavedRates(date=today, base="USD", rates=rates))
            return rates
    else:
        default_rates = _newer_default_rates(saved)
        if default_rates is not None:
            logger.warning("No %s secret set, using default exchange rates.", EXCHANGE_RATES_SECRET)
            return default_rates
        logger.warning("No %s secret set, exchange rates can't be updated.", EXCHANGE_RATES_SECRET)

    return saved["rates"] if saved is not None else None


def get_usd_exchange_rates() -> dict[str, float] | None:
    """Returns exchange rates as units of each currency (by ISO 4217 code) per 1 USD, or None if unavailable."""
    return _load_usd_rates(datetime.now(tz=UTC).date().isoformat())


def convert_currency(amount: float, from_code: str, to_code: str) -> float | None:
    """Converts an amount between two currencies via their USD exchange rates.

    Returns:
        The converted amount, or None if a rate for either currency is unavailable.
    """
    rates: dict[str, float] | None = get_usd_exchange_rates()
    if rates is None or from_code not in rates or to_code not in rates:
        return None
    return amount / rates[from_code] * rates[to_code]
