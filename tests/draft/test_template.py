"""Tests for the letter skeleton and rendering (ADR-0018, ADR-0020 'what the patient sees')."""

import datetime as dt
import logging
from pathlib import Path

import pytest

from pair.contracts import (
    Checklist,
    Claim,
    ClaimDecision,
    Denial,
    EvidenceCitation,
    Letter,
    PolicyCitation,
)
from pair.draft.template import (
    LetterTemplate,
    LetterTemplateError,
    load_letter_template,
    render_letter,
)
from pair.policies.loader import load_all

DOC = "Seen in sleep clinic on 2026-03-02. Home sleep test on 2026-03-10: AHI 18.2 events/hr."


@pytest.fixture(scope="module")
def pap(repo_root: Path) -> Checklist:
    """The shipped PAP checklist."""
    return load_all(repo_root / "policies")["pap-osa"]


@pytest.fixture(scope="module")
def template(repo_root: Path) -> LetterTemplate:
    """The shipped letter template."""
    return load_letter_template(repo_root / "policies" / "_letter.yaml")


def denial(plan_type: str = "medicare_advantage") -> Denial:
    """A synthetic PAP denial."""
    return Denial(
        service="CPAP device",
        codes=["E0601"],
        reason_text="Records do not show a qualifying sleep test.",
        reason_category="criteria_not_met",  # type: ignore[arg-type]
        policy_ref="L33718",
        plan_type=plan_type,  # type: ignore[arg-type]
        date=dt.date(2026, 9, 1),
    )


def claim(
    pap: Checklist, criterion_id: str, quote: str, text: str, decision: ClaimDecision | None = ClaimDecision.KEEP
) -> Claim:
    """A claim citing ``quote`` in ``DOC`` and its criterion's clause."""
    criterion = next(c for c in pap.criteria if c.id == criterion_id)
    start = DOC.index(quote)
    return Claim(
        criterion_id=criterion_id,
        text=text,
        policy_cite=PolicyCitation(source_id=criterion.source_id, quote=criterion.clause),
        evidence_cite=EvidenceCitation(doc_id="note-1", char_start=start, char_end=start + len(quote), quote=quote),
        score=None if decision is None else 0.9,
        decision=decision,
    )


def letter(pap: Checklist, *claims: Claim) -> Letter:
    """A PAP letter."""
    return Letter(policy_id=pap.id, claims=list(claims))


def two_criteria(pap: Checklist, ahi_decision: ClaimDecision | None = ClaimDecision.KEEP) -> Letter:
    """f2f_visit with two KEPT claims, ahi_threshold with one claim of the given decision."""
    return letter(
        pap,
        claim(pap, "ahi_threshold", "AHI 18.2 events/hr", "My sleep test showed an AHI of 18.2.", ahi_decision),
        claim(pap, "f2f_visit", "Seen in sleep clinic on 2026-03-02", "I saw my doctor on 2026-03-02."),
        claim(pap, "f2f_visit", "Home sleep test on 2026-03-10", "My home sleep test was on 2026-03-10."),
    )


def test_shipped_template_has_no_dashes(template: LetterTemplate) -> None:
    """Letter text follows the writing rules: no em or en dashes."""
    for value in [*template.model_dump(exclude={"headings"}).values(), *template.headings.values()]:
        assert "—" not in value and "–" not in value


def test_every_shipped_criterion_has_a_first_person_heading(template: LetterTemplate, repo_root: Path) -> None:
    """Headings are in the patient's voice, carry no internal tags and match the shipped criteria exactly."""
    keys = {f"{c.id}/{criterion.id}" for c in load_all(repo_root / "policies").values() for criterion in c.criteria}
    assert set(template.headings) == keys
    for heading in template.headings.values():
        words = set(heading.lower().replace(",", " ").replace(".", " ").split())
        assert "adr" not in heading.lower() and not words & {"you", "your"}


def test_heading_comes_from_template_with_criterion_text_fallback(pap: Checklist, template: LetterTemplate) -> None:
    """The letter shows the template heading; a criterion without one falls back to its text."""
    text = render_letter(two_criteria(pap), pap, denial(), template).text
    assert f"Requirement: {template.headings['pap-osa/ahi_threshold']}" in text
    assert "(ADR-0015)" not in text
    bare = template.model_copy(update={"headings": {}})
    ahi = next(c for c in pap.criteria if c.id == "ahi_threshold")
    assert f"Requirement: {ahi.text}" in render_letter(two_criteria(pap), pap, denial(), bare).text


def test_unknown_placeholder_is_rejected(tmp_path: Path, repo_root: Path) -> None:
    """A typo in a placeholder fails at load time, not mid-letter."""
    text = (repo_root / "policies" / "_letter.yaml").read_text().replace("{service}", "{servise}", 1)
    path = tmp_path / "_letter.yaml"
    path.write_text(text)

    with pytest.raises(LetterTemplateError, match="servise"):
        load_letter_template(path)


def test_missing_section_is_rejected(tmp_path: Path) -> None:
    """Every section must be present."""
    path = tmp_path / "_letter.yaml"
    path.write_text("header: hi\n")

    with pytest.raises(LetterTemplateError):
        load_letter_template(path)


def test_letter_has_every_section_in_order(pap: Checklist, template: LetterTemplate) -> None:
    """Header, subject, denial reference, CMS-4201-F argument, paragraphs, closing, notice."""
    rendered = render_letter(two_criteria(pap), pap, denial(), template)
    text = rendered.text

    markers = ["[Your name]", "Re:", "Records do not show a qualifying sleep test.", "CMS-4201-F",
               "Requirement:", "Sincerely", "not legal or medical advice"]
    positions = [text.index(marker) for marker in markers]
    assert positions == sorted(positions)
    assert "E0601" in text and "LCD L33718" in text


def test_paragraphs_follow_checklist_order(pap: Checklist, template: LetterTemplate) -> None:
    """f2f_visit comes before ahi_threshold even though the letter lists ahi first."""
    text = render_letter(two_criteria(pap), pap, denial(), template).text

    f2f, ahi = template.headings["pap-osa/f2f_visit"], template.headings["pap-osa/ahi_threshold"]
    assert text.index(f2f) < text.index(ahi)
    assert text.index("2026-03-02.") < text.index("2026-03-10.")


def test_each_paragraph_quotes_clause_and_cites_records(pap: Checklist, template: LetterTemplate) -> None:
    """Every argued criterion quotes its clause; every claim sentence carries its record quote."""
    text = render_letter(two_criteria(pap), pap, denial(), template).text

    for criterion_id in ("f2f_visit", "ahi_threshold"):
        clause = next(c for c in pap.criteria if c.id == criterion_id).clause
        assert clause in text
    assert '(Record note-1: "AHI 18.2 events/hr")' in text


def test_all_kept_criterion_gets_a_conclusion(pap: Checklist, template: LetterTemplate) -> None:
    """A conclusion sentence per criterion whose claims are all KEPT."""
    rendered = render_letter(two_criteria(pap), pap, denial(), template)

    assert rendered.text.count(template.conclusion) == 2
    assert rendered.unconfirmed == () and rendered.not_evaluated == ()


def test_flagged_claim_is_removed_listed_and_blocks_conclusion(pap: Checklist, template: LetterTemplate) -> None:
    """FLAGGED: out of the text, listed separately, and its criterion loses the conclusion."""
    rendered = render_letter(
        letter(
            pap,
            claim(pap, "ahi_threshold", "AHI 18.2 events/hr", "My AHI was 18.2.", ClaimDecision.FLAG),
            claim(pap, "ahi_threshold", "Home sleep test on 2026-03-10", "I had a home sleep test."),
            claim(pap, "f2f_visit", "Seen in sleep clinic on 2026-03-02", "I saw my doctor on 2026-03-02."),
        ),
        pap,
        denial(),
        template,
    )

    assert "My AHI was 18.2." not in rendered.text
    assert [c.text for c in rendered.unconfirmed] == ["My AHI was 18.2."]
    assert "I had a home sleep test." in rendered.text
    assert rendered.text.count(template.conclusion) == 1


def test_not_evaluated_claim_is_shown_but_never_concluded(pap: Checklist, template: LetterTemplate) -> None:
    """No verifier decision: shown, listed as not evaluated, no conclusion for that criterion."""
    rendered = render_letter(two_criteria(pap, ahi_decision=None), pap, denial(), template)

    assert "My sleep test showed an AHI of 18.2." in rendered.text
    assert [c.criterion_id for c in rendered.not_evaluated] == ["ahi_threshold"]
    assert rendered.text.count(template.conclusion) == 1


def test_dropped_claim_is_removed_and_recorded(pap: Checklist, template: LetterTemplate) -> None:
    """DROP (failed span or link check): out of the text, kept for the logs."""
    rendered = render_letter(two_criteria(pap, ahi_decision=ClaimDecision.DROP), pap, denial(), template)

    assert "AHI of 18.2" not in rendered.text
    assert [c.criterion_id for c in rendered.dropped] == ["ahi_threshold"]
    assert rendered.unargued == ("ahi_threshold",)


def test_criterion_with_no_shown_claim_has_no_paragraph(pap: Checklist, template: LetterTemplate) -> None:
    """If every claim of a criterion is removed, its paragraph and clause quote go too."""
    rendered = render_letter(two_criteria(pap, ahi_decision=ClaimDecision.FLAG), pap, denial(), template)

    ahi = next(c for c in pap.criteria if c.id == "ahi_threshold")
    assert ahi.text not in rendered.text
    assert rendered.unargued == ("ahi_threshold",)


def test_cms_argument_only_for_medicare_advantage(
    pap: Checklist, template: LetterTemplate, caplog: pytest.LogCaptureFixture
) -> None:
    """CMS-4201-F binds MA plans only; for another plan type it is left out and logged."""
    with caplog.at_level(logging.WARNING):
        text = render_letter(two_criteria(pap), pap, denial("other"), template).text

    assert "CMS-4201-F" not in text
    assert "not Medicare Advantage" in caplog.text


def test_letter_for_another_policy_is_rejected(pap: Checklist, template: LetterTemplate) -> None:
    """The letter and checklist must be for the same policy."""
    other = Letter(policy_id="home-oxygen", claims=[])

    with pytest.raises(LetterTemplateError, match="home-oxygen"):
        render_letter(other, pap, denial(), template)


def test_claim_for_unknown_criterion_is_rejected(pap: Checklist, template: LetterTemplate) -> None:
    """A claim naming a criterion outside the checklist is an error."""
    bad = claim(pap, "f2f_visit", "Seen in sleep clinic on 2026-03-02", "x.").model_copy(
        update={"criterion_id": "made_up"}
    )

    with pytest.raises(LetterTemplateError, match="made_up"):
        render_letter(letter(pap, bad), pap, denial(), template)


def test_empty_letter_keeps_frame_without_requirement_section(pap: Checklist, template: LetterTemplate) -> None:
    """With every claim removed, the letter still has its frame but no 'below I show' line."""
    rendered = render_letter(
        letter(pap, claim(pap, "f2f_visit", "Seen in sleep clinic on 2026-03-02", "x.", ClaimDecision.FLAG)),
        pap,
        denial(),
        template,
    )

    assert template.policy_intro not in rendered.text
    assert "Requirement:" not in rendered.text
    assert "Sincerely" in rendered.text and "not legal or medical advice" in rendered.text
    assert rendered.unargued == ("f2f_visit",)


def test_sentence_that_already_quotes_its_record_gets_a_short_cite(pap: Checklist, template: LetterTemplate) -> None:
    """A verbatim-quote sentence (the wording fallback) cites the record id only, not the quote twice."""
    quote = "AHI 18.2 events/hr"
    rendered = render_letter(
        letter(pap, claim(pap, "ahi_threshold", quote, f'My records state: "{quote}".')), pap, denial(), template
    )

    assert rendered.text.count(quote) == 1
    assert template.record_ref.format(doc_id="note-1") in rendered.text


@pytest.mark.parametrize("policy_id", ["pap-osa", "home-oxygen", "facet-joint"])
def test_full_letter_uses_headings_not_criterion_text(
    policy_id: str, template: LetterTemplate, repo_root: Path
) -> None:
    """A letter arguing every criterion of a shipped policy uses headings, never the patient-facing criterion text."""
    checklist = load_all(repo_root / "policies")[policy_id]
    record = "Record line for the requirement."
    claims = [
        Claim(
            criterion_id=criterion.id,
            text="My records show this.",
            policy_cite=PolicyCitation(source_id=criterion.source_id, quote=criterion.clause),
            evidence_cite=EvidenceCitation(doc_id="note-1", char_start=0, char_end=len(record), quote=record),
            score=0.9,
            decision=ClaimDecision.KEEP,
        )
        for criterion in checklist.criteria
    ]
    text = render_letter(Letter(policy_id=policy_id, claims=claims), checklist, denial(), template).text
    assert "ADR" not in text
    assert text.count("Requirement: ") == len(checklist.criteria)
    for criterion in checklist.criteria:
        heading = template.headings[f"{policy_id}/{criterion.id}"]
        assert f"Requirement: {heading}" in text
        if criterion.text != heading:
            assert criterion.text not in text


def test_quote_sentence_is_shown_and_counts_like_kept(pap: Checklist, template: LetterTemplate) -> None:
    """ADR-0024: a QUOTE sentence is in the text, not listed as unconfirmed, and allows the conclusion."""
    quote = claim(pap, "ahi_threshold", "AHI 18.2 events/hr", 'My records state: "AHI 18.2 events/hr".', ClaimDecision.QUOTE)
    rendered = render_letter(
        letter(pap, quote, claim(pap, "f2f_visit", "Seen in sleep clinic on 2026-03-02", "I saw my doctor.")),
        pap, denial(), template,
    )  # fmt: skip

    assert 'My records state: "AHI 18.2 events/hr".' in rendered.text
    assert rendered.unconfirmed == () and rendered.not_evaluated == ()
    assert rendered.text.count(template.conclusion) == 2
