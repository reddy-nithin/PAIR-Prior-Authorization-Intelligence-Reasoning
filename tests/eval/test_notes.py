"""Planted-span check and the retrying note writer (T9). The LLM is faked."""

import random

import pytest

from pair.eval.cases import CaseType
from pair.eval.synth.notes import (
    HEADER,
    NoteGenerationError,
    build_prompt,
    check_notes,
    write_notes,
)
from pair.eval.synth.planners import DATES, UNITS, plan_from_states
from pair.llm import LLMResponseError
from pair.policies.loader import load_all
from tests.conftest import REPO_ROOT
from tests.eval.helpers import PROFILE, PhraseWriter

CHECKLISTS = load_all(REPO_ROOT / "policies")


def spec_with(policy_id: str = "pap-osa", **states: str):  # type: ignore[no-untyped-def]
    """A verified spec with all units present except the given ones."""
    rng = random.Random(5)
    all_states = {u.name: "present" for u in UNITS[policy_id]}
    all_states.update(states)
    return plan_from_states(CHECKLISTS[policy_id], CaseType.TRICKY, all_states, DATES[policy_id](rng), rng)


def test_prompt_lists_phrases_per_document_and_absent_topics() -> None:
    """The prompt asks for each phrase in its document and names what to leave out."""
    spec = spec_with(ahi_threshold="absent")
    prompt = build_prompt(spec, PROFILE, "PAP for sleep apnea")
    for plant in spec.plants:
        assert f'- "{plant.phrase}"' in prompt
    assert "Leave these out completely" in prompt
    assert "71-year-old woman" in prompt
    assert "Hypertension" in prompt


def test_check_catches_a_missing_phrase() -> None:
    """A phrase missing from its note is a problem."""
    spec = spec_with()
    texts = {"clinic": "nothing here", "report": "nothing"}
    problems = check_notes(spec, texts)
    assert any("AHI 22.4 events/hour" in p for p in problems)


def test_check_catches_leaked_absent_values() -> None:
    """An absent unit's values leaking into the notes is a problem."""
    spec = spec_with(ahi_threshold="absent")
    texts = {p.doc_id: "" for p in spec.plants}
    for plant in spec.plants:
        texts[plant.doc_id] += plant.phrase + " "
    assert check_notes(spec, texts) == []
    texts["report"] += "AHI was 30."
    assert any("AHI" in p for p in check_notes(spec, texts))


def test_writer_passes_first_time_and_adds_header() -> None:
    """Notes that contain every phrase are accepted on attempt 1, with the synthetic header."""
    written = write_notes(spec_with(), PROFILE, "PAP", PhraseWriter())
    assert written.attempts == 1
    assert all(note.text.startswith(HEADER) for note in written.notes)
    assert [n.doc_id for n in written.notes] == ["clinic", "report"]


def test_writer_retries_with_the_problem() -> None:
    """A missing phrase is fed back and the second attempt can pass."""
    writer = PhraseWriter(drop="AHI 22.4 events/hour", fail_times=1)
    written = write_notes(spec_with(), PROFILE, "PAP", writer)
    assert written.attempts == 2
    assert "AHI 22.4 events/hour" in writer.prompts[1].split("rejected:")[1]


def test_writer_gives_up_after_max_attempts() -> None:
    """Three failed checks raise NoteGenerationError."""
    writer = PhraseWriter(drop="AHI 22.4 events/hour", fail_times=99)
    with pytest.raises(NoteGenerationError, match="planted-span"):
        write_notes(spec_with(), PROFILE, "PAP", writer)
    assert len(writer.prompts) == 3


def test_writer_retries_after_bad_json() -> None:
    """A non-JSON reply counts as a failed attempt."""

    class Flaky(PhraseWriter):
        def generate_json(self, prompt, schema):  # type: ignore[no-untyped-def]
            if not self.prompts:
                self.prompts.append(prompt)
                raise LLMResponseError("not json")
            return super().generate_json(prompt, schema)

    written = write_notes(spec_with(), PROFILE, "PAP", Flaky())
    assert written.attempts == 2


def test_male_profile_wording() -> None:
    """Sex is described in plain words."""
    profile = PROFILE.model_copy(update={"sex": "M", "conditions": []})
    prompt = build_prompt(spec_with(), profile, "PAP")
    assert "71-year-old man" in prompt
    assert "none notable" in prompt


def test_check_ignores_capitalization_and_gold_span_uses_note_text() -> None:
    """A phrase written mid-sentence in lower case still counts; the gold span is the note's own text."""
    from pair.eval.synth.planners import planted_evidence

    spec = spec_with("facet-joint")
    texts = {p.doc_id: "" for p in spec.plants}
    for plant in spec.plants:
        texts[plant.doc_id] += "Exam: " + plant.phrase.lower() + ". "
    assert check_notes(spec, texts) == []
    for item in planted_evidence(spec.plants, texts):
        assert texts[item.doc_id][item.char_start : item.char_end] == item.span_text
        assert item.span_text == item.span_text.lower()


@pytest.mark.parametrize(
    ("policy_id", "unit", "leak"),
    [
        ("facet-joint", "no_untreated_radiculopathy", "He denies any radiating leg pain or radiculopathy."),
        ("facet-joint", "no_other_pathology", "MRI shows no fracture."),
        ("facet-joint", "duration_and_conservative_care", "Pain for 6 months despite physical therapy."),
        ("home-oxygen", "home_benefit", "Oxygen is expected to help."),
        ("home-oxygen", "qualified_tester", "The test was performed by the hospital laboratory."),
        ("pap-osa", "reevaluation", "Follow-up in clinic went well."),
        ("facet-joint", "pain_and_function", "She reports moderate low back pain."),
        ("facet-joint", "no_untreated_radiculopathy", "Leg pain with walking suggests neurogenic claudication."),
        ("facet-joint", "no_untreated_radiculopathy", "There is no associated weakness or numbness."),
        ("facet-joint", "no_untreated_radiculopathy", "Neurological exam is grossly intact."),
        ("facet-joint", "no_untreated_radiculopathy", "Neuro intact."),
        ("facet-joint", "no_untreated_radiculopathy", "Non-radiating low back pain."),
    ],
)
def test_absent_units_catch_leaks(policy_id: str, unit: str, leak: str) -> None:
    """When a unit is absent, the writer mentioning its facts anyway is caught."""
    spec = spec_with(policy_id, **{unit: "absent"})
    texts = {p.doc_id: "" for p in spec.plants}
    for plant in spec.plants:
        texts[plant.doc_id] += plant.phrase + ". "
    assert check_notes(spec, texts) == []
    texts["clinic"] = texts.get("clinic", "") + leak
    assert check_notes(spec, texts)


def test_prompt_forbids_mentioning_absent_topics_even_as_negations() -> None:
    """'No weakness or numbness' fills a radiculopathy gap, so absent topics can't be negated either (seed-10)."""
    prompt = build_prompt(spec_with("facet-joint", no_untreated_radiculopathy="absent"), PROFILE, "facet")
    assert "not even to say they are absent or normal" in prompt


def test_pap_prompt_puts_ahi_in_the_diagnostic_study() -> None:
    """The LCD measures AHI without PAP, so the AHI must not read as a CPAP-download value (pap-osa-08)."""
    prompt = build_prompt(spec_with(), PROFILE, "PAP")
    assert "diagnostic sleep test, done before CPAP" in prompt
    assert "never as CPAP device data" in prompt


def test_facet_prompt_dates_notes_and_keeps_rfa_planned() -> None:
    """Facet notes carry the visit date, and the requested RFA hasn't been done yet."""
    spec = spec_with("facet-joint")
    prompt = build_prompt(spec, PROFILE, "facet")
    assert spec.dates["visit"].strftime("%m/%d/%Y") in prompt
    assert "has not been done yet" in prompt


@pytest.mark.parametrize(("sex", "pronouns"), [("F", "she/her"), ("M", "he/him")])
def test_prompt_names_pronouns_for_the_profile_sex(sex: str, pronouns: str) -> None:
    """The writer is told which pronouns to use (pap-osa-04 called a woman "He")."""
    profile = PROFILE.model_copy(update={"sex": sex})
    assert f"Refer to the patient as {pronouns}" in build_prompt(spec_with(), profile, "PAP")
