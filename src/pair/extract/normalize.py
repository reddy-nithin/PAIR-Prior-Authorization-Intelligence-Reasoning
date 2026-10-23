"""Turn extracted text values into typed rule values (stdlib only).

``"18.2 events/hr"`` → ``18.2``, ``"March 4, 2026"`` → ``date(2026, 3, 4)``,
``"no"`` → ``False``. Anything that won't parse becomes ``None``, so the rule
engine sees a mention without a value instead of a wrong value.
"""

import datetime as dt
import re
from typing import Any

from pair.contracts import EvidenceValue, VariableType

_NUMBER = re.compile(r"(?<![A-Za-z\d.])-?\d[\d,]*(?:\.\d+)?")
"""A number not glued to letters, so ``PaO2 54`` gives 54, not 2."""
_WORDS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12,
}  # fmt: skip
_MONTHS: dict[str, int] = {
    name: number
    for number, names in enumerate(
        [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
         ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
         ("oct", "october"), ("nov", "november"), ("dec", "december")],
        start=1,
    )
    for name in names
}  # fmt: skip
_HUNDRED_SCALE = re.compile(r"\d\s*mm\b|/\s*100\b|0\s*(?:-|–|to)\s*100\b", re.IGNORECASE)
"""A 0 to 100 pain scale: millimetres on a VAS line (not ``mmHg``), ``/100`` or a stated range."""
_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_US = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_MONTH_FIRST = re.compile(r"\b([a-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")
_DAY_FIRST = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\.?,?\s+(\d{4})\b")
_TRUE: frozenset[str] = frozenset({"true", "yes", "y", "present", "documented", "met", "positive"})
PAIN_SCORE_VARIABLES: frozenset[str] = frozenset({"pain_score"})
"""Rule variables read on a 0 to 10 pain scale."""
_FALSE: frozenset[str] = frozenset({"false", "no", "n", "absent", "none", "not documented", "negative"})


def normalize(var_type: VariableType, raw: Any) -> EvidenceValue:
    """Normalize a raw extracted value (a string or a list of strings) to ``var_type``."""
    if var_type is VariableType.LIST:
        return _to_list(raw)
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    text = str(raw).strip()
    if not text:
        return None
    if var_type is VariableType.NUMBER:
        return _to_number(text)
    if var_type is VariableType.DATE:
        return _to_date(text)
    if var_type is VariableType.BOOL:
        return _to_bool(text)
    return text


def pain_on_ten_point_scale(value: EvidenceValue, span: str) -> EvidenceValue:
    """Put a pain score on the 0 to 10 scale the rules use (ADR-0015).

    A 0 to 100 VAS (``35 mm``, ``62/100``, ``VAS (0-100) 48``) is divided by 10. A score above
    10 with no stated scale is unusable, so it becomes ``None`` rather than a false pass.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 10:
        return value
    if _HUNDRED_SCALE.search(span):
        return value / 10
    return None


def _to_number(text: str) -> int | float | None:
    """The first number in the text, or a small number word."""
    match = _NUMBER.search(text)
    if match:
        digits = match.group().replace(",", "")
        return float(digits) if "." in digits else int(digits)
    first = text.lower().split()[0]
    return _WORDS.get(first)


def _to_date(text: str) -> dt.date | None:
    """ISO, ``March 4, 2026``, ``4 March 2026`` or US ``03/04/2026``."""
    lowered = text.lower()
    candidates: list[tuple[int, int, int]] = []
    if m := _ISO.search(lowered):
        candidates.append((int(m[1]), int(m[2]), int(m[3])))
    if m := _US.search(lowered):
        candidates.append((int(m[3]), int(m[1]), int(m[2])))
    if (m := _MONTH_FIRST.search(lowered)) and m[1] in _MONTHS:
        candidates.append((int(m[3]), _MONTHS[m[1]], int(m[2])))
    if (m := _DAY_FIRST.search(lowered)) and m[2] in _MONTHS:
        candidates.append((int(m[3]), _MONTHS[m[2]], int(m[1])))
    for year, month, day in candidates:
        try:
            return dt.date(year, month, day)
        except ValueError:
            continue
    return None


def _to_bool(text: str) -> bool | None:
    """Common yes/no words."""
    lowered = text.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    return None


def _to_list(raw: Any) -> list[str] | None:
    """Split on ``;``/``,``, strip and de-duplicate; empty → None."""
    parts = raw if isinstance(raw, list) else re.split(r"[;,]", str(raw))
    items = [str(part).strip() for part in parts if str(part).strip()]
    return list(dict.fromkeys(items)) or None
