"""Table tests for value normalization (T8)."""

import datetime as dt
from typing import Any

import pytest

from pair.contracts import VariableType
from pair.extract.normalize import normalize, pain_on_ten_point_scale


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("18.2 events/hr", 18.2),
        ("AHI 22", 22),
        ("72%", 72),
        ("rated 7/10", 7),
        ("PaO2 54 mmHg", 54),
        ("1,204 events", 1204),
        ("two", 2),
        ("Two blocks", 2),
        ("-3", -3),
        ("none recorded", None),
        ("", None),
    ],
)
def test_numbers(raw: str, expected: float | None) -> None:
    """The first number in the text, units and percent signs dropped; small number words work."""
    assert normalize(VariableType.NUMBER, raw) == expected


def test_number_keeps_int_type() -> None:
    """Whole numbers stay ints, decimals become floats."""
    assert isinstance(normalize(VariableType.NUMBER, "30"), int)
    assert isinstance(normalize(VariableType.NUMBER, "30.5"), float)


@pytest.mark.parametrize(
    "raw",
    ["2026-03-04", "March 4, 2026", "Mar 4 2026", "march 4th, 2026", "4 March 2026", "03/04/2026", "3/4/2026"],
)
def test_dates(raw: str) -> None:
    """ISO, written-out and US numeric dates all parse."""
    assert normalize(VariableType.DATE, raw) == dt.date(2026, 3, 4)


@pytest.mark.parametrize("raw", ["soon", "13/45/2026", "February 30, 2026", ""])
def test_bad_dates(raw: str) -> None:
    """Unparseable or impossible dates give None."""
    assert normalize(VariableType.DATE, raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("Yes", True), ("documented", True), ("false", False), ("no", False), ("absent", False), ("maybe", None)],
)
def test_bools(raw: str, expected: bool | None) -> None:
    """Common yes/no words map to bools; anything else is None."""
    assert normalize(VariableType.BOOL, raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("daytime sleepiness", ["daytime sleepiness"]),
        ("snoring; hypertension, insomnia", ["snoring", "hypertension", "insomnia"]),
        (["edema", " edema ", ""], ["edema"]),
        ("  ", None),
        ([], None),
    ],
)
def test_lists(raw: Any, expected: list[str] | None) -> None:
    """Lists are split on ; and , stripped and de-duplicated; empty is None."""
    assert normalize(VariableType.LIST, raw) == expected


def test_text_is_stripped() -> None:
    """Text values are stripped; blank is None."""
    assert normalize(VariableType.TEXT, "  CPAP ") == "CPAP"
    assert normalize(VariableType.TEXT, " ") is None


def test_list_value_for_scalar_type_uses_first_item() -> None:
    """LangExtract attributes can be lists; a scalar variable uses the first item."""
    assert normalize(VariableType.NUMBER, ["18.2", "20"]) == 18.2
    assert normalize(VariableType.NUMBER, []) is None


def test_lab_names_with_digits_are_skipped() -> None:
    """Digits inside a lab name (SpO2, PaO2) aren't the value."""
    assert normalize(VariableType.NUMBER, "SpO2 87%") == 87


@pytest.mark.parametrize(
    ("value", "span", "expected"),
    [
        (7, "rated 7/10", 7),
        (35, "VAS 35 mm", 3.5),
        (62, "pain 62/100 on the VAS", 6.2),
        (48, "VAS (0-100) 48", 4.8),
        (35, "pain score 35", None),  # above 10 with no stated scale: unusable, not a pass
        (None, "moderate pain", None),
    ],
)
def test_pain_scores_are_put_on_a_ten_point_scale(value: float | None, span: str, expected: float | None) -> None:
    """The rule reads 0 to 10, so a 0 to 100 mm VAS is divided by 10 (ADR-0015)."""
    assert pain_on_ten_point_scale(value, span) == expected
