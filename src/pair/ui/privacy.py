"""Log redaction for the demo API: Presidio replaces PII in every log record (ADR-0023).

Upload text is never logged in the first place; this filter is the second guard.
It runs on handlers, so it sees every record they write, and it fails closed: if
redaction breaks, the message is withheld instead of written unscrubbed. Presidio
and spaCy log while they scrub; those records reach the same handlers, so they are
dropped (a per-thread guard), which also stops the filter from calling itself.
Presidio and the spaCy model (``en_core_web_lg``, about 1 GB of RAM) load once,
on first use.
"""

import functools
import importlib.util
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

SPACY_MODEL = "en_core_web_lg"
WITHHELD = "[log message withheld: redaction failed]"
_MEMBER_ID = r"(?i)\b(?:MRN|member\s*id|medicare\s*id|mbi)\s*[:#]?\s*[A-Z0-9-]{5,}\b"


class PrivacyError(RuntimeError):
    """Log redaction can't be set up."""


def model_installed() -> bool:
    """True if the spaCy model Presidio needs is installed."""
    return importlib.util.find_spec(SPACY_MODEL) is not None


@functools.cache
def _engines() -> tuple[Any, Any]:
    """Presidio analyzer (spaCy large model + a member-id pattern) and anonymizer, built once."""
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_anonymizer import AnonymizerEngine

    nlp = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": SPACY_MODEL}],
    }).create_engine()  # fmt: skip
    analyzer = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
    analyzer.registry.add_recognizer(
        PatternRecognizer(supported_entity="MEMBER_ID", patterns=[Pattern("member id", _MEMBER_ID, 0.9)])
    )
    return analyzer, AnonymizerEngine()  # type: ignore[no-untyped-call]


def scrub(text: str) -> str:
    """Replace detected PII in ``text`` with entity tags such as ``<PERSON>``."""
    if not text.strip():
        return text
    analyzer, anonymizer = _engines()
    findings = analyzer.analyze(text=text, language="en")
    return str(anonymizer.anonymize(text=text, analyzer_results=findings).text)


_guard = threading.local()


class RedactingFilter(logging.Filter):
    """Scrubs a record's message and exception text before a handler writes it."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite the record in place and let it through; drop records logged during a scrub."""
        if getattr(_guard, "active", False):
            return False
        _guard.active = True
        try:
            record.msg = scrub(record.getMessage())
            if record.exc_info and not record.exc_text:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            if record.exc_text:
                record.exc_text = scrub(record.exc_text)
        except Exception:  # noqa: BLE001  fail closed; logging here would re-enter this filter
            record.msg, record.exc_text = WITHHELD, None
        finally:
            _guard.active = False
        record.args = ()
        record.exc_info = None
        return True


def install_log_redaction(target: logging.Logger | None = None) -> RedactingFilter:
    """Add one ``RedactingFilter`` to every handler of ``target`` (default: the root logger).

    Loads Presidio now so the first real request isn't slow and a missing model fails at startup.

    Raises:
        PrivacyError: If the spaCy model isn't installed.
    """
    if not model_installed():
        raise PrivacyError(f"log redaction needs the spaCy model {SPACY_MODEL} (`uv sync`)")
    _engines()
    log = target or logging.getLogger()
    redactor = RedactingFilter()
    for handler in log.handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(redactor)
    logger.info("log redaction on for %d handler(s)", len(log.handlers))
    return redactor
