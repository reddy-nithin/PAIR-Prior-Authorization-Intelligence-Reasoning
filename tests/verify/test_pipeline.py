"""Tests for ``verify_letter``: citations, then entailment, then the threshold (step 6)."""

import dataclasses
from pathlib import Path

import pytest

from pair.contracts import (
    Checklist,
    Claim,
    ClaimDecision,
    Evidence,
    EvidenceCitation,
    EvidenceStatus,
    Letter,
    PolicyCitation,
)
from pair.policies.loader import load_all
from pair.verify.conformal import ConformalError, Threshold
from pair.verify.nli import PREMISE_RULE
from pair.verify.pipeline import verify_letter

DOC = "Seen in sleep clinic on 2026-03-02. Home sleep test on 2026-03-10: AHI 18.2 events/hr."
DOCS = {"note-1": DOC}


class FakeVerifier:
    """Scores claims from a lookup table and records each premise."""

    def __init__(self, scores: dict[str, float], backend: str = "minicheck") -> None:
        self.scores = scores
        self.backend = backend
        self.premises: list[str] = []

    def score(self, claim: str, premise: str) -> float:
        """Return the canned score for ``claim``."""
        self.premises.append(premise)
        return self.scores[claim]

    def describe(self) -> dict[str, str]:
        """Run metadata."""
        return {"verifier_backend": self.backend, "verifier_model": "bespoke-minicheck", "verifier_host": "h"}


@pytest.fixture(scope="module")
def pap(repo_root: Path) -> Checklist:
    """The shipped PAP checklist."""
    return load_all(repo_root / "policies")["pap-osa"]


def item(quote: str, criterion_id: str) -> Evidence:
    """Asserted evidence for ``quote``."""
    start = DOC.index(quote)
    return Evidence(
        criterion_id=criterion_id, variable="x", value=1.0, span_text=quote,
        char_start=start, char_end=start + len(quote), doc_id="note-1", status=EvidenceStatus.ASSERTED,
    )


def claim(pap: Checklist, criterion_id: str, quote: str, text: str, start: int | None = None) -> Claim:
    """A claim citing ``quote``."""
    criterion = next(c for c in pap.criteria if c.id == criterion_id)
    begin = DOC.index(quote) if start is None else start
    return Claim(
        criterion_id=criterion_id,
        text=text,
        policy_cite=PolicyCitation(source_id=criterion.source_id, quote=criterion.clause),
        evidence_cite=EvidenceCitation(doc_id="note-1", char_start=begin, char_end=begin + len(quote), quote=quote),
    )


EVIDENCE = [item("AHI 18.2 events/hr", "ahi_threshold"), item("Seen in sleep clinic on 2026-03-02", "f2f_visit")]
THRESHOLD = Threshold(q_hat=0.5, n=11, k=11, alpha=0.1, drafter="gemma4:e4b",
                      verifier_backend="minicheck", verifier_model="bespoke-minicheck")


def letter(pap: Checklist) -> Letter:
    """Three claims: high score, low score, and one with broken offsets."""
    return Letter(
        policy_id="pap-osa",
        claims=[
            claim(pap, "ahi_threshold", "AHI 18.2 events/hr", "My AHI was 18.2."),
            claim(pap, "f2f_visit", "Seen in sleep clinic on 2026-03-02", "I saw my doctor on 2026-03-02."),
            claim(pap, "ahi_threshold", "AHI 18.2 events/hr", "Broken.", start=0),
        ],
    )


SCORES = {"My AHI was 18.2.": 0.9, "I saw my doctor on 2026-03-02.": 0.3}


def test_chain_keeps_flags_and_drops(pap: Checklist) -> None:
    """Score above q-hat KEEP, at or below FLAG, failed citation DROP without being scored."""
    verifier = FakeVerifier(SCORES)
    result = verify_letter(letter(pap), pap, DOCS, EVIDENCE, verifier, THRESHOLD, drafter="gemma4:e4b")

    assert [c.decision for c in result.letter.claims] == [ClaimDecision.KEEP, ClaimDecision.FLAG, ClaimDecision.DROP]
    assert [c.score for c in result.letter.claims] == [0.9, 0.3, 0.0]
    assert len(verifier.premises) == 2
    assert result.metadata["drafter"] == "gemma4:e4b" and result.metadata["threshold"] == "fitted"


def test_premise_is_the_quote_sentence_without_policy_text(pap: Checklist) -> None:
    """The verifier sees the record sentence only."""
    verifier = FakeVerifier(SCORES)
    verify_letter(letter(pap), pap, DOCS, EVIDENCE, verifier, THRESHOLD, drafter="gemma4:e4b")

    assert verifier.premises[0] == "Home sleep test on 2026-03-10: AHI 18.2 events/hr."
    assert all("beneficiary" not in premise for premise in verifier.premises)
    assert verify_letter(letter(pap), pap, DOCS, EVIDENCE, FakeVerifier(SCORES), THRESHOLD, "gemma4:e4b").premises == (
        "Home sleep test on 2026-03-10: AHI 18.2 events/hr.", "Seen in sleep clinic on 2026-03-02.", None
    )


def test_without_a_threshold_nothing_is_kept(pap: Checklist) -> None:
    """No fitted pair: scored claims are 'not evaluated' (decision None), clear No's are FLAGGED."""
    result = verify_letter(letter(pap), pap, DOCS, EVIDENCE, FakeVerifier(SCORES), None, drafter="gemma4:e2b-it-qat")

    assert [c.decision for c in result.letter.claims] == [None, ClaimDecision.FLAG, ClaimDecision.DROP]
    assert result.letter.claims[0].score == 0.9
    assert result.metadata["threshold"] == "none"


def test_threshold_for_another_pair_is_rejected(pap: Checklist) -> None:
    """Applying the E4B threshold to E2B claims (or another verifier) is a caller error."""
    with pytest.raises(ConformalError, match="e2b"):
        verify_letter(letter(pap), pap, DOCS, EVIDENCE, FakeVerifier(SCORES), THRESHOLD, drafter="gemma4:e2b-it-qat")
    with pytest.raises(ConformalError, match="gemini"):
        verify_letter(letter(pap), pap, DOCS, EVIDENCE, FakeVerifier(SCORES, "gemini"), THRESHOLD, "gemma4:e4b")


def test_threshold_from_another_premise_rule_is_rejected(pap: Checklist) -> None:
    """A threshold fit on premises built by another rule can't be applied (ADR-0022)."""
    old = dataclasses.replace(THRESHOLD, premise_rule="adr-0018")
    with pytest.raises(ConformalError, match="premise rule"):
        verify_letter(letter(pap), pap, DOCS, EVIDENCE, FakeVerifier(SCORES), old, "gemma4:e4b")


def test_metadata_names_the_premise_rule(pap: Checklist) -> None:
    """Every run says which premise rule built the premises."""
    result = verify_letter(letter(pap), pap, DOCS, EVIDENCE, FakeVerifier(SCORES), None, "gemma4:e4b")
    assert result.metadata["premise_rule"] == PREMISE_RULE == THRESHOLD.premise_rule
