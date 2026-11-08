"""Tests for the deterministic citation checks: exact quotes and the criterion link (ADR-0018)."""

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
from pair.verify.span import CitationError, apply_citation_checks, check_citations

DOC = "Seen in sleep clinic on 2026-03-02. Home sleep test on 2026-03-10: AHI 18.2 events/hr."
DOCS = {"note-1": DOC, "note-2": "Other note. AHI 18.2 events/hr."}
QUOTE = "AHI 18.2 events/hr"


@pytest.fixture(scope="module")
def pap(repo_root: Path) -> Checklist:
    """The shipped PAP checklist."""
    return load_all(repo_root / "policies")["pap-osa"]


def evidence(criterion_id: str = "ahi_threshold", status: EvidenceStatus = EvidenceStatus.ASSERTED) -> Evidence:
    """The AHI span in note-1, bound to ``criterion_id``."""
    start = DOC.index(QUOTE)
    return Evidence(
        criterion_id=criterion_id, variable="ahi", value=18.2, span_text=QUOTE,
        char_start=start, char_end=start + len(QUOTE), doc_id="note-1", status=status,
    )


def claim(
    pap: Checklist,
    criterion_id: str = "ahi_threshold",
    doc_id: str = "note-1",
    quote: str = QUOTE,
    start: int | None = None,
    policy_quote: str | None = None,
    source_id: str | None = None,
) -> Claim:
    """A claim citing the AHI span; every part can be broken on purpose."""
    criterion = next(c for c in pap.criteria if c.id == criterion_id)
    begin = DOC.index(QUOTE) if start is None else start
    return Claim(
        criterion_id=criterion_id,
        text="My sleep test showed an AHI of 18.2.",
        policy_cite=PolicyCitation(
            source_id=source_id or criterion.source_id, quote=policy_quote or criterion.clause
        ),
        evidence_cite=EvidenceCitation(doc_id=doc_id, char_start=begin, char_end=begin + len(quote), quote=quote),
    )


def test_exact_citations_pass(pap: Checklist) -> None:
    """Verbatim record quote at its offsets, clause quote, link to an asserted item."""
    assert check_citations(claim(pap), pap, DOCS, [evidence()]).ok


def test_part_of_the_clause_is_a_valid_policy_quote(pap: Checklist) -> None:
    """The policy quote may be a verbatim substring of the clause."""
    clause = next(c for c in pap.criteria if c.id == "ahi_threshold").clause
    assert check_citations(claim(pap, policy_quote=clause[:60]), pap, DOCS, [evidence()]).ok


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"quote": "AHI 18.2  events/hr"}, "record quote"),
        ({"quote": "ahi 18.2 events/hr"}, "record quote"),
        ({"start": 0}, "record quote"),
        ({"doc_id": "note-2"}, "record quote"),
        ({"doc_id": "note-9"}, "unknown document"),
        ({"policy_quote": "The AHI is at least 15."}, "policy quote"),
        ({"source_id": "240.4"}, "policy quote"),
    ],
)
def test_broken_citations_fail(pap: Checklist, kwargs: dict[str, object], reason: str) -> None:
    """Whitespace, case, offsets, document and policy text are compared exactly, never normalized."""
    result = check_citations(claim(pap, **kwargs), pap, DOCS, [evidence()])  # type: ignore[arg-type]
    assert not result.ok
    assert reason in (result.reason or "")


def test_quote_bound_to_another_criterion_fails_the_link(pap: Checklist) -> None:
    """A real quote that the engine bound to another criterion is the 'wrong criterion' fault."""
    result = check_citations(claim(pap), pap, DOCS, [evidence("f2f_visit")])
    assert not result.ok and "criterion link" in (result.reason or "")


def test_negated_evidence_does_not_link(pap: Checklist) -> None:
    """Only asserted evidence can back a claim."""
    result = check_citations(claim(pap), pap, DOCS, [evidence(status=EvidenceStatus.NEGATED)])
    assert not result.ok and "criterion link" in (result.reason or "")


def test_unknown_criterion_fails(pap: Checklist) -> None:
    """A claim naming a criterion outside the checklist fails, not crashes."""
    bad = claim(pap).model_copy(update={"criterion_id": "made_up"})
    result = check_citations(bad, pap, DOCS, [evidence()])
    assert not result.ok and "made_up" in (result.reason or "")


def test_apply_drops_failures_with_score_zero_and_leaves_passes_undecided(pap: Checklist) -> None:
    """Failures become DROP with score 0; passes go on to entailment with no decision yet."""
    letter = Letter(policy_id="pap-osa", claims=[claim(pap), claim(pap, start=0)])

    checked, results = apply_citation_checks(letter, pap, DOCS, [evidence()])

    good, bad = checked.claims
    assert good.decision is None and good.score is None
    assert bad.decision is ClaimDecision.DROP and bad.score == 0.0
    assert [r.ok for r in results] == [True, False]


def test_apply_rejects_a_letter_for_another_policy(pap: Checklist) -> None:
    """Checking against the wrong checklist is a caller error."""
    with pytest.raises(CitationError, match="home-oxygen"):
        apply_citation_checks(Letter(policy_id="home-oxygen", claims=[]), pap, DOCS, [])
