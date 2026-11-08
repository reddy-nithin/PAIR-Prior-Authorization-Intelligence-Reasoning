"""Tests for the log redaction filter and that pipeline logs never carry record text (Phase 4 T4)."""

import io
import logging
from collections.abc import Iterator

import pytest

from pair.draft.template import LetterTemplate
from pair.llm import LLMConfig
from pair.pipeline import Resources, run_core, run_trust
from pair.score.base_model import BaseEstimate
from pair.score.strength import load_adjustments
from pair.trust_cli import case_flags
from pair.ui import privacy
from pair.ui.privacy import (
    WITHHELD,
    PrivacyError,
    RedactingFilter,
    install_log_redaction,
    scrub,
)
from pair.verify.conformal import Threshold
from tests.conftest import REPO_ROOT
from tests.fakes import FakeLLM
from tests.test_pipeline import CASE, denial_reply, gold_extract
from tests.ui.conftest import DRAFTER, EmptyWordingLLM, FirstLowVerifier

needs_model = pytest.mark.skipif(not privacy.model_installed(), reason="spaCy en_core_web_lg not installed")


@pytest.fixture
def stream_logger() -> Iterator[tuple[logging.Logger, io.StringIO]]:
    """A logger writing to a string through one handler, removed afterwards."""
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    log = logging.getLogger("pair.test.privacy")
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    yield log, buffer
    log.removeHandler(handler)


@needs_model
def test_scrub_replaces_names_dates_phones_and_member_ids() -> None:
    """Synthetic PII becomes entity tags; the rest of the sentence stays."""
    text = scrub("Mary Jones (MRN: A1234567) called 816-555-0199 on March 3, 2026 about her CPAP denial.")
    for secret in ("Mary Jones", "A1234567", "816-555-0199", "March 3, 2026"):
        assert secret not in text
    assert "<PERSON>" in text and "<MEMBER_ID>" in text and "called" in text and "denial." in text


@needs_model
def test_filter_redacts_messages_args_and_tracebacks(stream_logger: tuple[logging.Logger, io.StringIO]) -> None:
    """The filter scrubs the formatted message and any exception text before a handler writes it."""
    log, buffer = stream_logger
    log.handlers[0].addFilter(RedactingFilter())
    log.info("upload from %s", "John Smith")
    try:
        raise ValueError("bad record for Jane Doe")
    except ValueError:
        log.exception("failed")
    out = buffer.getvalue()
    assert "John Smith" not in out and "Jane Doe" not in out
    assert "upload from <PERSON>" in out and "Traceback" in out


def test_blank_text_needs_no_engine() -> None:
    """Blank messages pass through without loading Presidio."""
    assert scrub("   ") == "   "


def test_filter_fails_closed_when_redaction_breaks(
    stream_logger: tuple[logging.Logger, io.StringIO], monkeypatch: pytest.MonkeyPatch
) -> None:
    """If Presidio errors, the message is withheld rather than written unscrubbed."""
    def broken(text: str) -> str:
        raise RuntimeError("engine down")

    monkeypatch.setattr(privacy, "scrub", broken)
    log, buffer = stream_logger
    log.handlers[0].addFilter(RedactingFilter())
    log.warning("note for Mary Jones")
    assert "Mary Jones" not in buffer.getvalue()
    assert WITHHELD in buffer.getvalue()


def test_install_refuses_without_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Starting the API without the spaCy model is an error, not a silent unscrubbed log."""
    monkeypatch.setattr(privacy, "model_installed", lambda: False)
    with pytest.raises(PrivacyError, match="en_core_web_lg"):
        install_log_redaction(logging.getLogger("pair.test.none"))


@needs_model
def test_install_adds_one_filter_per_handler(stream_logger: tuple[logging.Logger, io.StringIO]) -> None:
    """Installing twice doesn't stack filters."""
    log, _ = stream_logger
    try:
        install_log_redaction(log)
        install_log_redaction(log)
        assert sum(isinstance(f, RedactingFilter) for f in log.handlers[0].filters) == 1
    finally:
        for handler in log.handlers:
            for found in [f for f in handler.filters if isinstance(f, RedactingFilter)]:
                handler.removeFilter(found)


def test_records_logged_while_scrubbing_are_dropped_not_looped(
    stream_logger: tuple[logging.Logger, io.StringIO], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Presidio and spaCy log while they scrub; those records reach the same handler and must not recurse or leak."""
    log, buffer = stream_logger
    calls: list[str] = []

    def chatty(text: str) -> str:
        calls.append(text)
        log.warning("engine saw %s", text)
        return text.replace("Mary Jones", "<PERSON>")

    monkeypatch.setattr(privacy, "scrub", chatty)
    log.handlers[0].addFilter(RedactingFilter())
    log.warning("note for Mary Jones")
    out = buffer.getvalue()
    assert calls == ["note for Mary Jones"]
    assert "note for <PERSON>" in out and "Mary Jones" not in out and "engine saw" not in out


def test_a_full_run_never_logs_record_text(
    caplog: pytest.LogCaptureFixture, resources: Resources, template: LetterTemplate
) -> None:
    """Steps 1 to 7 at DEBUG log no record sentence and no evidence quote."""
    documents = CASE.record_text()
    caplog.set_level(logging.DEBUG)
    core = run_core(
        CASE.denial_text, documents, resources, FakeLLM([denial_reply()]), LLMConfig.from_env({}),
        context=CASE.context, extract_fn=gold_extract,
    )  # fmt: skip
    threshold = Threshold(q_hat=0.5, n=54, k=1, alpha=0.1, drafter=DRAFTER,
                          verifier_backend="minicheck", verifier_model="bespoke-minicheck")  # fmt: skip
    run_trust(
        core, documents, resources.checklists["pap-osa"], EmptyWordingLLM(), FirstLowVerifier(), threshold,
        DRAFTER, template, case_flags(CASE), BaseEstimate(0.6, 0.5, 0.7, 120, "DME", False),
        load_adjustments(REPO_ROOT / "src" / "pair" / "score" / "adjustments.yaml"),
    )  # fmt: skip
    logged = caplog.text
    sentences = [s.strip() for text in documents.values() for s in text.split(".") if len(s.strip()) > 20]
    quotes = [item.span_text for item in CASE.gold_evidence if len(item.span_text) >= 12]
    assert sentences and quotes
    leaked = [s for s in [*sentences, *quotes, CASE.denial_text[:40]] if s in logged]
    assert not leaked, leaked
