"""One small client for schema-constrained JSON calls to Ollama or Gemini.

The pipeline only ever asks an LLM to *read* (fill a JSON schema from text),
so a single ``generate_json(prompt, schema)`` call is the whole interface.
Backend, model and endpoint come from the environment (ADR-0010, ADR-0011):

- ``ollama`` (default): ``gemma4:e4b`` on the lab server via the SSH tunnel on
  ``localhost:11435``. Thinking is turned off and ``num_ctx`` is set per
  request, because the server default (4096) is too small for clinical notes.
- ``gemini``: ``gemini-3.5-flash`` on Vertex AI with ``thinking_level=MINIMAL``,
  the closest current equivalent of "thinking budget 0".
"""

import hashlib
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Protocol

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_MODEL: str = "gemma4:e4b"
DEFAULT_GEMINI_MODEL: str = "gemini-3.5-flash"
DEFAULT_OLLAMA_URL: str = "http://localhost:11435"
"""The Mac end of the lab tunnel (`scripts/lab_ollama.sh start`)."""
DEFAULT_GCP_PROJECT: str = "pair-appeal-copilot"
DEFAULT_GCP_LOCATION: str = "global"
DEFAULT_NUM_CTX: int = 16384
DEFAULT_TIMEOUT_S: float = 300.0
TEMPERATURE: float = 0.0

JsonSchema = Mapping[str, Any]
Post = Callable[[str, bytes, float], bytes]
"""``(url, body, timeout) -> response body``; injectable so tests need no network."""

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class Backend(StrEnum):
    """Which LLM service answers."""

    OLLAMA = "ollama"
    GEMINI = "gemini"


class LLMConfigError(ValueError):
    """The LLM settings are missing or invalid."""


class LLMError(RuntimeError):
    """The LLM call failed (transport, server or SDK error)."""


class LLMResponseError(LLMError):
    """The LLM answered, but not with a JSON object."""


@dataclass(frozen=True)
class LLMConfig:
    """Settings for one LLM backend.

    Attributes:
        backend: Which service to call.
        model: Model id or Ollama tag.
        ollama_url: Base URL of the Ollama server (no trailing slash).
        gcp_project: Vertex AI project for Gemini.
        gcp_location: Vertex AI location for Gemini.
        num_ctx: Ollama context window, set on every request.
        timeout_s: Ollama HTTP timeout in seconds.
    """

    backend: Backend
    model: str
    ollama_url: str = DEFAULT_OLLAMA_URL
    gcp_project: str = DEFAULT_GCP_PROJECT
    gcp_location: str = DEFAULT_GCP_LOCATION
    num_ctx: int = DEFAULT_NUM_CTX
    timeout_s: float = DEFAULT_TIMEOUT_S

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "LLMConfig":
        """Build a config from ``PAIR_*`` variables (``os.environ`` by default).

        Raises:
            LLMConfigError: If a variable has an invalid value.
        """
        source = os.environ if env is None else env
        backend = _backend(source.get("PAIR_LLM_BACKEND", Backend.OLLAMA.value))
        default_model = (
            DEFAULT_OLLAMA_MODEL if backend is Backend.OLLAMA else DEFAULT_GEMINI_MODEL
        )
        model = source.get("PAIR_LLM_MODEL", default_model).strip()
        if not model:
            raise LLMConfigError("PAIR_LLM_MODEL is empty")
        return cls(
            backend=backend,
            model=model,
            ollama_url=_ollama_url(source.get("PAIR_OLLAMA_URL", DEFAULT_OLLAMA_URL)),
            gcp_project=source.get("PAIR_GCP_PROJECT", DEFAULT_GCP_PROJECT),
            gcp_location=source.get("PAIR_GCP_LOCATION", DEFAULT_GCP_LOCATION),
            num_ctx=int(
                _positive(
                    "PAIR_LLM_NUM_CTX", source.get("PAIR_LLM_NUM_CTX"), DEFAULT_NUM_CTX
                )
            ),
            timeout_s=_positive(
                "PAIR_LLM_TIMEOUT_S",
                source.get("PAIR_LLM_TIMEOUT_S"),
                DEFAULT_TIMEOUT_S,
            ),
        )

    def config_hash(self) -> str:
        """A short, stable hash of the settings, for run logs (ADR-0011)."""
        blob = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:12]


def _backend(value: str) -> Backend:
    """Parse a backend name, case-insensitively."""
    try:
        return Backend(value.strip().lower())
    except ValueError as exc:
        choices = ", ".join(b.value for b in Backend)
        raise LLMConfigError(
            f"PAIR_LLM_BACKEND={value!r}; expected one of {choices}"
        ) from exc


def _ollama_url(value: str) -> str:
    """Validate an http(s) base URL and drop any trailing slash."""
    if urllib.parse.urlsplit(value).scheme not in {"http", "https"}:
        raise LLMConfigError(f"PAIR_OLLAMA_URL={value!r} must be an http(s) URL")
    return value.rstrip("/")


def _positive(name: str, value: str | None, default: float) -> float:
    """Parse a positive number, or return ``default`` when unset."""
    if value is None:
        return default
    try:
        number = float(value)
    except ValueError as exc:
        raise LLMConfigError(f"{name}={value!r} is not a number") from exc
    if number <= 0:
        raise LLMConfigError(f"{name}={value!r} must be positive")
    return number


@dataclass(frozen=True)
class LLMUsage:
    """Token counts reported by the backend (None when not reported)."""

    prompt_tokens: int | None
    output_tokens: int | None
    thinking_tokens: int | None
    thinking_present: bool = False
    """True if the backend returned thinking text or counted thinking tokens."""


@dataclass(frozen=True)
class LLMResult:
    """A parsed JSON reply plus what produced it."""

    data: dict[str, Any]
    raw_text: str
    usage: LLMUsage
    backend: Backend
    model: str


class LLMClient(Protocol):
    """Anything that can fill a JSON schema from a prompt."""

    def generate_json(self, prompt: str, schema: JsonSchema) -> LLMResult:
        """Return the model's reply to ``prompt``, constrained to ``schema``."""
        ...


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a reply that must be one JSON object (an optional markdown fence is allowed).

    Raises:
        LLMResponseError: If the text isn't a JSON object.
    """
    stripped = text.strip()
    fenced = _FENCE.match(stripped)
    if fenced:
        stripped = fenced.group(1)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise LLMResponseError(f"reply is not JSON: {text[:200]!r}") from exc
    if not isinstance(data, dict):
        raise LLMResponseError(f"reply is not a JSON object: {text[:200]!r}")
    return data


def http_post(url: str, body: bytes, timeout: float) -> bytes:
    """POST a JSON body and return the response body (the default Ollama transport)."""
    request = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data: bytes = response.read()
    return data


class OllamaClient:
    """Calls Ollama's ``/api/generate`` with a JSON-schema ``format``."""

    def __init__(self, config: LLMConfig, post: Post = http_post) -> None:
        """Bind a config and a transport.

        Raises:
            LLMConfigError: If ``config`` isn't for the Ollama backend.
        """
        if config.backend is not Backend.OLLAMA:
            raise LLMConfigError(
                f"OllamaClient needs backend=ollama, got {config.backend}"
            )
        self._config = config
        self._post = post

    def generate_json(self, prompt: str, schema: JsonSchema) -> LLMResult:
        """Return the model's JSON reply.

        Raises:
            LLMError: If the server can't be reached or reports an error.
            LLMResponseError: If the reply isn't a JSON object.
        """
        config = self._config
        url = f"{config.ollama_url}/api/generate"
        payload = {
            "model": config.model,
            "prompt": prompt,
            "format": dict(schema),
            "stream": False,
            "think": False,
            "options": {"temperature": TEMPERATURE, "num_ctx": config.num_ctx},
        }
        try:
            body = self._post(url, json.dumps(payload).encode(), config.timeout_s)
        except (urllib.error.URLError, OSError) as exc:
            logger.error("Ollama call to %s failed: %s", url, exc)
            raise LLMError(
                f"Ollama at {url} unreachable ({exc}); is the lab tunnel up?"
            ) from exc
        envelope = _ollama_envelope(body)
        if "error" in envelope:
            logger.error("Ollama error for %s: %s", config.model, envelope["error"])
            raise LLMError(f"Ollama error for {config.model}: {envelope['error']}")
        text = str(envelope.get("response", ""))
        usage = LLMUsage(
            prompt_tokens=envelope.get("prompt_eval_count"),
            output_tokens=envelope.get("eval_count"),
            thinking_tokens=None,
            thinking_present=bool(envelope.get("thinking")),
        )
        logger.info("ollama %s usage %s", config.model, usage)
        return LLMResult(
            parse_json_object(text), text, usage, Backend.OLLAMA, config.model
        )


def _ollama_envelope(body: bytes) -> dict[str, Any]:
    """Decode Ollama's response envelope."""
    try:
        envelope = json.loads(body)
    except json.JSONDecodeError as exc:
        raise LLMResponseError(f"Ollama envelope is not JSON: {body[:200]!r}") from exc
    if not isinstance(envelope, dict):
        raise LLMResponseError(f"Ollama envelope is not an object: {body[:200]!r}")
    return envelope


class GeminiClient:
    """Calls Gemini on Vertex AI in JSON mode with minimal thinking."""

    def __init__(self, config: LLMConfig, sdk: Any | None = None) -> None:
        """Bind a config; the Vertex SDK client is built on first use unless injected.

        Raises:
            LLMConfigError: If ``config`` isn't for the Gemini backend.
        """
        if config.backend is not Backend.GEMINI:
            raise LLMConfigError(
                f"GeminiClient needs backend=gemini, got {config.backend}"
            )
        self._config = config
        self._sdk = sdk

    def _client(self) -> Any:
        """Return the SDK client, creating a Vertex one if needed."""
        if self._sdk is None:
            self._sdk = genai.Client(
                vertexai=True,
                project=self._config.gcp_project,
                location=self._config.gcp_location,
            )
        return self._sdk

    def generate_json(self, prompt: str, schema: JsonSchema) -> LLMResult:
        """Return the model's JSON reply.

        Raises:
            LLMError: If the API call fails.
            LLMResponseError: If the reply is empty or isn't a JSON object.
        """
        model = self._config.model
        request_config = types.GenerateContentConfig(
            temperature=TEMPERATURE,
            response_mime_type="application/json",
            response_json_schema=dict(schema),
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.MINIMAL
            ),
        )
        try:
            response = self._client().models.generate_content(
                model=model, contents=prompt, config=request_config
            )
        except genai_errors.APIError as exc:
            logger.error("Gemini call to %s failed: %s", model, exc)
            raise LLMError(f"Gemini call to {model} failed: {exc}") from exc
        text = response.text
        if not text:
            raise LLMResponseError(f"Gemini {model} returned an empty reply")
        meta = response.usage_metadata
        thoughts = getattr(meta, "thoughts_token_count", None)
        usage = LLMUsage(
            prompt_tokens=getattr(meta, "prompt_token_count", None),
            output_tokens=getattr(meta, "candidates_token_count", None),
            thinking_tokens=thoughts,
            thinking_present=bool(thoughts),
        )
        logger.info("gemini %s usage %s", model, usage)
        return LLMResult(parse_json_object(text), text, usage, Backend.GEMINI, model)


def make_client(config: LLMConfig) -> LLMClient:
    """Return the client for ``config.backend``."""
    if config.backend is Backend.GEMINI:
        return GeminiClient(config)
    return OllamaClient(config)
