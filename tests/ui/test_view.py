"""Tests for ``CaseView``: the one model every demo screen reads (Phase 4 T2, ADR-0023)."""

import dataclasses
import re

import pytest

from pair.contracts import CriterionStatus, ReasonCategory
from pair.draft.template import LetterTemplate
from pair.pipeline import CoreRun, Resources, TrustRun
from pair.policies.select import Selection
from pair.score.strength import ShipLink
from pair.ui.view import (
    REASON_PLAIN,
    STATUS_DISPLAY,
    CaseView,
    Decision,
    ViewError,
    build_view,
    caseview_schema,
)


def criterion_ids(resources: Resources) -> set[str]:
    """Every criterion id across the shipped policies."""
    return {c.id for checklist in resources.checklists.values() for c in checklist.criteria}


def test_every_status_has_an_icon_and_a_distinct_text_label() -> None:
    """Color is never the only signal: each status has its own icon name and words."""
    assert set(STATUS_DISPLAY) == set(CriterionStatus)
    labels = [display.label for display in STATUS_DISPLAY.values()]
    icons = [display.icon for display in STATUS_DISPLAY.values()]
    assert len(set(labels)) == len(labels) and len(set(icons)) == len(icons)
    assert all(label.strip() for label in labels)


def test_every_reason_category_has_plain_words() -> None:
    """Every denial category maps to a plain sentence."""
    assert set(REASON_PLAIN) == set(ReasonCategory)
    assert all(text.endswith(".") for text in REASON_PLAIN.values())


def test_denial_shows_the_reason_and_the_rule_it_cites(view: CaseView) -> None:
    """Screen 2: the letter's own words, a plain version, and the cited LCD with its link."""
    assert view.denial is not None
    assert view.denial.reason_text.startswith("The records do not show")
    assert view.denial.reason_plain == REASON_PLAIN[ReasonCategory.INSUFFICIENT_DOCUMENTATION]
    assert view.denial.cited_rule is not None
    assert view.denial.cited_rule.label == "LCD L33718"
    assert view.denial.cited_rule.url.startswith("https://www.cms.gov/")


def test_one_row_per_criterion_with_status_text(view: CaseView, resources: Resources) -> None:
    """Screen 3: one row per criterion in checklist order, each with icon + label."""
    order = [c.id for c in resources.checklists["pap-osa"].criteria]
    assert [row.id for row in view.criteria] == order
    status = {row.id: row.status.status for row in view.criteria}
    assert status == {"f2f_visit": "insufficient", "ahi_threshold": "met", "adherence": "met", "reevaluation": "met"}
    for row in view.criteria:
        assert row.status.label == STATUS_DISPLAY[row.status.status].label
        assert row.trace and row.policy.clause


def test_rows_use_the_ui_headings(view: CaseView, ui_headings: dict[str, str]) -> None:
    """Rows, gaps and steps show the plain ``_ui.yaml`` heading, not the criterion text."""
    for row in view.criteria:
        assert row.heading == ui_headings[f"pap-osa/{row.id}"]
    assert view.gap_groups[0].items[0].heading == ui_headings["pap-osa/f2f_visit"]


def test_without_ui_headings_criterion_text_is_shown_without_tags(
    core: CoreRun, resources: Resources, template: LetterTemplate,
    ship_links: tuple[ShipLink, ...], documents: dict[str, str],
) -> None:  # fmt: skip
    """The fallback strips "(… ADR-0015)" tags from the criterion text."""
    view = build_view("x", core, None, resources, template, ship_links, documents)
    assert all("ADR" not in row.heading for row in view.criteria)
    ahi = next(row for row in view.criteria if row.id == "ahi_threshold")
    assert ahi.heading.endswith("(10 with symptoms)")


def test_every_quote_slices_its_document(view: CaseView) -> None:
    """Record quotes and letter citations point at the exact characters, so the UI can highlight them."""
    texts = {doc.doc_id: doc.text for doc in view.documents}
    spans = [span for row in view.criteria for span in row.quotes]
    assert view.letter is not None
    spans += [s.record for s in [*view.letter.sentences, *view.letter.unconfirmed]]
    assert spans
    for span in spans:
        assert texts[span.doc_id][span.char_start : span.char_end] == span.quote


def test_documents_keep_their_titles(view: CaseView, titles: dict[str, str]) -> None:
    """The source panel shows each record's title."""
    assert {doc.doc_id: doc.title for doc in view.documents} == titles


def test_gaps_grouped_by_who_to_ask(view: CaseView) -> None:
    """Screen 4: the insufficient f2f visit is listed under the doctor's office with its message."""
    assert [group.who for group in view.gap_groups] == ["Your doctor's office"]
    (item,) = view.gap_groups[0].items
    assert item.criterion_id == "f2f_visit"
    assert item.status.status is CriterionStatus.INSUFFICIENT
    assert item.message.startswith("Ask your doctor's office")


def test_unmet_gaps_go_to_the_doctor(
    core: CoreRun, trust: TrustRun, resources: Resources, template: LetterTemplate,
    ship_links: tuple[ShipLink, ...], documents: dict[str, str],
) -> None:  # fmt: skip
    """An unmet criterion has no record to fetch, so its advice is grouped under the doctor."""
    assert core.verdict is not None
    results = [
        r.model_copy(update={"status": CriterionStatus.UNMET}) if r.criterion_id == "f2f_visit" else r
        for r in core.verdict.results
    ]
    gaps = [g.model_copy(update={"message": "Ask about other options."}) for g in core.verdict.gaps]
    verdict = core.verdict.model_copy(update={"results": results, "gaps": gaps})
    unmet = build_view("x", dataclasses.replace(core, verdict=verdict), trust, resources, template, ship_links, documents)
    assert [group.who for group in unmet.gap_groups] == ["Your doctor"]


def test_letter_sentences_are_located_in_the_letter_text(view: CaseView) -> None:
    """Screen 5: each shown sentence has offsets into the letter so the UI can make it clickable."""
    assert view.letter is not None
    shown = view.letter.sentences
    assert len(shown) == 8
    for sentence in shown:
        assert sentence.letter_start is not None and sentence.letter_end is not None
        assert view.letter.text[sentence.letter_start : sentence.letter_end] == sentence.text
        assert sentence.decision in (Decision.KEPT, Decision.QUOTED)
    starts = [s.letter_start for s in shown]
    assert starts == sorted(starts)


def test_flagged_claims_are_listed_but_never_in_the_letter(view_flagged: CaseView) -> None:
    """A FLAGGED claim is shown as "not confirmed" next to the letter, not inside it."""
    view = view_flagged
    assert view.letter is not None
    (flagged,) = view.letter.unconfirmed
    assert flagged.decision is Decision.FLAGGED
    assert flagged.letter_start is None
    assert flagged.text not in view.letter.text
    assert "confirm" in flagged.decision_label.lower()


def test_not_argued_criteria_explain_why(view: CaseView) -> None:
    """f2f is left out of the letter, and the patient is told why and what to get."""
    assert view.letter is not None
    (item,) = view.letter.not_argued
    assert item.criterion_id == "f2f_visit"
    assert item.message.startswith("Ask your doctor's office")


def test_abstain_shows_no_number_anywhere(view: CaseView) -> None:
    """Screen 6, get a human: no point estimate, no range, no 'if fixed' numbers."""
    strength = view.strength
    assert strength is not None and strength.abstain
    assert strength.p is None and strength.low is None and strength.high is None
    assert all(item.p_if_fixed is None for item in strength.improve)
    assert strength.reason is not None and view.help_links


def test_patient_text_names_no_criterion_ids(view: CaseView, resources: Resources) -> None:
    """Internal ids like ``f2f_visit`` are replaced by plain headings in reasons and steps."""
    assert view.strength is not None and view.strength.reason is not None
    texts = [view.strength.reason, *(item.action for item in view.strength.improve)]
    for text in texts:
        for cid in criterion_ids(resources):
            assert not re.search(rf"\b{cid}\b", text), (cid, text)
    assert view.strength.reason == "A required item has no record yet: a visit in person with your doctor before your sleep test."


def test_scored_strength_shows_range_steps_and_what_helps(
    core: CoreRun, trust: TrustRun, resources: Resources, template: LetterTemplate,
    ship_links: tuple[ShipLink, ...], documents: dict[str, str],
) -> None:  # fmt: skip
    """Screen 6, scored: point and range, one step per active criterion, a 'what helps' with its number."""
    assert trust.strength is not None
    scored = trust.strength.model_copy(update={"abstain": False, "abstain_reason": None})
    view = build_view(
        "x", core, dataclasses.replace(trust, strength=scored), resources, template, ship_links, documents
    )
    strength = view.strength
    assert strength is not None and not strength.abstain and strength.reason is None
    assert strength.p == pytest.approx(scored.p)
    assert (strength.low, strength.high) == (scored.interval.low, scored.interval.high)
    assert [step.criterion_id for step in strength.steps] == [s.criterion_id for s in scored.explanation.steps]
    effects = {step.criterion_id: step.effect for step in strength.steps}
    assert effects["f2f_visit"] == "lowers" and effects["ahi_threshold"] == "raises"
    (helps,) = strength.improve
    assert helps.p_if_fixed is not None and helps.p_if_fixed > strength.p
    assert strength.data_note.startswith("Based on California")


def test_core_only_run_has_no_letter_or_strength(
    core: CoreRun, resources: Resources, template: LetterTemplate,
    ship_links: tuple[ShipLink, ...], documents: dict[str, str],
) -> None:  # fmt: skip
    """Without steps 5 to 7 the view still shows the verdict and gaps."""
    view = build_view("x", core, None, resources, template, ship_links, documents)
    assert view.supported and view.letter is None and view.strength is None
    assert view.criteria and view.gap_groups


def test_unsupported_denial_says_so_and_points_to_help(
    core: CoreRun, resources: Resources, template: LetterTemplate,
    ship_links: tuple[ShipLink, ...], documents: dict[str, str],
) -> None:  # fmt: skip
    """No checklist applies: no rows, no letter, the reason, and the help links."""
    unsupported = dataclasses.replace(
        core, selection=Selection(None, "no modeled policy for code L1832"), extractions={}, verdict=None
    )
    view = build_view("x", unsupported, None, resources, template, ship_links, documents)
    assert not view.supported and view.unsupported_reason
    assert view.criteria == [] and view.gap_groups == [] and view.letter is None and view.strength is None
    assert view.overall is None and view.help_links


def test_unreadable_denial_has_no_denial_section(
    core: CoreRun, resources: Resources, template: LetterTemplate,
    ship_links: tuple[ShipLink, ...], documents: dict[str, str],
) -> None:  # fmt: skip
    """A denial PAIR couldn't read still produces a view that says so."""
    failed = dataclasses.replace(
        core, denial=None, denial_error="bad JSON", selection=Selection(None, "unsupported: unreadable"),
        extractions={}, verdict=None,
    )  # fmt: skip
    view = build_view("x", failed, None, resources, template, ship_links, documents)
    assert view.denial is None and not view.supported


def test_trust_run_for_a_core_without_verdict_is_rejected(
    core: CoreRun, trust: TrustRun, resources: Resources, template: LetterTemplate,
    ship_links: tuple[ShipLink, ...], documents: dict[str, str],
) -> None:  # fmt: skip
    """A letter can't exist without a verdict."""
    with pytest.raises(ViewError, match="verdict"):
        build_view("x", dataclasses.replace(core, verdict=None), trust, resources, template, ship_links, documents)


def test_letter_that_lost_a_sentence_is_rejected(
    core: CoreRun, trust: TrustRun, resources: Resources, template: LetterTemplate,
    ship_links: tuple[ShipLink, ...], documents: dict[str, str],
) -> None:  # fmt: skip
    """If a shown claim isn't in the rendered text, offsets would be wrong, so the view refuses."""
    rendered = dataclasses.replace(trust.rendered, text=trust.rendered.text.replace("My records state", "Records"))
    with pytest.raises(ViewError, match="not found"):
        build_view("x", core, dataclasses.replace(trust, rendered=rendered), resources, template, ship_links, documents)


def test_safety_notice_and_run_info(view: CaseView, template: LetterTemplate) -> None:
    """The safety notice is the letter's notice; run info names the drafter, verifier and threshold."""
    assert view.safety_notice == template.notice
    assert view.run["drafter"] == "fake-drafter"
    assert view.run["verifier_backend"] == "minicheck" and view.run["threshold"] == "fitted"
    assert view.mode == "cached" and view.schema_version == 1


def test_json_round_trip(view: CaseView) -> None:
    """The cache stores views as JSON and reads them back unchanged."""
    assert CaseView.model_validate_json(view.model_dump_json()) == view


def test_schema_is_stable_and_names_every_screen_section() -> None:
    """The JSON Schema that generates the TypeScript types is deterministic."""
    schema = caseview_schema()
    assert schema == caseview_schema()
    assert schema["title"] == "CaseView"
    assert {"denial", "criteria", "gap_groups", "letter", "strength", "documents", "safety_notice"} <= set(
        schema["properties"]
    )


def test_importing_the_view_loads_no_llm_code() -> None:
    """Cached mode reads ``CaseView`` with Ollama off, so the view module must not pull in LLM code."""
    import subprocess
    import sys

    code = (
        "import sys, pair.ui.view; "
        "bad = sorted(m for m in sys.modules if m == 'langextract' or m.startswith(('langextract.', 'pair.llm', "
        "'pair.pipeline', 'pair.verify.nli', 'pair.extract', 'google.genai'))); print(','.join(bad))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == ""


def test_flagged_claim_of_a_met_criterion_is_quoted_word_for_word(view: CaseView) -> None:
    """ADR-0024: the fixture's flagged claim argues a met criterion, so the letter quotes its record sentence."""
    assert view.letter is not None
    quoted = [s for s in view.letter.sentences if s.decision is Decision.QUOTED]
    assert quoted, "expected the flagged paraphrase to be replaced by a quote"
    texts = {d.doc_id: d.text for d in view.documents}
    met = {row.id for row in view.criteria if row.status.status == "met"}
    for sentence in quoted:
        assert sentence.criterion_id in met
        assert "word for word" in sentence.decision_label
        assert texts[sentence.record.doc_id][sentence.record.char_start : sentence.record.char_end] == sentence.record.quote
        assert sentence.record.quote in sentence.text
        assert view.letter.text.count(sentence.record.quote) == 1  # not repeated by the record citation
    for flagged in view.letter.unconfirmed:
        assert flagged.criterion_id not in met or any(
            s.criterion_id == flagged.criterion_id and s.decision is Decision.KEPT for s in view.letter.sentences
        )
