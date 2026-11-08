"""Calibration for the IMR base rate: inductive Venn-Abers, Mondrian sets and the Wilson floor (ADR-0019).

- **Venn-Abers** turns a model score into a range ``[p0, p1]``: isotonic
  regression on the calibration scores plus the test score, labeled 0 and then 1.
  The range shows how much calibration data there is; it isn't a probability
  interval for this case.
- **Mondrian conformal sets** at 90%, per ``TreatmentCategory``, are the validity
  number: the share of new cases whose true outcome is in their set.
- **Wilson floor**: a policy group's shown range is never narrower than a 90%
  Wilson interval on its own overturn rate; it slides inside [0, 1], never clipped.
"""

import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Self

import numpy as np
from numpy.typing import ArrayLike, NDArray
from sklearn.isotonic import IsotonicRegression

from pair.eval.trust_stats import clopper_pearson
from pair.verify.conformal import conformal_quantile

logger = logging.getLogger(__name__)

MIN_GROUP_ROWS = 30
OTHER = "other"
WILSON_Z = 1.6448536269514722
"""Two-sided 90%."""

FloatArray = NDArray[np.float64]


class VennAbers:
    """Inductive Venn-Abers on one calibration set of scores and 0/1 labels."""

    def __init__(self) -> None:
        """Create an unfitted calibrator."""
        self._scores: FloatArray = np.empty(0)
        self._labels: FloatArray = np.empty(0)

    def fit(self, scores: ArrayLike, labels: ArrayLike) -> Self:
        """Store the calibration set.

        Raises:
            ValueError: If lengths differ or only one label is present.
        """
        s = np.asarray(scores, dtype=float)
        y = np.asarray(labels, dtype=float)
        if s.shape != y.shape or len(set(y.tolist())) < 2:
            raise ValueError("Venn-Abers needs matching scores and labels with both classes present")
        self._scores, self._labels = s, y
        return self

    def predict(self, scores: ArrayLike) -> tuple[FloatArray, FloatArray]:
        """``(p0, p1)`` for each test score (computed once per distinct score)."""
        test = np.asarray(scores, dtype=float)
        unique, inverse = np.unique(test, return_inverse=True)
        p0 = np.array([self._fit_at(s, 0.0) for s in unique])
        p1 = np.array([self._fit_at(s, 1.0) for s in unique])
        return p0[inverse], p1[inverse]

    def _fit_at(self, score: float, label: float) -> float:
        """Isotonic fit on calibration plus (score, label), evaluated at score."""
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        iso.fit(np.append(self._scores, score), np.append(self._labels, label))
        return float(iso.predict([score])[0])

    @staticmethod
    def point(p0: ArrayLike, p1: ArrayLike) -> FloatArray:
        """The single estimate p = p1 / (1 − p0 + p1)."""
        a = np.asarray(p0, dtype=float)
        b = np.asarray(p1, dtype=float)
        return np.asarray(b / (1.0 - a + b), dtype=float)


def pool_small_groups(groups: ArrayLike, minimum: int = MIN_GROUP_ROWS) -> NDArray[np.str_]:
    """Rename groups with fewer than ``minimum`` rows to ``other``."""
    values = np.asarray(groups, dtype=str)
    counts = Counter(values.tolist())
    return np.array([g if counts[g] >= minimum else OTHER for g in values.tolist()], dtype=str)


@dataclass(frozen=True)
class GroupCoverage:
    """Coverage for one group, with its Clopper-Pearson 95% interval."""

    n: int
    coverage: float
    low: float
    high: float


@dataclass(frozen=True)
class CoverageReport:
    """Coverage of the prediction sets on a test set, and how informative the sets are."""

    n: int
    coverage: float
    low: float
    high: float
    share_both: float
    share_single: float
    share_empty: float
    per_group: dict[str, GroupCoverage] = field(default_factory=dict)


def _coverage(hits: list[bool]) -> GroupCoverage:
    """Coverage of a list of hit flags."""
    k, n = sum(hits), len(hits)
    low, high = clopper_pearson(k, n)
    return GroupCoverage(n, k / n if n else math.nan, low, high)


class MondrianSets:
    """Mondrian split-conformal prediction sets for a binary outcome, one q̂ per group."""

    def __init__(self, alpha: float = 0.1) -> None:
        """Create unfitted sets at miscoverage ``alpha``."""
        self.alpha = alpha
        self._q: dict[str, float] = {}

    def fit(self, scores: ArrayLike, labels: ArrayLike, groups: ArrayLike) -> Self:
        """Fit q̂ per group (groups under 30 rows pooled into ``other``) on nonconformity 1 − P(true label)."""
        s = np.asarray(scores, dtype=float)
        y = np.asarray(labels, dtype=int)
        g = pool_small_groups(groups)
        nonconformity = np.where(y == 1, 1.0 - s, s)
        self._q = {
            name: conformal_quantile(nonconformity[g == name].tolist(), self.alpha) for name in sorted(set(g.tolist()))
        }
        logger.info("Mondrian q-hat per group: %s", self._q)
        return self

    def predict_set(self, score: float, group: str) -> frozenset[int]:
        """Labels whose nonconformity is within the group's q̂ (unknown group: ``other``, else both)."""
        q = self._q.get(group, self._q.get(OTHER, math.inf))
        return frozenset(label for label, a in ((1, 1.0 - score), (0, score)) if a <= q)

    def evaluate(self, scores: ArrayLike, labels: ArrayLike, groups: ArrayLike) -> CoverageReport:
        """Coverage overall (Clopper-Pearson) and per given group, plus set-size shares."""
        sets = [self.predict_set(float(s), str(g)) for s, g in zip(np.asarray(scores), np.asarray(groups), strict=True)]
        y = np.asarray(labels, dtype=int).tolist()
        hits = [label in found for label, found in zip(y, sets, strict=True)]
        overall = _coverage(hits)
        by_group: dict[str, list[bool]] = {}
        for g, hit in zip(np.asarray(groups, dtype=str).tolist(), hits, strict=True):
            by_group.setdefault(g, []).append(hit)
        n = len(sets)
        if n == 0:
            return CoverageReport(0, math.nan, 0.0, 1.0, math.nan, math.nan, math.nan)
        return CoverageReport(
            n=n, coverage=overall.coverage, low=overall.low, high=overall.high,
            share_both=sum(len(x) == 2 for x in sets) / n,
            share_single=sum(len(x) == 1 for x in sets) / n,
            share_empty=sum(len(x) == 0 for x in sets) / n,
            per_group={g: _coverage(h) for g, h in sorted(by_group.items())},
        )


def wilson_width(successes: int, n: int, z: float = WILSON_Z) -> float:
    """Width of the Wilson score interval for ``successes`` of ``n``."""
    phat = successes / n
    return 2 * z / (1 + z * z / n) * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))


def wilson_floor(p: float, low: float, high: float, successes: int, n: int) -> tuple[float, float, bool]:
    """Widen ``[low, high]`` around ``p`` to at least the 90% Wilson width, sliding inside [0, 1].

    Returns:
        ``(low, high, widened)``.
    """
    width = wilson_width(successes, n)
    if high - low >= width:
        return low, high, False
    new_low, new_high = p - width / 2, p + width / 2
    if new_low < 0.0:
        new_low, new_high = 0.0, width
    elif new_high > 1.0:
        new_low, new_high = 1.0 - width, 1.0
    return new_low, new_high, True
