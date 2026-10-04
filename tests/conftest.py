"""Shared test fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import streamlit as st

from src import currency_rates
from src.currency_rates import DEFAULT_EXCHANGE_RATES_FILE, SavedRates

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def offline_exchange_rates(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Serves the bundled default exchange rates, dated today, so tests don't depend on the API key or saved rates.

    data/exchange_rates.json is git-ignored and only exists after a successful API fetch, so without this the rates are
    unavailable on a fresh checkout or in CI and currency conversion returns None.
    """
    original_read = currency_rates._read_rates_file

    def read_default_rates(path: Path = DEFAULT_EXCHANGE_RATES_FILE) -> SavedRates | None:
        saved: SavedRates | None = original_read(DEFAULT_EXCHANGE_RATES_FILE)
        if saved is not None:
            saved["date"] = datetime.now(tz=UTC).date().isoformat()
        return saved

    monkeypatch.setattr(currency_rates, "_read_rates_file", read_default_rates)
    st.cache_data.clear()
    yield
    st.cache_data.clear()
