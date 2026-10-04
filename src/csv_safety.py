"""Protection against formula injection in CSV exports opened by spreadsheet software."""

from __future__ import annotations

import pandas as pd

# Characters that make a spreadsheet treat a cell as a formula.
_FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r", "\n")


def sanitise_cell(value: object) -> object:
    """Returns a string starting with a formula character prefixed by an apostrophe, and any other value unchanged."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def to_safe_csv(frame: pd.DataFrame, **kwargs: object) -> str:
    """Returns frame as CSV text with its text cells and column names made safe to open in a spreadsheet."""
    safe: pd.DataFrame = frame.copy()
    safe.columns = [sanitise_cell(column) for column in safe.columns]
    for column in safe.columns:
        if not pd.api.types.is_numeric_dtype(safe[column]) and not pd.api.types.is_bool_dtype(safe[column]):
            safe[column] = safe[column].map(sanitise_cell)
    return safe.to_csv(**kwargs)
