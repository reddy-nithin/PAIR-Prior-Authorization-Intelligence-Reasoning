"""IMR argument exemplars: overturned findings used as tone examples for drafting (spec §5.4).

Findings text is written after the IMR decision, so it must never become a
strength-score feature. It flows only into drafting prompts, and the test suite
checks that no ``pair.score`` module imports ``pair.draft``.
"""

import logging
from pathlib import Path

from pair.score.imr_data import load_imr_features, load_imr_findings
from pair.score.imr_mapping import PolicyImrMapping, select_rows

logger = logging.getLogger(__name__)


def load_exemplars(
    path: Path | None, mapping: PolicyImrMapping, n: int = 2, max_chars: int = 400
) -> tuple[str, ...]:
    """Pick the newest overturned findings for one policy group.

    Args:
        path: The IMR determinations CSV, or None to draft without exemplars.
        mapping: Which IMR rows count as this policy's group.
        n: How many exemplars at most.
        max_chars: Longer findings are cut to this length, ending in "...".

    Returns:
        Up to ``n`` findings, newest report year first (ties by reference id).

    Raises:
        FileNotFoundError: If ``path`` is given but doesn't exist.
    """
    if path is None:
        return ()
    if not path.exists():
        raise FileNotFoundError(f"IMR file not found: {path}")
    features = load_imr_features(path)
    findings = load_imr_findings(path)
    mask = (select_rows(features, mapping) & (features["label"] == 1).fillna(False)).astype(bool)
    picked = findings.loc[mask].assign(year=features.loc[mask, "report_year"])
    picked = picked[picked["findings"].fillna("").str.strip() != ""]
    picked = picked.sort_values(["year", "reference_id"], ascending=[False, True]).head(n)
    exemplars = tuple(_truncate(str(text), max_chars) for text in picked["findings"])
    logger.info("loaded %d IMR exemplars from %s", len(exemplars), path.name)
    return exemplars


def _truncate(text: str, max_chars: int) -> str:
    """Cut ``text`` to at most ``max_chars``, marking the cut with "..."."""
    return text if len(text) <= max_chars else text[: max_chars - 3].rstrip() + "..."
