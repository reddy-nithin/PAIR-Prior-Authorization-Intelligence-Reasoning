"""Entailment verifier: does the record sentence support the claim? (step 6, ADR-0018).

One ``Verifier`` protocol, ``score(claim, premise) -> float`` in [0, 1], with two
backends behind a config switch:

- ``minicheck`` (default): ``bespoke-minicheck`` on the lab server's Ollama via
  the tunnel. Score = P(Yes) from the first answer token's log-probabilities.
- ``gemini``: a Gemini Flash judge on Vertex (thinking minimal) answering plain
  "Yes" or "No"; score = P(Yes) from ``responseLogprobs``. It never gets a
  conformal threshold, so it can only FLAG or DROP (ADR-0018).

A reply without log-probabilities raises: a bare Yes/No can't be calibrated.

The premise is the record quote completed to its own sentence and nothing else
(no policy text, no neighboring sentences). ``build_premise`` is the only place
it is built; the S1 labeler uses it too, so labels and scores see the same text.
"""

import json
import logging
import math
import os
import re
import urllib.error
import urllib.parse
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from pair.llm import (
    DEFAULT_GCP_LOCATION,
    DEFAULT_GCP_PROJECT,
    DEFAULT_OLLAMA_URL,
    LLMError,
    Post,
    http_post,
)

logger = logging.getLogger(__name__)

MAX_SIDE_CHARS = 300
PREMISE_RULE = "adr-0022"  # tags runs and thresholds with the rule that built their premises
REFERRING = re.compile(r"(This|That|These|Those|It|They|Such)\b")  # ADR-0022 openers, case-sensitive
TOP_LOGPROBS = 10
DEFAULT_MINICHECK_MODEL = "bespoke-minicheck"
DEFAULT_JUDGE_MODEL = "gemini-3.5-flash"
DEFAULT_TIMEOUT_S = 120.0

_BREAK = re.compile(r"[.!?](?=\s|$)|\n")

JUDGE_PROMPT = """Read the document and the claim. Answer Yes if the document fully supports every part of the claim, otherwise No. Answer with one word: Yes or No.

Document: {premise}
Claim: {claim}
Answer:"""


class VerifierConfigError(ValueError):
    """The verifier settings are missing or invalid."""


class VerifierResponseError(LLMError):
    """The verifier answered without usable log-probabilities."""


class VerifierBackend(StrEnum):
    """Which entailment model answers."""

    MINICHECK = "minicheck"
    GEMINI = "gemini"


@dataclass(frozen=True)
class VerifierConfig:
    """Settings for one verifier backend.

    Attributes:
        backend: Which service to call.
        model: Ollama tag or Gemini model id.
        ollama_url: Base URL of the Ollama server (the lab tunnel).
        gcp_project: Vertex AI project for the Gemini judge.
        gcp_location: Vertex AI location for the Gemini judge.
        timeout_s: Ollama HTTP timeout in seconds.
    """

    backend: VerifierBackend
    model: str
    ollama_url: str = DEFAULT_OLLAMA_URL
    gcp_project: str = DEFAULT_GCP_PROJECT
    gcp_location: str = DEFAULT_GCP_LOCATION
    timeout_s: float = DEFAULT_TIMEOUT_S

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "VerifierConfig":
        """Build a config from ``PAIR_VERIFIER_*`` variables (``os.environ`` by default).

        Raises:
            VerifierConfigError: If a variable has an invalid value.
        """
        source = os.environ if env is None else env
        name = source.get("PAIR_VERIFIER_BACKEND", VerifierBackend.MINICHECK.value).strip().lower()
        try:
            backend = VerifierBackend(name)
        except ValueError as exc:
            raise VerifierConfigError(f"PAIR_VERIFIER_BACKEND={name!r}; expected minicheck or gemini") from exc
        default = DEFAULT_MINICHECK_MODEL if backend is VerifierBackend.MINICHECK else DEFAULT_JUDGE_MODEL
        model = source.get("PAIR_VERIFIER_MODEL", default).strip()
        if not model:
            raise VerifierConfigError("PAIR_VERIFIER_MODEL is empty")
        url = source.get("PAIR_OLLAMA_URL", DEFAULT_OLLAMA_URL)
        if urllib.parse.urlsplit(url).scheme not in {"http", "https"}:
            raise VerifierConfigError(f"PAIR_OLLAMA_URL={url!r} must be an http(s) URL")
        return cls(
            backend=backend,
            model=model,
            ollama_url=url.rstrip("/"),
            gcp_project=source.get("PAIR_GCP_PROJECT", DEFAULT_GCP_PROJECT),
            gcp_location=source.get("PAIR_GCP_LOCATION", DEFAULT_GCP_LOCATION),
        )


class Verifier(Protocol):
    """Anything that scores how well a premise supports a claim."""

    def score(self, claim: str, premise: str) -> float:
        """Return P(the premise supports the claim) in [0, 1]."""
        ...

    def describe(self) -> dict[str, str]:
        """Backend, model tag and host, for run metadata."""
        ...


def build_premise(document: str, char_start: int, char_end: int) -> str:
    """The record quote completed to its own sentence, capped at ``MAX_SIDE_CHARS`` per side.

    A sentence ends at ``.``, ``!`` or ``?`` followed by whitespace, or at a line
    break. If the quote's sentence opens with a referring word (``REFERRING``),
    the previous sentence is added in front, capped at ``MAX_SIDE_CHARS`` back
    from its end (ADR-0022). Nothing further back is ever included, so the
    premise is always one slice of the document.

    Raises:
        ValueError: If the offsets don't fit the document.
    """
    if not 0 <= char_start < char_end <= len(document):
        raise ValueError(f"offsets {char_start}..{char_end} don't fit a document of {len(document)} chars")
    left_limit = max(0, char_start - MAX_SIDE_CHARS)
    before = list(_BREAK.finditer(document, left_limit, char_start))
    start = before[-1].end() if before else left_limit
    right_limit = min(len(document), char_end + MAX_SIDE_CHARS)
    after = _BREAK.search(document, max(char_end - 1, char_start), right_limit)
    if after is None:
        end = right_limit
    else:
        end = after.start() if after.group(0) == "\n" else after.end()
    if before and REFERRING.match(document[start:max(end, char_end)].lstrip()):
        start = _previous_sentence_start(document, before[-1].start())
    return document[start:max(end, char_end)].strip()


def _previous_sentence_start(document: str, boundary: int) -> int:
    """Where the sentence ending at ``boundary`` starts, at most ``MAX_SIDE_CHARS`` back."""
    limit = max(0, boundary - MAX_SIDE_CHARS)
    breaks = list(_BREAK.finditer(document, limit, boundary))
    return breaks[-1].end() if breaks else limit


def p_yes(top: Iterable[tuple[str, float]]) -> float:
    """P(Yes) normalized over the Yes and No tokens among the first token's top log-probabilities.

    Raises:
        VerifierResponseError: If neither answer is among the top tokens.
    """
    yes = no = 0.0
    for token, logprob in top:
        word = token.strip().lower()
        if word == "yes":
            yes += math.exp(logprob)
        elif word == "no":
            no += math.exp(logprob)
    if yes + no == 0.0:
        raise VerifierResponseError("neither Yes nor No is among the top tokens")
    return yes / (yes + no)


class MiniCheckClient:
    """``bespoke-minicheck`` on Ollama, scored from log-probabilities."""

    def __init__(self, config: VerifierConfig, post: Post = http_post) -> None:
        """Bind a config and a transport.

        Raises:
            VerifierConfigError: If ``config`` isn't for MiniCheck.
        """
        if config.backend is not VerifierBackend.MINICHECK:
            raise VerifierConfigError(f"MiniCheckClient needs backend=minicheck, got {config.backend}")
        self._config = config
        self._post = post

    def describe(self) -> dict[str, str]:
        """Backend, model tag and host, for run metadata."""
        host = urllib.parse.urlsplit(self._config.ollama_url).netloc
        return {"verifier_backend": "minicheck", "verifier_model": self._config.model, "verifier_host": host}

    def score(self, claim: str, premise: str) -> float:
        """Return P(Yes) for ``claim`` given ``premise``.

        Raises:
            LLMError: If the server can't be reached or reports an error.
            VerifierResponseError: If the reply has no log-probabilities.
        """
        config = self._config
        url = f"{config.ollama_url}/api/generate"
        payload = {
            "model": config.model,
            "prompt": f"Document: {premise}\nClaim: {claim}",
            "stream": False,
            "logprobs": True,
            "top_logprobs": TOP_LOGPROBS,
            "options": {"temperature": 0, "num_predict": 1},
        }
        try:
            body = self._post(url, json.dumps(payload).encode(), config.timeout_s)
        except (urllib.error.URLError, OSError) as exc:
            logger.error("MiniCheck call to %s failed: %s", url, exc)
            raise LLMError(f"MiniCheck at {url} unreachable ({exc}); is the lab tunnel up?") from exc
        try:
            envelope = json.loads(body)
        except json.JSONDecodeError as exc:
            raise VerifierResponseError(f"MiniCheck envelope is not JSON: {body[:200]!r}") from exc
        if "error" in envelope:
            logger.error("MiniCheck error for %s: %s", config.model, envelope["error"])
            raise LLMError(f"Ollama error for {config.model}: {envelope['error']}")
        logprobs = envelope.get("logprobs") or []
        if not logprobs or not logprobs[0].get("top_logprobs"):
            raise VerifierResponseError(f"MiniCheck reply {envelope.get('response')!r} has no log-probabilities")
        return p_yes((item["token"], float(item["logprob"])) for item in logprobs[0]["top_logprobs"])


class GeminiJudge:
    """Gemini Flash as a Yes/No judge, scored from ``responseLogprobs``."""

    def __init__(self, config: VerifierConfig, sdk: Any | None = None) -> None:
        """Bind a config; the Vertex SDK client is built on first use unless injected.

        Raises:
            VerifierConfigError: If ``config`` isn't for the Gemini judge.
        """
        if config.backend is not VerifierBackend.GEMINI:
            raise VerifierConfigError(f"GeminiJudge needs backend=gemini, got {config.backend}")
        self._config = config
        self._sdk = sdk

    def describe(self) -> dict[str, str]:
        """Backend, model tag and host, for run metadata."""
        return {
            "verifier_backend": "gemini",
            "verifier_model": self._config.model,
            "verifier_host": f"vertex:{self._config.gcp_location}",
        }

    def _client(self) -> Any:
        """Return the SDK client, creating a Vertex one if needed."""
        if self._sdk is None:  # pragma: no cover - needs Vertex credentials
            self._sdk = genai.Client(
                vertexai=True, project=self._config.gcp_project, location=self._config.gcp_location
            )
        return self._sdk

    def score(self, claim: str, premise: str) -> float:
        """Return P(Yes) for ``claim`` given ``premise``.

        Raises:
            LLMError: If the API call fails.
            VerifierResponseError: If the reply has no log-probabilities.
        """
        model = self._config.model
        request_config = types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=1,
            response_logprobs=True,
            logprobs=TOP_LOGPROBS,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
        )
        try:
            response = self._client().models.generate_content(
                model=model, contents=JUDGE_PROMPT.format(premise=premise, claim=claim), config=request_config
            )
        except genai_errors.APIError as exc:
            logger.error("Gemini judge call to %s failed: %s", model, exc)
            raise LLMError(f"Gemini judge call to {model} failed: {exc}") from exc
        candidates = getattr(response, "candidates", None) or []
        result = getattr(candidates[0], "logprobs_result", None) if candidates else None
        top = getattr(result, "top_candidates", None) or []
        if not top:
            raise VerifierResponseError(f"Gemini judge reply {getattr(response, 'text', '')!r} has no log-probabilities")
        return p_yes((c.token, float(c.log_probability)) for c in top[0].candidates)


def make_verifier(config: VerifierConfig) -> MiniCheckClient | GeminiJudge:
    """Return the verifier for ``config.backend``."""
    if config.backend is VerifierBackend.GEMINI:
        return GeminiJudge(config)
    return MiniCheckClient(config)
