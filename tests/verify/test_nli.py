"""Tests for the entailment verifier: premise building, P(Yes) from log-probabilities, backends (ADR-0018)."""

import json
import math
from types import SimpleNamespace
from typing import Any

import pytest

from pair.llm import LLMError
from pair.verify.nli import (
    MAX_SIDE_CHARS,
    GeminiJudge,
    MiniCheckClient,
    VerifierBackend,
    VerifierConfig,
    VerifierConfigError,
    VerifierResponseError,
    build_premise,
    make_verifier,
    p_yes,
)

NOTE = "Seen in clinic. Home sleep test on 2026-03-10: AHI 18.2 events/hr, mild. Follow up in 6 weeks."
QUOTE = "AHI 18.2 events/hr"


def span(document: str, quote: str) -> tuple[int, int]:
    """Offsets of ``quote`` in ``document``."""
    start = document.index(quote)
    return start, start + len(quote)


# --- premise -------------------------------------------------------------------------------


def test_premise_completes_the_quote_to_its_own_sentence() -> None:
    """From the start of the quote's sentence to the end of it, no neighbors."""
    assert build_premise(NOTE, *span(NOTE, QUOTE)) == "Home sleep test on 2026-03-10: AHI 18.2 events/hr, mild."


def test_premise_stops_at_line_breaks() -> None:
    """A line break ends a sentence in clinical notes."""
    note = "HPI\nAHI 18.2 events/hr on home test\nPlan: CPAP"
    assert build_premise(note, *span(note, QUOTE)) == "AHI 18.2 events/hr on home test"


def test_premise_clips_at_document_edges() -> None:
    """A quote at the very start or end of a document needs no boundary."""
    assert build_premise(QUOTE, 0, len(QUOTE)) == QUOTE


def test_premise_is_capped_on_each_side() -> None:
    """Without a boundary, at most ``MAX_SIDE_CHARS`` on each side."""
    note = "x" * 500 + QUOTE + "y" * 500
    premise = build_premise(note, *span(note, QUOTE))
    assert premise == "x" * MAX_SIDE_CHARS + QUOTE + "y" * MAX_SIDE_CHARS


@pytest.mark.parametrize("opener", ["This", "That", "These", "Those", "It", "They", "Such"])
def test_referring_opener_adds_the_previous_sentence(opener: str) -> None:
    """ADR-0022: a sentence opening with a referring word gets the sentence before it."""
    note = f"Visit note. The patient used CPAP 6.2 hours per night. {opener} gave AHI 18.2 events/hr overall."
    assert build_premise(note, *span(note, QUOTE)) == (
        f"The patient used CPAP 6.2 hours per night. {opener} gave AHI 18.2 events/hr overall."
    )


def test_quote_that_starts_with_the_opener_still_counts() -> None:
    """The opener can be the first word of the quote itself."""
    note = "Download: 131 events. This yields AHI 18.2 events/hr."
    assert build_premise(note, *span(note, "This yields AHI 18.2")) == note


def test_previous_sentence_across_a_line_break() -> None:
    """The previous sentence can be the previous line."""
    note = "Download: 131 events over 6.2 hours\nThis yields an AHI 18.2 events/hr."
    assert build_premise(note, *span(note, QUOTE)) == "Download: 131 events over 6.2 hours\nThis yields an AHI 18.2 events/hr."


@pytest.mark.parametrize("opener", ["He", "She", "His", "Her", "Thisbe", "this", "The"])
def test_other_openers_keep_the_own_sentence(opener: str) -> None:
    """Patient pronouns, lowercase and words that only start with a trigger don't count."""
    note = f"Earlier sentence. {opener} had AHI 18.2 events/hr."
    assert build_premise(note, *span(note, QUOTE)) == f"{opener} had AHI 18.2 events/hr."


def test_only_one_sentence_back() -> None:
    """If the previous sentence also opens with a trigger, nothing more is added."""
    note = "Base fact. This came next. It showed AHI 18.2 events/hr."
    assert build_premise(note, *span(note, QUOTE)) == "This came next. It showed AHI 18.2 events/hr."


def test_referring_opener_at_document_start_adds_nothing() -> None:
    """No previous sentence: the own sentence alone."""
    note = "This study showed AHI 18.2 events/hr."
    assert build_premise(note, *span(note, QUOTE)) == note


def test_previous_sentence_is_capped() -> None:
    """The previous sentence keeps at most ``MAX_SIDE_CHARS`` back from its end; the premise stays one slice."""
    note = "z" * 500 + ". This showed AHI 18.2 events/hr."
    premise = build_premise(note, *span(note, QUOTE))
    assert premise == "z" * MAX_SIDE_CHARS + ". This showed AHI 18.2 events/hr."
    assert premise in note


def test_premise_rejects_offsets_that_do_not_fit() -> None:
    """Bad offsets are a caller error."""
    with pytest.raises(ValueError):
        build_premise(NOTE, 50, 20)


# --- P(Yes) ------------------------------------------------------------------------------


def test_p_yes_normalizes_over_yes_and_no() -> None:
    """P(Yes) = p(Yes) / (p(Yes) + p(No)), summing token variants."""
    top = [("Yes", math.log(0.6)), (" yes", math.log(0.1)), ("No", math.log(0.2)), ("Maybe", math.log(0.1))]
    assert p_yes(top) == pytest.approx(0.7 / 0.9)


def test_p_yes_with_only_one_answer_present() -> None:
    """If No isn't in the top tokens, P(Yes) is 1 by normalization (resolution measured live)."""
    assert p_yes([("Yes", math.log(0.99))]) == pytest.approx(1.0)


def test_p_yes_without_any_answer_token_raises() -> None:
    """Never fall back to 0 or 1 when neither answer is among the top tokens."""
    with pytest.raises(VerifierResponseError):
        p_yes([("Maybe", -0.1)])


# --- MiniCheck on Ollama -----------------------------------------------------------------


def ollama_reply(top: list[tuple[str, float]] | None, response: str = "Yes") -> bytes:
    """An Ollama /api/generate envelope with optional log-probabilities."""
    envelope: dict[str, Any] = {"response": response}
    if top is not None:
        envelope["logprobs"] = [
            {"token": top[0][0], "logprob": top[0][1], "top_logprobs": [{"token": t, "logprob": lp} for t, lp in top]}
        ]
    return json.dumps(envelope).encode()


def minicheck(reply: bytes | Exception) -> tuple[MiniCheckClient, list[dict[str, Any]]]:
    """A MiniCheck client with a fake transport that records request bodies."""
    sent: list[dict[str, Any]] = []

    def post(url: str, body: bytes, timeout: float) -> bytes:
        sent.append({"url": url, **json.loads(body)})
        if isinstance(reply, Exception):
            raise reply
        return reply

    config = VerifierConfig(backend=VerifierBackend.MINICHECK, model="bespoke-minicheck")
    return MiniCheckClient(config, post=post), sent


def test_minicheck_scores_from_logprobs_and_sends_document_and_claim() -> None:
    """Request asks for log-probabilities with thinking off; score is P(Yes)."""
    client, sent = minicheck(ollama_reply([("Yes", math.log(0.8)), ("No", math.log(0.2))]))

    assert client.score("My AHI was 18.2.", "AHI 18.2 events/hr") == pytest.approx(0.8)
    (request,) = sent
    assert request["url"].endswith("/api/generate")
    assert request["logprobs"] is True and request["top_logprobs"] >= 5
    assert request["prompt"] == "Document: AHI 18.2 events/hr\nClaim: My AHI was 18.2."
    assert request["options"]["temperature"] == 0


def test_minicheck_missing_logprobs_raises() -> None:
    """A Yes/No without log-probabilities can't be calibrated, so it is an error (ADR-0018)."""
    client, _ = minicheck(ollama_reply(None))
    with pytest.raises(VerifierResponseError, match="log-probabilities"):
        client.score("claim", "premise")


@pytest.mark.parametrize("error", [TimeoutError("timed out"), ConnectionRefusedError("refused"), OSError("unreachable")])
def test_minicheck_transport_errors_raise_llm_error(error: Exception) -> None:
    """Timeouts and refused connections surface as ``LLMError``."""
    client, _ = minicheck(error)
    with pytest.raises(LLMError, match="lab tunnel"):
        client.score("claim", "premise")


def test_minicheck_server_error_raises() -> None:
    """An Ollama error envelope is an ``LLMError``."""
    client, _ = minicheck(json.dumps({"error": "model not found"}).encode())
    with pytest.raises(LLMError, match="model not found"):
        client.score("claim", "premise")


def test_minicheck_bad_envelope_raises() -> None:
    """A non-JSON envelope is a response error."""
    client, _ = minicheck(b"<html>")
    with pytest.raises(VerifierResponseError):
        client.score("claim", "premise")


# --- Gemini judge ------------------------------------------------------------------------


class FakeModels:
    """Stands in for ``genai.Client().models``."""

    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        """Record the call and return the canned response (or raise it)."""
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def gemini_response(top: list[tuple[str, float]] | None) -> Any:
    """A response shaped like the SDK's, with optional first-token top candidates."""
    result = None
    if top is not None:
        candidates = [SimpleNamespace(token=t, log_probability=lp) for t, lp in top]
        result = SimpleNamespace(top_candidates=[SimpleNamespace(candidates=candidates)])
    return SimpleNamespace(text="Yes", candidates=[SimpleNamespace(logprobs_result=result)])


def judge(response: Any) -> tuple[GeminiJudge, FakeModels]:
    """A Gemini judge with a fake SDK."""
    models = FakeModels(response)
    config = VerifierConfig(backend=VerifierBackend.GEMINI, model="gemini-3.5-flash")
    return GeminiJudge(config, sdk=SimpleNamespace(models=models)), models


def test_gemini_judge_scores_from_response_logprobs_with_thinking_minimal() -> None:
    """Plain-text Yes/No (no JSON), logprobs requested, thinking minimal."""
    client, models = judge(gemini_response([("Yes", math.log(0.9)), ("No", math.log(0.1))]))

    assert client.score("claim", "premise") == pytest.approx(0.9)
    config = models.calls[0]["config"]
    assert config.response_logprobs is True and config.logprobs >= 5
    assert config.response_mime_type in (None, "text/plain")
    assert config.thinking_config.thinking_level.name == "MINIMAL"
    assert "premise" in models.calls[0]["contents"] and "claim" in models.calls[0]["contents"]


def test_gemini_judge_missing_logprobs_raises() -> None:
    """A self-reported answer without log-probabilities is never a score."""
    client, _ = judge(gemini_response(None))
    with pytest.raises(VerifierResponseError, match="log-probabilities"):
        client.score("claim", "premise")


def test_gemini_judge_api_error_raises_llm_error() -> None:
    """SDK API errors surface as ``LLMError``."""
    from google.genai import errors as genai_errors

    client, _ = judge(genai_errors.APIError(500, {"error": {"message": "boom"}}))
    with pytest.raises(LLMError, match="boom"):
        client.score("claim", "premise")


# --- config ------------------------------------------------------------------------------


def test_config_defaults_to_minicheck_on_the_lab_tunnel() -> None:
    """No variables: MiniCheck through the lab tunnel."""
    config = VerifierConfig.from_env({})
    assert config.backend is VerifierBackend.MINICHECK and config.model == "bespoke-minicheck"
    assert config.ollama_url == "http://localhost:11435"


def test_config_reads_gemini_backend() -> None:
    """``PAIR_VERIFIER_BACKEND=gemini`` switches backend and default model."""
    config = VerifierConfig.from_env({"PAIR_VERIFIER_BACKEND": "Gemini"})
    assert config.backend is VerifierBackend.GEMINI and config.model.startswith("gemini")


@pytest.mark.parametrize(
    "env",
    [{"PAIR_VERIFIER_BACKEND": "llama"}, {"PAIR_VERIFIER_MODEL": " "}, {"PAIR_OLLAMA_URL": "ftp://x"}],
)
def test_config_rejects_bad_values(env: dict[str, str]) -> None:
    """Bad settings fail loudly."""
    with pytest.raises(VerifierConfigError):
        VerifierConfig.from_env(env)


def test_make_verifier_picks_the_backend_and_describes_it() -> None:
    """Run metadata names backend, model tag and host (ADR-0011)."""
    minicheck_client = make_verifier(VerifierConfig.from_env({}))
    gemini_client = make_verifier(VerifierConfig.from_env({"PAIR_VERIFIER_BACKEND": "gemini"}))

    assert isinstance(minicheck_client, MiniCheckClient) and isinstance(gemini_client, GeminiJudge)
    assert minicheck_client.describe() == {
        "verifier_backend": "minicheck", "verifier_model": "bespoke-minicheck", "verifier_host": "localhost:11435",
    }
    assert gemini_client.describe()["verifier_backend"] == "gemini"


def test_clients_reject_the_wrong_backend() -> None:
    """A client bound to the other backend's config is a setup error."""
    with pytest.raises(VerifierConfigError):
        MiniCheckClient(VerifierConfig.from_env({"PAIR_VERIFIER_BACKEND": "gemini"}))
    with pytest.raises(VerifierConfigError):
        GeminiJudge(VerifierConfig.from_env({}))


# --- live (lab GPU or Vertex) ------------------------------------------------------------


@pytest.mark.llm
def test_live_backend_returns_graded_scores() -> None:
    """T4 live check: log-probabilities come back and scores aren't all saturated."""
    client = make_verifier(VerifierConfig.from_env())
    premise = build_premise(NOTE, *span(NOTE, QUOTE))
    supported = client.score("My home sleep test on 2026-03-10 showed an AHI of 18.2.", premise)
    unsupported = client.score("My home sleep test showed an AHI of 32.", premise)
    assert 0.0 <= unsupported < supported <= 1.0
