"""Tests for the extraction runner on fake LangExtract output (T8)."""

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest
from langextract import data as lx_data

from pair.contracts import EvidenceStatus
from pair.extract.runner import ExtractionResult, extract_evidence, model_kwargs
from pair.llm import LLMConfig
from pair.policies.loader import load_all
from tests.conftest import REPO_ROOT

CHECKLISTS = load_all(REPO_ROOT / "policies")
NOTE = (
    "Sleep visit 01/12/2026 in person. Home sleep test 02/02/2026: AHI 18.2 events/hour, "
    "96 events. Reports daytime sleepiness. Denies morning headaches."
)


def ext(cls: str, text: str, value: str | None = None, status: str = "asserted", *, aligned: bool = True) -> lx_data.Extraction:
    """A LangExtract extraction aligned to the first occurrence of ``text`` in NOTE."""
    start = NOTE.find(text)
    interval = lx_data.CharInterval(start_pos=start, end_pos=start + len(text)) if aligned else None
    attributes: dict[str, str | list[str]] = {"status": status} if value is None else {"value": value, "status": status}
    return lx_data.Extraction(cls, text, char_interval=interval, attributes=attributes)


class FakeExtract:
    """Records kwargs and returns a fake annotated document."""

    def __init__(self, extractions: list[lx_data.Extraction]) -> None:
        self.extractions = extractions
        self.kwargs: dict[str, Any] = {}

    def __call__(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return SimpleNamespace(extractions=self.extractions)


def run(extractions: list[lx_data.Extraction], policy: str = "pap-osa") -> ExtractionResult:
    """Run the extractor on NOTE with a fake LangExtract."""
    return extract_evidence(
        NOTE, "note-1", CHECKLISTS[policy], LLMConfig.from_env({}), extract_fn=FakeExtract(extractions)
    )


def test_offsets_slice_the_document_to_span_text() -> None:
    """Every Evidence span is exactly the document slice at its offsets."""
    result = run([ext("ahi", "AHI 18.2 events/hour", "18.2"), ext("sleep_test_date", "02/02/2026", "2026-02-02")])
    assert result.n_total == 2
    assert result.n_dropped == 0
    for item in result.evidence:
        assert NOTE[item.char_start : item.char_end] == item.span_text
        assert item.doc_id == "note-1"
    by_var = {e.variable: e for e in result.evidence}
    assert by_var["ahi"].value == 18.2
    assert by_var["ahi"].criterion_id == "ahi_threshold"
    assert by_var["sleep_test_date"].value == dt.date(2026, 2, 2)
    assert by_var["sleep_test_date"].criterion_id == "f2f_visit"


def test_unaligned_extractions_are_dropped_and_counted() -> None:
    """``char_interval=None`` means ungrounded: dropped, never turned into Evidence."""
    result = run([ext("ahi", "AHI 18.2 events/hour", "18.2", aligned=False), ext("event_count", "96 events", "96")])
    assert result.n_total == 2
    assert result.n_dropped == 1
    assert [e.variable for e in result.evidence] == ["event_count"]
    assert result.grounding_rate == 0.5


def test_blank_placeholders_are_not_counted_as_extractions() -> None:
    """Empty ``extraction_text`` means "not found": counted as empty, outside the grounding rate."""
    blank = lx_data.Extraction("ahi", "", char_interval=None)
    spaces = lx_data.Extraction("event_count", "  ", char_interval=None)
    result = run([blank, spaces, ext("event_count", "96 events", "96")])
    assert result.n_empty == 2
    assert result.n_total == 1
    assert result.n_dropped == 0
    assert result.grounding_rate == 1.0


def test_unknown_class_is_dropped_and_counted() -> None:
    """A class that isn't a checklist variable is dropped."""
    result = run([ext("bmi", "AHI 18.2 events/hour", "31")])
    assert result.n_unknown == 1
    assert result.evidence == ()


def test_status_is_read_and_bad_status_is_uncertain() -> None:
    """Statuses come from attributes; an unknown status is treated as uncertain (binds nothing)."""
    result = run(
        [
            ext("symptoms_or_conditions", "daytime sleepiness", "daytime sleepiness"),
            ext("symptoms_or_conditions", "morning headaches", "morning headaches", "negated"),
            ext("event_count", "96 events", "96", "probably"),
        ]
    )
    statuses = [e.status for e in result.evidence]
    assert statuses == [EvidenceStatus.ASSERTED, EvidenceStatus.NEGATED, EvidenceStatus.UNCERTAIN]


def test_missing_status_means_asserted() -> None:
    """A model that omits the status attribute is read as asserting the fact."""
    extraction = lx_data.Extraction(
        "event_count", "96 events", char_interval=lx_data.CharInterval(start_pos=NOTE.find("96 events"), end_pos=NOTE.find("96 events") + 9)
    )
    result = run([extraction])
    assert result.evidence[0].status is EvidenceStatus.ASSERTED
    assert result.evidence[0].value == 96


def test_missing_value_falls_back_to_span_text() -> None:
    """Without a value attribute, the span text itself is normalized."""
    result = run([ext("event_count", "96 events")])
    assert result.evidence[0].value == 96


def test_unparseable_value_is_kept_as_a_mention() -> None:
    """A value that won't normalize stays as a mention with value None."""
    result = run([ext("ahi", "AHI 18.2 events/hour", "high")])
    assert result.evidence[0].value is None


def test_shared_variable_gives_one_evidence_per_criterion() -> None:
    """``spo2`` feeds both oxygen groups, so one extraction yields two Evidence items."""
    note_policy = "home-oxygen"
    result = run([ext("spo2", "AHI 18.2 events/hour", "87")], policy=note_policy)
    assert sorted(e.criterion_id for e in result.evidence) == ["group1_blood_gas", "group2_blood_gas"]
    assert all(e.value == 87 for e in result.evidence)


def test_empty_document_makes_no_call() -> None:
    """Blank text returns an empty result without calling LangExtract."""
    fake = FakeExtract([])
    result = extract_evidence("  ", "d", CHECKLISTS["pap-osa"], LLMConfig.from_env({}), extract_fn=fake)
    assert result.n_total == 0
    assert result.grounding_rate is None
    assert fake.kwargs == {}


def test_prompt_and_examples_are_passed() -> None:
    """The prompt names every variable and the policy's examples are passed."""
    fake = FakeExtract([])
    extract_evidence(NOTE, "d", CHECKLISTS["pap-osa"], LLMConfig.from_env({}), extract_fn=fake)
    prompt = fake.kwargs["prompt_description"]
    for name in ("ahi", "event_count", "symptoms_or_conditions", "reevaluation_date"):
        assert name in prompt
    assert fake.kwargs["examples"]
    assert fake.kwargs["text_or_documents"] == NOTE


def test_model_kwargs_ollama() -> None:
    """Ollama: lab URL, context window and timeout passed through, thinking off."""
    kwargs = model_kwargs(LLMConfig.from_env({"PAIR_LLM_NUM_CTX": "8192"}))
    assert kwargs["model_id"] == "gemma4:e4b"
    assert kwargs["model_url"] == "http://localhost:11435"
    assert kwargs["fence_output"] is False
    assert kwargs["temperature"] == 0.0
    assert kwargs["language_model_params"] == {"timeout": 300, "num_ctx": 8192, "think": False}


def test_model_kwargs_gemini() -> None:
    """Gemini: Vertex project/location and minimal thinking."""
    kwargs = model_kwargs(LLMConfig.from_env({"PAIR_LLM_BACKEND": "gemini"}))
    assert kwargs["model_id"] == "gemini-3.5-flash"
    params = kwargs["language_model_params"]
    assert params["vertexai"] is True
    assert params["project"] == "pair-appeal-copilot"
    assert params["location"] == "global"
    assert params["thinking_config"] == {"thinking_level": "MINIMAL"}
    assert "model_url" not in kwargs


@pytest.mark.llm
def test_live_extraction_grounds_the_ahi() -> None:
    """Real LangExtract call on the configured backend (lab tunnel or Vertex)."""
    result = extract_evidence(NOTE, "note-1", CHECKLISTS["pap-osa"], LLMConfig.from_env())
    by_var = {e.variable: e for e in result.evidence}
    assert by_var["ahi"].value == 18.2
    assert all(NOTE[e.char_start : e.char_end] == e.span_text for e in result.evidence)


def test_prompt_forbids_inference_and_non_text_spans() -> None:
    """The LLM must not turn words into numbers or put true/false in place of quoted text."""
    from pair.extract.runner import build_prompt

    prompt = build_prompt(CHECKLISTS["facet-joint"])
    assert "never turn words into numbers" in prompt
    assert "never true, false or null" in prompt


def test_parse_errors_raise_instead_of_dropping_chunks() -> None:
    """LangExtract is asked to raise on unparseable output, so nothing is dropped silently."""
    fake = FakeExtract([])
    extract_evidence(NOTE, "d", CHECKLISTS["pap-osa"], LLMConfig.from_env({}), extract_fn=fake)
    from pair.extract.tolerant_format import TolerantFormatHandler

    params = fake.kwargs["resolver_params"]
    assert params["suppress_parse_errors"] is False
    assert isinstance(params["format_handler"], TolerantFormatHandler)


class FlakyExtract(FakeExtract):
    """Raises a resolver parse error for the first ``fail`` calls."""

    def __init__(self, extractions: list[lx_data.Extraction], fail: int) -> None:
        super().__init__(extractions)
        self.fail = fail
        self.prompts: list[str] = []

    def __call__(self, **kwargs: Any) -> Any:
        from langextract.resolver import ResolverParsingError

        self.prompts.append(kwargs["prompt_description"])
        if len(self.prompts) <= self.fail:
            raise ResolverParsingError("Extraction text must be a string, integer, or float.")
        return super().__call__(**kwargs)


def test_parse_error_is_retried_once_with_a_correction() -> None:
    """A first unparseable answer is retried with a note about what went wrong."""
    fake = FlakyExtract([ext("event_count", "96 events", "96")], fail=1)
    result = extract_evidence(NOTE, "d", CHECKLISTS["pap-osa"], LLMConfig.from_env({}), extract_fn=fake)
    assert len(fake.prompts) == 2
    assert "previous answer could not be parsed" in fake.prompts[1]
    assert result.n_failed == 0
    assert [e.variable for e in result.evidence] == ["event_count"]


def test_parse_error_twice_counts_a_failed_document() -> None:
    """Two unparseable answers give no evidence and n_failed=1, never a silent empty result."""
    fake = FlakyExtract([], fail=2)
    result = extract_evidence(NOTE, "d", CHECKLISTS["pap-osa"], LLMConfig.from_env({}), extract_fn=fake)
    assert result.n_failed == 1
    assert result.evidence == ()
    assert result.grounding_rate is None


class HandlerExtract(FakeExtract):
    """Feeds raw model JSON through the format handler the runner passes in."""

    def __init__(self, raw: str, extractions: list[lx_data.Extraction]) -> None:
        super().__init__(extractions)
        self.raw = raw

    def __call__(self, **kwargs: Any) -> Any:
        kwargs["resolver_params"]["format_handler"].parse_output(self.raw)
        return super().__call__(**kwargs)


def test_malformed_items_count_as_ungrounded_and_nulls_as_empty() -> None:
    """Items the handler dropped show up in the grounding counts instead of vanishing."""
    import json

    raw = json.dumps({"extractions": [{"ahi": ["x"]}, {"event_count": None}, {"event_count": "96 events"}]})
    fake = HandlerExtract(raw, [ext("event_count", "96 events", "96")])
    result = extract_evidence(NOTE, "d", CHECKLISTS["pap-osa"], LLMConfig.from_env({}), extract_fn=fake)
    assert result.n_total == 2
    assert result.n_dropped == 1
    assert result.n_empty == 1
    assert [e.variable for e in result.evidence] == ["event_count"]


def test_pain_score_on_a_hundred_point_vas_is_rescaled() -> None:
    """A "VAS 35 mm" span binds 3.5, so it doesn't pass the 0 to 10 rule at 35 (ADR-0015)."""
    note = "Pain clinic: axial low back pain, VAS 35 mm."
    start = note.find("VAS 35 mm")
    extraction = lx_data.Extraction(
        "pain_score",
        "VAS 35 mm",
        char_interval=lx_data.CharInterval(start_pos=start, end_pos=start + 9),
        attributes={"value": "35", "status": "asserted"},
    )
    result = extract_evidence(
        note, "note-1", CHECKLISTS["facet-joint"], LLMConfig.from_env({}), extract_fn=FakeExtract([extraction])
    )
    assert [e.value for e in result.evidence] == [3.5]
