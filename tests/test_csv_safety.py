import pandas as pd

from src.csv_safety import sanitise_cell, to_safe_csv


def test_formula_cells_are_prefixed() -> None:
    for value in ("=1+1", "+1", "-1", "@SUM(A1)", "\t=1"):
        assert sanitise_cell(value) == f"'{value}"


def test_other_values_are_unchanged() -> None:
    assert sanitise_cell("Writing") == "Writing"
    assert sanitise_cell(5) == 5
    assert sanitise_cell(-5) == -5


def test_to_safe_csv_keeps_numbers_and_escapes_text() -> None:
    frame = pd.DataFrame({"Name": ["=HYPERLINK(1)", "ok"], "Cost": [-1.5, 2.0]})
    assert to_safe_csv(frame, index=False).splitlines() == ["Name,Cost", "'=HYPERLINK(1),-1.5", "ok,2.0"]
