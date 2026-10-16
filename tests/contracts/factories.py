"""Valid keyword arguments for each contract model, used to build test cases.

Each factory returns a fresh dict so tests can derive invalid variants with
``{**valid_x(), "field": bad}`` without mutating shared state.
"""

import datetime as dt
from typing import Any


def valid_denial() -> dict[str, Any]:
    """Return kwargs for a valid synthetic ``Denial``."""
    return {
        "service": "CPAP device",
        "codes": ["E0601"],
        "reason_text": "Records do not show a face-to-face evaluation before the sleep test.",
        "reason_category": "insufficient_documentation",
        "policy_ref": "L33718",
        "plan_type": "medicare_advantage",
        "date": dt.date(2026, 9, 1),
    }


def valid_source() -> dict[str, Any]:
    """Return kwargs for a valid ``PolicySource``."""
    return {
        "type": "LCD",
        "id": "L33718",
        "title": "Positive Airway Pressure (PAP) Devices for the Treatment of Obstructive Sleep Apnea",
        "url": "https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid=33718",
        "version": "1",
        "retrieved": dt.date(2026, 10, 15),
    }


def valid_criterion(criterion_id: str = "ahi_threshold") -> dict[str, Any]:
    """Return kwargs for a valid ``Criterion``."""
    return {
        "id": criterion_id,
        "text": "AHI at least 15, or 5 to 14 with symptoms",
        "clause": "The AHI or RDI is greater than or equal to 15 events per hour",
        "source_id": "L33718",
        "evidence_type": "lab_value",
        "variables": {"ahi": "number", "symptoms": "list"},
        "rule": "ahi >= 15 or (5 <= ahi <= 14 and any(symptoms))",
        "critical": True,
    }


def valid_checklist() -> dict[str, Any]:
    """Return kwargs for a valid ``Checklist`` with two criteria."""
    return {
        "id": "pap-osa",
        "title": "PAP devices for obstructive sleep apnea",
        "sources": [valid_source()],
        "context": {"initial": "bool"},
        "criteria": [valid_criterion("ahi_threshold"), valid_criterion("f2f_visit")],
        "logic": "f2f_visit and ahi_threshold",
    }


NOTE_TEXT = "Home sleep test shows AHI of 18.2 events/hr."


def valid_evidence() -> dict[str, Any]:
    """Return kwargs for a valid ``Evidence`` whose span matches ``NOTE_TEXT``."""
    start = NOTE_TEXT.index("AHI of 18.2")
    span = "AHI of 18.2"
    return {
        "criterion_id": "ahi_threshold",
        "variable": "ahi",
        "value": 18.2,
        "span_text": span,
        "char_start": start,
        "char_end": start + len(span),
        "doc_id": "note-1",
        "status": "asserted",
    }


def valid_policy_cite() -> dict[str, Any]:
    """Return kwargs for a valid ``PolicyCitation``."""
    return {"source_id": "L33718", "quote": "greater than or equal to 15 events per hour"}


def valid_claim() -> dict[str, Any]:
    """Return kwargs for a valid ``Claim``."""
    evidence = valid_evidence()
    return {
        "criterion_id": "ahi_threshold",
        "text": "My sleep test showed an AHI of 18.2, above the policy threshold of 15.",
        "policy_cite": valid_policy_cite(),
        "evidence_cite": {
            "doc_id": evidence["doc_id"],
            "char_start": evidence["char_start"],
            "char_end": evidence["char_end"],
            "quote": evidence["span_text"],
        },
        "score": None,
        "decision": None,
    }


def valid_strength() -> dict[str, Any]:
    """Return kwargs for a valid, non-abstaining ``Strength``."""
    return {
        "p": 0.62,
        "interval": {"low": 0.48, "high": 0.74},
        "abstain": False,
        "abstain_reason": None,
        "explanation": {
            "base_rate": 0.55,
            "n_similar": 412,
            "imr_category": "DME",
            "steps": [
                {"criterion_id": "ahi_threshold", "status": "met", "shift": 1.4, "why": "AHI 18.2 in note-1"},
                {"criterion_id": "adherence", "status": "insufficient", "shift": 0.8, "why": "No device report"},
            ],
            "improve": [
                {"criterion_id": "adherence", "action": "Ask your supplier for the 30-day usage report", "p_if_fixed": 0.71},
            ],
        },
    }
