"""Tests for the LLM client (T6). No network: every transport is faked."""

import json
import os
import urllib.error
from types import SimpleNamespace
from typing import Any, Self

import pytest
from google.genai import errors as genai_errors
from google.genai import types

from pair import llm
from pair.llm import (
    Backend,
    GeminiClient,
    LLMConfig,
    LLMConfigError,
    LLMError,
    LLMResponseError,
    OllamaClient,
    make_client,
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"ahi": {"type": "number"}},
    "required": ["ahi"],
}


# ── Config ──────────────────────────────────────────────────────────────────


def test_config_defaults_to_ollama_e4b_on_the_lab_tunnel() -> None:
    """An empty environment picks the evaluated model (ADR-0011) on port 11435."""
    config = LLMConfig.from_env({})
    assert config.backend is Backend.OLLAMA
    assert config.model == "gemma4:e4b"
    assert config.ollama_url == "http://localhost:11435"


def test_config_gemini_defaults() -> None:
    """The Gemini backend defaults to ADR-0010's model, project and global endpoint."""
    config = LLMConfig.from_env({"PAIR_LLM_BACKEND": "gemini"})
    assert config.backend is Backend.GEMINI
    assert config.model == "gemini-3.5-flash"
    assert config.gcp_project == "pair-appeal-copilot"
    assert config.gcp_location == "global"


def test_config_reads_overrides() -> None:
    """Every setting can be overridden from the environment."""
    config = LLMConfig.from_env(
        {
            "PAIR_LLM_BACKEND": "OLLAMA",
            "PAIR_LLM_MODEL": "gemma4:e2b-it-qat",
            "PAIR_OLLAMA_URL": "http://localhost:11434/",
            "PAIR_LLM_NUM_CTX": "32768",
            "PAIR_LLM_TIMEOUT_S": "60",
        }
    )
    assert config.model == "gemma4:e2b-it-qat"
    assert config.ollama_url == "http://localhost:11434"
    assert config.num_ctx == 32768
    assert config.timeout_s == 60.0


def test_config_reads_os_environ_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an explicit mapping, ``from_env`` reads ``os.environ``."""
    monkeypatch.setenv("PAIR_LLM_BACKEND", "gemini")
    assert LLMConfig.from_env().backend is Backend.GEMINI
    assert os.environ["PAIR_LLM_BACKEND"] == "gemini"


@pytest.mark.parametrize(
    ("env", "match"),
    [
        ({"PAIR_LLM_BACKEND": "openai"}, "PAIR_LLM_BACKEND"),
        ({"PAIR_LLM_NUM_CTX": "big"}, "PAIR_LLM_NUM_CTX"),
        ({"PAIR_LLM_NUM_CTX": "0"}, "PAIR_LLM_NUM_CTX"),
        ({"PAIR_LLM_TIMEOUT_S": "-1"}, "PAIR_LLM_TIMEOUT_S"),
        ({"PAIR_LLM_MODEL": "  "}, "PAIR_LLM_MODEL"),
        ({"PAIR_OLLAMA_URL": "ftp://host"}, "PAIR_OLLAMA_URL"),
    ],
)
def test_config_rejects_bad_values(env: dict[str, str], match: str) -> None:
    """Bad settings fail loudly and name the variable."""
    with pytest.raises(LLMConfigError, match=match):
        LLMConfig.from_env(env)


def test_config_hash_is_stable_and_changes_with_model() -> None:
    """The run-log hash depends on the config, not on object identity."""
    a = LLMConfig.from_env({})
    b = LLMConfig.from_env({})
    c = LLMConfig.from_env({"PAIR_LLM_MODEL": "gemma4:e2b-it-qat"})
    assert a.config_hash() == b.config_hash()
    assert a.config_hash() != c.config_hash()
    assert len(a.config_hash()) == 12


def test_make_client_picks_backend() -> None:
    """The factory returns the client for the configured backend."""
    assert isinstance(make_client(LLMConfig.from_env({})), OllamaClient)
    gemini = make_client(LLMConfig.from_env({"PAIR_LLM_BACKEND": "gemini"}))
    assert isinstance(gemini, GeminiClient)


# ── Shared JSON parsing ─────────────────────────────────────────────────────


@pytest.mark.parametrize("text", ["not json", "[1, 2]", "", "null"])
def test_parse_json_object_rejects_non_objects(text: str) -> None:
    """Only a JSON object is a valid reply."""
    with pytest.raises(LLMResponseError):
        llm.parse_json_object(text)


def test_parse_json_object_accepts_fenced_json() -> None:
    """Some models wrap JSON in a markdown fence; the fence is stripped."""
    assert llm.parse_json_object('```json\n{"ahi": 18.2}\n```') == {"ahi": 18.2}


# ── Ollama ──────────────────────────────────────────────────────────────────


class FakePost:
    """Records the request and returns a canned Ollama reply."""

    def __init__(self, reply: dict[str, Any] | bytes | Exception) -> None:
        self.reply = reply
        self.calls: list[tuple[str, dict[str, Any], float]] = []

    def __call__(self, url: str, body: bytes, timeout: float) -> bytes:
        self.calls.append((url, json.loads(body), timeout))
        if isinstance(self.reply, Exception):
            raise self.reply
        if isinstance(self.reply, bytes):
            return self.reply
        return json.dumps(self.reply).encode()


OLLAMA_OK: dict[str, Any] = {
    "model": "gemma4:e4b",
    "response": '{"ahi": 18.2}',
    "done": True,
    "prompt_eval_count": 40,
    "eval_count": 9,
}


def test_ollama_sends_schema_no_thinking_and_num_ctx() -> None:
    """The request carries the JSON schema, ``think: false`` and a per-request context size."""
    post = FakePost(OLLAMA_OK)
    client = OllamaClient(LLMConfig.from_env({"PAIR_LLM_NUM_CTX": "8192"}), post=post)
    result = client.generate_json("Find the AHI.", SCHEMA)

    url, payload, timeout = post.calls[0]
    assert url == "http://localhost:11435/api/generate"
    assert payload["model"] == "gemma4:e4b"
    assert payload["prompt"] == "Find the AHI."
    assert payload["format"] == SCHEMA
    assert payload["think"] is False
    assert payload["stream"] is False
    assert payload["options"] == {"temperature": 0.0, "num_ctx": 8192}
    assert timeout == 300.0

    assert result.data == {"ahi": 18.2}
    assert result.backend is Backend.OLLAMA
    assert result.model == "gemma4:e4b"
    assert result.usage.prompt_tokens == 40
    assert result.usage.output_tokens == 9
    assert result.usage.thinking_tokens is None


def test_ollama_reports_hidden_thinking() -> None:
    """If the server still returns thinking text, its presence is surfaced in usage."""
    post = FakePost({**OLLAMA_OK, "thinking": "let me think"})
    result = OllamaClient(LLMConfig.from_env({}), post=post).generate_json("p", SCHEMA)
    assert result.usage.thinking_present is True


def test_ollama_bad_json_reply_raises_response_error() -> None:
    """A reply whose ``response`` isn't a JSON object is a response error, with the raw text."""
    post = FakePost({**OLLAMA_OK, "response": "AHI is 18"})
    with pytest.raises(LLMResponseError, match="AHI is 18"):
        OllamaClient(LLMConfig.from_env({}), post=post).generate_json("p", SCHEMA)


@pytest.mark.parametrize("body", [b"<html>bad gateway</html>", b"[1, 2]"])
def test_ollama_non_json_envelope_raises_response_error(body: bytes) -> None:
    """A body that isn't Ollama's JSON object envelope is a response error."""
    post = FakePost(body)
    with pytest.raises(LLMResponseError, match="envelope"):
        OllamaClient(LLMConfig.from_env({}), post=post).generate_json("p", SCHEMA)


def test_ollama_server_error_field_raises() -> None:
    """Ollama's ``{"error": ...}`` reply becomes an LLMError naming the model."""
    post = FakePost({"error": "model 'gemma4:e4b' not found"})
    with pytest.raises(LLMError, match="not found"):
        OllamaClient(LLMConfig.from_env({}), post=post).generate_json("p", SCHEMA)


def test_ollama_transport_failure_raises_llm_error() -> None:
    """A refused connection (tunnel down) becomes an LLMError that names the URL."""
    post = FakePost(urllib.error.URLError("Connection refused"))
    with pytest.raises(LLMError, match="localhost:11435"):
        OllamaClient(LLMConfig.from_env({}), post=post).generate_json("p", SCHEMA)


def test_ollama_rejects_gemini_config() -> None:
    """Building an Ollama client from a Gemini config is a config error."""
    with pytest.raises(LLMConfigError):
        OllamaClient(LLMConfig.from_env({"PAIR_LLM_BACKEND": "gemini"}))


def test_http_post_uses_json_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default transport POSTs JSON with the given timeout."""
    seen: dict[str, Any] = {}

    class Response:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def read(self) -> bytes:
            return b"{}"

    def fake_urlopen(request: Any, timeout: float) -> Response:
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["type"] = request.get_header("Content-type")
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert llm.http_post("http://localhost:1/api/generate", b"{}", 5.0) == b"{}"
    assert seen == {
        "url": "http://localhost:1/api/generate",
        "method": "POST",
        "type": "application/json",
        "timeout": 5.0,
    }


# ── Gemini ──────────────────────────────────────────────────────────────────


class FakeModels:
    """Stands in for ``genai.Client().models``."""

    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def gemini_reply(text: str | None, thoughts: int | None = None) -> Any:
    """A minimal object shaped like a ``GenerateContentResponse``."""
    usage = SimpleNamespace(
        prompt_token_count=12, candidates_token_count=5, thoughts_token_count=thoughts
    )
    return SimpleNamespace(text=text, usage_metadata=usage)


def gemini_config() -> LLMConfig:
    """A Gemini config with defaults."""
    return LLMConfig.from_env({"PAIR_LLM_BACKEND": "gemini"})


def test_gemini_sends_schema_and_minimal_thinking() -> None:
    """The call uses JSON mode with the schema and ``thinking_level=MINIMAL`` (ADR-0010)."""
    models = FakeModels(gemini_reply('{"ahi": 18.2}', thoughts=3))
    client = GeminiClient(gemini_config(), sdk=SimpleNamespace(models=models))
    result = client.generate_json("Find the AHI.", SCHEMA)

    call = models.calls[0]
    assert call["model"] == "gemini-3.5-flash"
    assert call["contents"] == "Find the AHI."
    config = call["config"]
    assert isinstance(config, types.GenerateContentConfig)
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == SCHEMA
    assert config.temperature == 0.0
    assert config.thinking_config is not None
    assert config.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL
    assert config.thinking_config.thinking_budget is None

    assert result.data == {"ahi": 18.2}
    assert result.backend is Backend.GEMINI
    assert result.usage.prompt_tokens == 12
    assert result.usage.output_tokens == 5
    assert result.usage.thinking_tokens == 3
    assert result.usage.thinking_present is True


def test_gemini_empty_text_raises_response_error() -> None:
    """A blocked or empty reply is a response error."""
    models = FakeModels(gemini_reply(None))
    client = GeminiClient(gemini_config(), sdk=SimpleNamespace(models=models))
    with pytest.raises(LLMResponseError, match="empty"):
        client.generate_json("p", SCHEMA)


def test_gemini_api_error_raises_llm_error() -> None:
    """An SDK API error becomes an LLMError naming the model."""
    error = genai_errors.ClientError(400, {"error": {"message": "bad request"}})
    models = FakeModels(error)
    client = GeminiClient(gemini_config(), sdk=SimpleNamespace(models=models))
    with pytest.raises(LLMError, match="gemini-3.5-flash"):
        client.generate_json("p", SCHEMA)


def test_gemini_builds_vertex_sdk_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an injected SDK, a Vertex client is built on first use with the configured project."""
    seen: dict[str, Any] = {}
    models = FakeModels(gemini_reply('{"ahi": 1}'))

    def fake_client(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return SimpleNamespace(models=models)

    monkeypatch.setattr("google.genai.Client", fake_client)
    client = GeminiClient(gemini_config())
    assert seen == {}
    client.generate_json("p", SCHEMA)
    assert seen == {
        "vertexai": True,
        "project": "pair-appeal-copilot",
        "location": "global",
    }


def test_gemini_rejects_ollama_config() -> None:
    """Building a Gemini client from an Ollama config is a config error."""
    with pytest.raises(LLMConfigError):
        GeminiClient(LLMConfig.from_env({}))


# ── Live smoke test (opt-in) ────────────────────────────────────────────────


@pytest.mark.llm
def test_live_backend_returns_schema_json() -> None:
    """Real call to the configured backend (needs the lab tunnel or Vertex)."""
    config = LLMConfig.from_env()
    result = make_client(config).generate_json(
        "Sleep study: AHI of 18.2 events per hour. Return the AHI.", SCHEMA
    )
    assert result.data == {"ahi": 18.2}
