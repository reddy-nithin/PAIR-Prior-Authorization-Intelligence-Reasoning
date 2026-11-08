"""Conformal report numbers and the pre-registered exit rule (ADR-0020).

Every rate comes with n, a patient-level cluster-bootstrap 95% interval
(resampling patients, since claims from one patient aren't independent) and a
Clopper-Pearson interval labeled naive (it assumes independent claims). All
numbers are relative to the critic's S1 labels.

Strict-unsupported means S1 ``partly`` or ``unsupported``. DROPPED claims and
claims with no decision ("not evaluated") are outside the conformal sets.
"""

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from scipy.stats import beta

from pair.contracts import ClaimDecision

Label = Literal["supported", "partly", "unsupported"]
Verdict = Literal["pass", "inconclusive"]
Units = list[tuple[int, int]]

N_BOOT = 2000
EXIT_MIN_N = 30
EXIT_MAX_POINT = 0.15
EXIT_MAX_UPPER = 0.30
_EVALUATED = (ClaimDecision.KEEP, ClaimDecision.FLAG)


@dataclass(frozen=True)
class ClaimOutcome:
    """One claim's verifier decision and S1 label (None if unlabeled)."""

    criterion_id: str
    decision: ClaimDecision | None
    label: Label | None


@dataclass(frozen=True)
class LetterOutcome:
    """One test letter: its claims and the criteria that are gold-met for the case."""

    case_id: str
    patient_id: str
    claims: tuple[ClaimOutcome, ...]
    gold_met: frozenset[str]


@dataclass(frozen=True)
class RateEstimate:
    """k of n, with bootstrap and naive 95% intervals."""

    k: int
    n: int
    point: float
    boot_low: float
    boot_high: float
    naive_low: float
    naive_high: float


def clopper_pearson(k: int, n: int, level: float = 0.95) -> tuple[float, float]:
    """Exact binomial interval for k of n; (0, 1) when n = 0."""
    if n == 0:
        return (0.0, 1.0)
    tail = (1 - level) / 2
    low = 0.0 if k == 0 else float(beta.ppf(tail, k, n - k + 1))
    high = 1.0 if k == n else float(beta.ppf(1 - tail, k + 1, n - k))
    return (low, high)


def cluster_bootstrap(units: Units, n_boot: int = N_BOOT, seed: int = 0) -> list[float]:
    """Ratio-of-sums draws from resampling patients with replacement.

    Args:
        units: (numerator, denominator) per patient; every patient is included.
        n_boot: Number of resamples.
        seed: Random seed.

    Returns:
        One rate per resample whose denominator isn't zero.
    """
    rng = random.Random(seed)
    draws = []
    for _ in range(n_boot):
        sample = [units[rng.randrange(len(units))] for _ in units]
        denominator = sum(n for _, n in sample)
        if denominator:
            draws.append(sum(k for k, _ in sample) / denominator)
    return draws


def estimate_rate(units: Units, seed: int) -> RateEstimate:
    """Point, bootstrap percentile and naive intervals from per-patient counts."""
    k = sum(a for a, _ in units)
    n = sum(b for _, b in units)
    draws = sorted(cluster_bootstrap(units, seed=seed))
    if draws:
        boot = (draws[int(0.025 * (len(draws) - 1))], draws[math.ceil(0.975 * (len(draws) - 1))])
    else:
        boot = (0.0, 1.0)
    naive = clopper_pearson(k, n)
    return RateEstimate(k, n, k / n if n else math.nan, boot[0], boot[1], naive[0], naive[1])


def _per_patient(letters: Sequence[LetterOutcome], count: Callable[[LetterOutcome], tuple[int, int]]) -> Units:
    """Sum a per-letter (k, n) count by patient, keeping every patient."""
    totals: dict[str, list[int]] = {}
    for letter in letters:
        k, n = count(letter)
        entry = totals.setdefault(letter.patient_id, [0, 0])
        entry[0] += k
        entry[1] += n
    return [(k, n) for k, n in totals.values()]


def _negative(claim: ClaimOutcome) -> bool:
    """Strict-unsupported and in the conformal set."""
    return claim.decision in _EVALUATED and claim.label in ("partly", "unsupported")


def leak_rate(letters: Sequence[LetterOutcome], seed: int = 0) -> RateEstimate:
    """Share of strict-unsupported, evaluated claims that were KEPT."""

    def count(letter: LetterOutcome) -> tuple[int, int]:
        negatives = [c for c in letter.claims if _negative(c)]
        return sum(c.decision is ClaimDecision.KEEP for c in negatives), len(negatives)

    return estimate_rate(_per_patient(letters, count), seed)


def worst_case_leak_rate(letters: Sequence[LetterOutcome], seed: int = 0) -> RateEstimate:
    """Leak rate with every unlabeled evaluated claim counted as unsupported."""

    def count(letter: LetterOutcome) -> tuple[int, int]:
        negatives = [c for c in letter.claims if _negative(c) or (c.decision in _EVALUATED and c.label is None)]
        return sum(c.decision is ClaimDecision.KEEP for c in negatives), len(negatives)

    return estimate_rate(_per_patient(letters, count), seed)


def _kept(letter: LetterOutcome) -> list[ClaimOutcome]:
    """The letter's KEPT claims."""
    return [c for c in letter.claims if c.decision is ClaimDecision.KEEP]


def empty_letter_rate(letters: Sequence[LetterOutcome], seed: int = 0) -> RateEstimate:
    """Share of letters with no KEPT claim."""
    return estimate_rate(_per_patient(letters, lambda letter: (int(not _kept(letter)), 1)), seed)


def _letter_supported(letter: LetterOutcome) -> bool:
    """Every KEPT claim strictly supported, and every templated conclusion gold-met."""
    if any(c.label != "supported" for c in _kept(letter)):
        return False
    criteria = {c.criterion_id for c in letter.claims}
    concluded = {
        cid for cid in criteria
        if all(c.decision is ClaimDecision.KEEP for c in letter.claims if c.criterion_id == cid)
    }
    return concluded <= letter.gold_met


def support_among_nonempty(letters: Sequence[LetterOutcome], seed: int = 0) -> RateEstimate:
    """Share of non-empty letters whose KEPT claims and conclusions are all supported."""
    return estimate_rate(
        _per_patient(letters, lambda letter: (int(_letter_supported(letter)), 1) if _kept(letter) else (0, 0)), seed
    )


def precision_of_kept(letters: Sequence[LetterOutcome], seed: int = 0) -> RateEstimate:
    """Share of labeled KEPT claims that are strictly supported (descriptive)."""

    def count(letter: LetterOutcome) -> tuple[int, int]:
        labeled = [c for c in _kept(letter) if c.label is not None]
        return sum(c.label == "supported" for c in labeled), len(labeled)

    return estimate_rate(_per_patient(letters, count), seed)


def exit_verdict(leak: RateEstimate) -> Verdict:
    """'pass' only if n ≥ 30, point ≤ 0.15 and bootstrap upper ≤ 0.30; else 'inconclusive'."""
    if leak.n >= EXIT_MIN_N and leak.point <= EXIT_MAX_POINT and leak.boot_high <= EXIT_MAX_UPPER:
        return "pass"
    return "inconclusive"
