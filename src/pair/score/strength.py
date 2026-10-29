"""Appeal strength: IMR base rate, odds shifts per active criterion, abstention (step 7, ADR-0007, ADR-0019).

p starts at the policy group's IMR base rate, is converted to odds, multiplied
by one assumed shift per active criterion outcome (``adjustments.yaml``), and
converted back. The range ends move by the same shift. PAIR abstains ("get a
human") when any of these holds:

1. the unshifted base range is wider than ``max_width`` (too few similar past reviews);
2. an active critical criterion is insufficient;
3. an active any-of group has no met member and an insufficient one.

Base rates come from California IMR reviews of commercial plans; they are not a
guarantee for Medicare Advantage appeals.
"""

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from pair.contracts import (
    Checklist,
    CriterionStatus,
    Explanation,
    Improvement,
    Interval,
    Step,
    Strength,
    Verdict,
)
from pair.rules.active import ContextFlag, active_criteria, any_of_groups
from pair.score.base_model import BaseEstimate

logger = logging.getLogger(__name__)

IMR_NOTE = (
    "Based on California independent medical reviews of commercial health plans. "
    "It is not a guarantee for Medicare Advantage appeals."
)
UNMET_ADVICE = "This requirement isn't met; ask your doctor about alternatives."


class AdjustmentsError(ValueError):
    """``adjustments.yaml`` or ``_ship.yaml`` is invalid."""


@dataclass(frozen=True)
class Adjustments:
    """Assumed odds shifts per outcome, the width rule, and why each shift was chosen."""

    shifts: Mapping[CriterionStatus, float]
    max_width: float
    rationale: Mapping[str, str]


@dataclass(frozen=True)
class ShipLink:
    """A place to get free human help."""

    name: str
    url: str
    note: str


class _Shift(BaseModel):
    value: float = Field(gt=0)
    rationale: str = Field(min_length=1)


class _AdjustmentsFile(BaseModel):
    max_width: float = Field(gt=0, lt=1)
    shifts: dict[CriterionStatus, _Shift]


class _Link(BaseModel):
    name: str = Field(min_length=1)
    url: str = Field(pattern=r"^https://\S+$")
    note: str = ""


class _ShipFile(BaseModel):
    links: list[_Link] = Field(min_length=1)


def _load_yaml(path: Path) -> object:
    """Parse YAML, wrapping syntax errors."""
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        logger.error("invalid YAML %s: %s", path, exc)
        raise AdjustmentsError(f"{path}: {exc}") from exc


def load_adjustments(path: Path) -> Adjustments:
    """Load and validate the odds shifts (one per outcome, each positive with a rationale).

    Raises:
        AdjustmentsError: If the file is invalid or an outcome is missing.
    """
    try:
        parsed = _AdjustmentsFile.model_validate(_load_yaml(path))
    except ValidationError as exc:
        logger.error("invalid adjustments %s: %s", path, exc)
        raise AdjustmentsError(f"{path}: {exc}") from exc
    missing = sorted(set(CriterionStatus) - set(parsed.shifts))
    if missing:
        raise AdjustmentsError(f"{path}: no shift for {missing}")
    return Adjustments(
        shifts={status: shift.value for status, shift in parsed.shifts.items()},
        max_width=parsed.max_width,
        rationale={status.value: shift.rationale.strip() for status, shift in parsed.shifts.items()},
    )


def load_ship_links(path: Path) -> tuple[ShipLink, ...]:
    """Load the "get a human" links.

    Raises:
        AdjustmentsError: If the file is invalid.
    """
    try:
        parsed = _ShipFile.model_validate(_load_yaml(path))
    except ValidationError as exc:
        logger.error("invalid SHIP links %s: %s", path, exc)
        raise AdjustmentsError(f"{path}: {exc}") from exc
    return tuple(ShipLink(link.name, link.url, link.note.strip()) for link in parsed.links)


def odds_shift(p: float, multiplier: float) -> float:
    """Multiply the odds of ``p`` by ``multiplier``; 0 and 1 stay put."""
    if p <= 0.0 or p >= 1.0:
        return p
    odds = p / (1.0 - p) * multiplier
    return odds / (1.0 + odds)


def compute_strength(
    checklist: Checklist,
    verdict: Verdict,
    base: BaseEstimate,
    adjustments: Adjustments,
    flags: Mapping[str, ContextFlag],
) -> Strength:
    """Build the strength estimate, its explanation, and the abstention decision.

    Args:
        checklist: The applied checklist.
        verdict: The rule engine's verdict (not changed).
        base: The unshifted IMR base estimate for the policy group.
        adjustments: Odds shifts and the width rule.
        flags: Context flags with their sources (unsourced = Unknown).

    Raises:
        ValueError: If the verdict is for another policy.
    """
    if verdict.policy_id != checklist.id:
        raise ValueError(f"verdict is for {verdict.policy_id}, not {checklist.id}")
    active = active_criteria(checklist, flags)
    status = {r.criterion_id: r.status for r in verdict.results}
    traces = {r.criterion_id: r.trace for r in verdict.results}
    gaps = {g.criterion_id: g.message for g in verdict.gaps}

    steps = [
        Step(
            criterion_id=cid,
            status=status[cid],
            shift=adjustments.shifts[status[cid]],
            why=traces[cid] if status[cid] is not CriterionStatus.UNMET else f"{traces[cid]} {UNMET_ADVICE}",
        )
        for cid in active
    ]
    multiplier = math.prod(step.shift for step in steps)
    p = odds_shift(base.p, multiplier)
    improve = [
        Improvement(
            criterion_id=step.criterion_id,
            action=gaps.get(step.criterion_id, f"Add records for {step.criterion_id}."),
            p_if_fixed=odds_shift(base.p, multiplier / step.shift * adjustments.shifts[CriterionStatus.MET]),
        )
        for step in steps
        if step.status is CriterionStatus.INSUFFICIENT
    ]
    reasons = _abstain_reasons(checklist, active, status, base, adjustments.max_width)
    interval = Interval(low=odds_shift(base.low, multiplier), high=odds_shift(base.high, multiplier))
    strength = Strength(
        p=min(max(p, interval.low), interval.high),
        interval=interval,
        abstain=bool(reasons),
        abstain_reason=" ".join(reasons) if reasons else None,
        explanation=Explanation(
            base_rate=base.p, n_similar=base.n_similar, imr_category=base.imr_category, steps=steps, improve=improve
        ),
    )
    logger.info("strength %s: p=%.3f [%.3f, %.3f] abstain=%s", checklist.id, strength.p,
                interval.low, interval.high, strength.abstain)
    return strength


def _abstain_reasons(
    checklist: Checklist,
    active: tuple[str, ...],
    status: Mapping[str, CriterionStatus],
    base: BaseEstimate,
    max_width: float,
) -> list[str]:
    """The abstention rules that fire, in plain words."""
    reasons = []
    if base.high - base.low > max_width:
        reasons.append(f"Too few similar past reviews to give a useful range ({base.n_similar} similar reviews).")
    critical = [c.id for c in checklist.criteria if c.critical and c.id in active
                and status[c.id] is CriterionStatus.INSUFFICIENT]
    if critical:
        reasons.append(f"A required item has no record yet: {', '.join(critical)}.")
    for group in any_of_groups(checklist):
        if (any(cid in active for cid in group)
                and not any(status[cid] is CriterionStatus.MET for cid in group)
                and any(status[cid] is CriterionStatus.INSUFFICIENT for cid in group)):
            reasons.append(f"None of these is shown yet, and at least one has no record: {', '.join(group)}.")
    return reasons
