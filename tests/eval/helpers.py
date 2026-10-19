"""Helpers for eval tests: a fake note writer that plants every requested phrase."""

import re
from collections.abc import Mapping
from typing import Any

from pair.eval.cases import PatientProfile
from pair.llm import Backend, LLMResult, LLMUsage

PROFILE = PatientProfile(synthea_id="syn-1", age=71, sex="F", conditions=["Hypertension", "Obesity"])
_SECTION = re.compile(r'^(clinic|report):\n((?:- ".*"\n?)+)', re.MULTILINE)


class PhraseWriter:
    """An ``LLMClient`` that writes notes containing exactly the phrases the prompt asks for.

    ``drop`` removes phrases from the first ``fail_times`` replies to exercise retries.
    """

    def __init__(self, drop: str | None = None, fail_times: int = 0, extra: str = "") -> None:
        self.drop = drop
        self.fail_times = fail_times
        self.extra = extra
        self.prompts: list[str] = []

    def generate_json(self, prompt: str, schema: Mapping[str, Any]) -> LLMResult:
        """Return {"clinic": ..., "report": ...} with the requested phrases."""
        self.prompts.append(prompt)
        failing = len(self.prompts) <= self.fail_times
        data: dict[str, Any] = {}
        for doc_id, block in _SECTION.findall(prompt):
            phrases = re.findall(r'- "(.*)"', block)
            kept = [p for p in phrases if not (failing and p == self.drop)]
            data[doc_id] = "Synthetic note. " + ". ".join(kept) + ". " + self.extra
        data.setdefault("clinic", "Synthetic note.")
        data.setdefault("report", "Synthetic report.")
        usage = LLMUsage(prompt_tokens=100, output_tokens=50, thinking_tokens=None)
        return LLMResult(data=data, raw_text="", usage=usage, backend=Backend.GEMINI, model="fake-writer")
