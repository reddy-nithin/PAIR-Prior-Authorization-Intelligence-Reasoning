"""Shared fakes for tests that need an LLM client (no network)."""

from collections.abc import Mapping
from typing import Any

from pair.llm import Backend, LLMResult, LLMUsage, parse_json_object


class FakeLLM:
    """An ``LLMClient`` that replays canned replies and records every prompt.

    Each reply is a dict (returned as JSON), a string (parsed like a real reply,
    so invalid JSON raises ``LLMResponseError``) or an exception (raised).
    """

    def __init__(self, replies: list[dict[str, Any] | str | Exception]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.schemas: list[Mapping[str, Any]] = []

    def generate_json(self, prompt: str, schema: Mapping[str, Any]) -> LLMResult:
        """Return the next canned reply."""
        self.prompts.append(prompt)
        self.schemas.append(schema)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        data = parse_json_object(reply) if isinstance(reply, str) else reply
        usage = LLMUsage(prompt_tokens=len(prompt) // 4, output_tokens=10, thinking_tokens=None)
        return LLMResult(data=data, raw_text=str(reply), usage=usage, backend=Backend.OLLAMA, model="fake")
