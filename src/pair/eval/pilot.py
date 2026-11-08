"""ADR-0021 pilot: size fresh dev and test pools from the dev-only claim counts.

From the labeled ``cases-dev-v4`` claims: C claims, U strict-unsupported,
r̂ = U / C, m = C / n_cases. Sizing uses the cautious rate r_c = 0.75 · r̂
(r̂'s cluster-bootstrap interval is reported, not used). e = r_c · m expected
negatives per case; N_dev = ⌈max(0, 11 − U) / e⌉, N_test = max(0, ⌈30 / e⌉ − 30).
Caps: N_dev ≤ 60, N_test ≤ 120.
"""

import logging
import math
import random
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Literal

from pair.eval.trust_stats import RateEstimate, Units, estimate_rate
from pair.verify.conformal import MIN_NEGATIVES

logger = logging.getLogger(__name__)

CAUTION = 0.75
TEST_MIN_NEGATIVES = 30
EXISTING_TEST_CASES = 30
CAP_DEV = 60
CAP_TEST = 120
AUDIT_FRACTION = 0.2

Path_ = Literal["pools", "test_over_cap", "no_pools"]


class PoolError(ValueError):
    """The pilot can't be sized, or new pools overlap."""


@dataclass(frozen=True)
class PoolSizing:
    """Every number of the sizing rule, and which ADR-0021 path applies.

    ``path``: ``pools`` (both within cap), ``test_over_cap`` (dev pool only,
    inconclusive accepted on stated terms), ``no_pools`` (N_dev over cap).
    """

    claims: int
    unsupported: int
    r_hat: float
    r_c: float
    m: float
    e: float
    n_dev: float
    n_test: float
    dev_within_cap: bool
    test_within_cap: bool
    path: Path_


def _ceil(x: float) -> float:
    """Ceiling that ignores float noise (60.0000000001 stays 60); infinity stays infinite."""
    return x if math.isinf(x) else float(math.ceil(round(x, 9)))


def size_pools(claims: int, unsupported: int, n_cases: int, e_override: float | None = None) -> PoolSizing:
    """Apply the ADR-0021 sizing rule.

    Args:
        claims: C, dev claims after span and link drops.
        unsupported: U, strict-unsupported among them.
        n_cases: Dev cases drafted (30 for ``cases-dev-v4``).
        e_override: Use this e instead of r_c · m (tests of the cap boundaries only).

    Raises:
        PoolError: If there are no claims.
    """
    if claims <= 0 or n_cases <= 0:
        raise PoolError("the pilot has no claims to size from")
    r_hat = unsupported / claims
    r_c = CAUTION * r_hat
    m = claims / n_cases
    e = r_c * m if e_override is None else e_override
    if e > 0:
        n_dev = _ceil(max(0, MIN_NEGATIVES - unsupported) / e)
        n_test = max(0.0, _ceil(TEST_MIN_NEGATIVES / e) - EXISTING_TEST_CASES)
    else:
        n_dev = 0.0 if unsupported >= MIN_NEGATIVES else math.inf
        n_test = math.inf
    dev_ok, test_ok = n_dev <= CAP_DEV, n_test <= CAP_TEST
    path: Path_ = "no_pools" if not dev_ok else "test_over_cap" if not test_ok else "pools"
    sizing = PoolSizing(claims, unsupported, r_hat, r_c, m, e, n_dev, n_test, dev_ok, test_ok, path)
    logger.info("pilot sizing: %s", sizing)
    return sizing


def pilot_rate(per_patient: Units, seed: int = 0) -> RateEstimate:
    """r̂ with its patient-level cluster-bootstrap 95% interval (reported, not used for sizing)."""
    return estimate_rate(per_patient, seed)


def check_disjoint(dev: AbstractSet[str], test: AbstractSet[str], existing: AbstractSet[str]) -> None:
    """New dev and test pools share no Synthea id with each other or the existing patients.

    Raises:
        PoolError: Naming the shared ids.
    """
    shared = sorted((dev & test) | ((dev | test) & existing))
    if shared:
        raise PoolError(f"pools share Synthea ids: {shared}")


def audit_sample(case_ids: Sequence[str], seed: int, fraction: float = AUDIT_FRACTION) -> tuple[str, ...]:
    """A seeded random ``fraction`` of new cases for the critic case audit, sorted."""
    ordered = sorted(case_ids)
    return tuple(sorted(random.Random(seed).sample(ordered, math.ceil(fraction * len(ordered)))))
