"""Tests for the ``Verdict`` contract."""

import pydantic
import pytest

from pair.contracts import CriterionStatus, Verdict
from tests.contracts.factories import valid_evidence


def make_verdict(**overrides: object) -> dict[str, object]:
    """Return kwargs for a verdict with one met and one insufficient criterion."""
    base: dict[str, object] = {
        "policy_id": "pap-osa",
        "results": [
            {"criterion_id": "ahi_threshold", "status": "met", "evidence": [valid_evidence()], "trace": "ahi=18.2 >= 15"},
            {"criterion_id": "adherence", "status": "insufficient", "evidence": [], "trace": "no device report"},
        ],
        "overall": "insufficient",
        "gaps": [{"criterion_id": "adherence", "message": "Ask your supplier for the 30-day usage report."}],
    }
    return {**base, **overrides}


def test_valid_verdict_round_trips() -> None:
    """A valid verdict round-trips and keeps typed statuses."""
    verdict = Verdict.model_validate(make_verdict())
    assert Verdict.model_validate_json(verdict.model_dump_json()) == verdict
    assert verdict.overall is CriterionStatus.INSUFFICIENT


def test_gap_for_met_criterion_rejected() -> None:
    """A met criterion never gets a gap entry."""
    gaps = [{"criterion_id": "ahi_threshold", "message": "x"}]
    with pytest.raises(pydantic.ValidationError, match="not unmet or insufficient"):
        Verdict.model_validate(make_verdict(gaps=gaps))


def test_missing_gap_for_insufficient_criterion_rejected() -> None:
    """Every unmet or insufficient criterion gets a gap entry."""
    with pytest.raises(pydantic.ValidationError, match="missing gap"):
        Verdict.model_validate(make_verdict(gaps=[]))


def test_duplicate_results_rejected() -> None:
    """One result per criterion."""
    result = {"criterion_id": "a", "status": "met", "evidence": [], "trace": "t"}
    with pytest.raises(pydantic.ValidationError, match="duplicate"):
        Verdict.model_validate(make_verdict(results=[result, result], gaps=[]))


def test_evidence_must_belong_to_its_criterion() -> None:
    """A result can't cite evidence extracted for another criterion."""
    results = [{"criterion_id": "adherence", "status": "met", "evidence": [valid_evidence()], "trace": "t"}]
    with pytest.raises(pydantic.ValidationError, match="belongs to"):
        Verdict.model_validate(make_verdict(results=results, gaps=[]))
