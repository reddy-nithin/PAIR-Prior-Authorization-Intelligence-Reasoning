"""A LangExtract format handler that drops malformed items instead of whole chunks.

LangExtract rejects a whole chunk when any one item's span isn't a string or
number (e.g. a list for ``group2_conditions``), losing every fact in it. This
handler removes just the bad item, counts it as malformed (reported as an
ungrounded extraction), and counts null spans as "not found" placeholders.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from langextract import data
from langextract.core import format_handler as fh


class TolerantFormatHandler(fh.FormatHandler):
    """JSON handler with ``{"extractions": [...]}`` wrapper, no fences, per-item validation."""

    def __init__(self) -> None:
        super().__init__(
            format_type=data.FormatType.JSON,
            use_wrapper=True,
            wrapper_key=data.EXTRACTIONS_KEY,
            use_fences=False,
        )
        self.malformed = 0
        self.nulls = 0

    def reset(self) -> None:
        """Zero the counters."""
        self.malformed = 0
        self.nulls = 0

    def parse_output(self, text: str, *, strict: bool | None = None) -> Sequence[Mapping[str, Any]]:
        """Parse model output and keep only well-formed extraction items."""
        groups = super().parse_output(text, strict=strict)
        cleaned: list[dict[str, Any]] = []
        for group in groups:
            kept = self._clean_group(group)
            if kept:
                cleaned.append(kept)
        return cleaned

    def _clean_group(self, group: Mapping[str, Any]) -> dict[str, Any]:
        """Drop bad spans (with their attributes) and non-dict attributes from one group."""
        suffix = self.attribute_suffix
        bad: set[str] = set()
        for key, value in group.items():
            if key.endswith(suffix):
                continue
            if value is None:
                self.nulls += 1
                bad.add(key)
            elif isinstance(value, bool) or not isinstance(value, (str, int, float)):
                self.malformed += 1
                bad.add(key)
        kept: dict[str, Any] = {}
        for key, value in group.items():
            if key.endswith(suffix):
                if key.removesuffix(suffix) in bad or not isinstance(value, dict):
                    continue
            elif key in bad:
                continue
            kept[key] = value
        return kept
