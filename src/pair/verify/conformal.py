"""Split-conformal threshold on unsupported claims (step 6, ADR-0020).

q̂ is the k-th smallest verifier score among the n unsupported calibration
claims, k = ⌈(n+1)(1−α)⌉. A claim is KEPT only if its score is strictly above q̂.
On average over calibration sets, a new unsupported claim gets through at most
α of the time. For the threshold actually fit, P(leak > 0.2) is reported too.

A threshold belongs to one (drafter model, verifier backend, verifier model)
pair (ADR-0018). The Gemini judge never gets one, and fewer than 11 unsupported
calibration claims means no threshold at all (ADR-0020, ADR-0021).
"""

import json
import logging
import math
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from scipy.stats import binom

from pair.contracts import ClaimDecision
from pair.verify.nli import PREMISE_RULE

logger = logging.getLogger(__name__)

ALPHA = 0.1
MIN_NEGATIVES = 11
LEAK_LIMIT = 0.2
NO_THRESHOLD_BACKENDS = frozenset({"gemini"})

PairKey = tuple[str, str, str]


class ConformalError(ValueError):
    """A threshold can't be fit, loaded or applied."""


def conformal_k(n: int, alpha: float) -> int:
    """The rank k = ⌈(n+1)(1−α)⌉ (rounded first, so 10.8 stays 11 and 9.0 stays 9)."""
    return math.ceil(round((n + 1) * (1 - alpha), 9))


def conformal_quantile(scores: Sequence[float], alpha: float) -> float:
    """The k-th smallest score, or ``inf`` when k > n (too few scores for a finite q̂)."""
    k = conformal_k(len(scores), alpha)
    if k > len(scores):
        return math.inf
    return sorted(scores)[k - 1]


def leak_bound(n: int, k: int, leak: float = LEAK_LIMIT) -> float:
    """P(realized leak rate > ``leak``) for a threshold fit at rank k of n: BinomCDF(n − k; n, leak)."""
    return float(binom.cdf(n - k, n, leak))


@dataclass(frozen=True)
class Threshold:
    """A fitted q̂ and the (drafter, verifier) pair it belongs to."""

    q_hat: float
    n: int
    k: int
    alpha: float
    drafter: str
    verifier_backend: str
    verifier_model: str
    premise_rule: str = PREMISE_RULE
    leak_bound: float = field(default=math.nan, compare=False)

    def __post_init__(self) -> None:
        """Fill in P(leak > 0.2) when not given."""
        if math.isnan(self.leak_bound):
            object.__setattr__(self, "leak_bound", leak_bound(self.n, self.k))

    @property
    def key(self) -> PairKey:
        """(drafter, verifier backend, verifier model)."""
        return (self.drafter, self.verifier_backend, self.verifier_model)


def fit_threshold(
    unsupported_scores: Sequence[float],
    drafter: str,
    verifier_backend: str,
    verifier_model: str,
    alpha: float = ALPHA,
    premise_rule: str = PREMISE_RULE,
) -> Threshold:
    """Fit q̂ on the verifier scores of strict-unsupported calibration claims.

    Raises:
        ConformalError: If the backend never gets a threshold, or there are fewer
            than ``MIN_NEGATIVES`` scores.
    """
    if verifier_backend in NO_THRESHOLD_BACKENDS:
        raise ConformalError(f"the {verifier_backend} verifier never gets a threshold (ADR-0018)")
    n = len(unsupported_scores)
    if n < MIN_NEGATIVES:
        raise ConformalError(f"{n} unsupported calibration claims; at least {MIN_NEGATIVES} are needed (ADR-0020)")
    threshold = Threshold(
        q_hat=conformal_quantile(unsupported_scores, alpha), n=n, k=conformal_k(n, alpha), alpha=alpha,
        drafter=drafter, verifier_backend=verifier_backend, verifier_model=verifier_model, premise_rule=premise_rule,
    )
    logger.info("fitted q_hat=%.4f on n=%d (k=%d), P(leak>0.2)=%.3f for %s",
                threshold.q_hat, n, threshold.k, threshold.leak_bound, threshold.key)
    return threshold


def decide(score: float, threshold: Threshold) -> ClaimDecision:
    """KEEP iff ``score`` is strictly above q̂, else FLAG."""
    return ClaimDecision.KEEP if score > threshold.q_hat else ClaimDecision.FLAG


class ThresholdBook:
    """Fitted thresholds by (drafter, verifier backend, verifier model)."""

    def __init__(self, thresholds: Iterable[Threshold] = ()) -> None:
        """Index thresholds by pair.

        Raises:
            ConformalError: If two thresholds share a pair.
        """
        self._by_key: dict[PairKey, Threshold] = {}
        for threshold in thresholds:
            if threshold.key in self._by_key:
                raise ConformalError(f"duplicate threshold for {threshold.key}")
            self._by_key[threshold.key] = threshold

    def lookup(self, drafter: str, verifier_backend: str, verifier_model: str) -> Threshold | None:
        """The pair's threshold, or None (its claims are then 'not evaluated')."""
        return self._by_key.get((drafter, verifier_backend, verifier_model))

    def with_threshold(self, threshold: Threshold) -> "ThresholdBook":
        """A new book with ``threshold`` added, replacing any for the same pair."""
        return ThresholdBook([*(t for t in self._by_key.values() if t.key != threshold.key), threshold])

    def save(self, path: Path) -> None:
        """Write all thresholds as JSON."""
        path.write_text(json.dumps([asdict(t) for t in self._by_key.values()], indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> "ThresholdBook":
        """Read thresholds; a missing file is an empty book.

        Raises:
            ConformalError: If the file is malformed.
        """
        if not path.exists():
            return cls()
        try:
            return cls(Threshold(**row) for row in json.loads(path.read_text()))
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error("invalid threshold file %s: %s", path, exc)
            raise ConformalError(f"{path}: {exc}") from exc
