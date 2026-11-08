"""Tests for the conformal report numbers and the pre-registered exit rule (ADR-0020)."""

import pytest

from pair.contracts import ClaimDecision
from pair.eval.trust_stats import (
    ClaimOutcome,
    LetterOutcome,
    RateEstimate,
    clopper_pearson,
    cluster_bootstrap,
    empty_letter_rate,
    exit_verdict,
    leak_rate,
    precision_of_kept,
    support_among_nonempty,
    worst_case_leak_rate,
)

KEEP, FLAG, DROP = ClaimDecision.KEEP, ClaimDecision.FLAG, ClaimDecision.DROP


def c(decision: ClaimDecision | None, label: str | None, criterion: str = "a") -> ClaimOutcome:
    """A claim outcome."""
    return ClaimOutcome(criterion_id=criterion, decision=decision, label=label)  # type: ignore[arg-type]


def letter(patient: str, *claims: ClaimOutcome, gold_met: tuple[str, ...] = ("a", "b")) -> LetterOutcome:
    """A letter outcome for ``patient``."""
    return LetterOutcome(case_id=f"{patient}-case", patient_id=patient, claims=claims, gold_met=frozenset(gold_met))


LETTERS = [
    letter("p1", c(KEEP, "supported"), c(KEEP, "unsupported"), c(FLAG, "partly")),
    letter("p2", c(FLAG, "unsupported"), c(FLAG, "supported")),
    letter("p3", c(KEEP, "supported", "b"), c(DROP, "unsupported")),
    letter("p4", c(KEEP, None), c(FLAG, None), c(None, "unsupported")),
]


def test_leak_rate_counts_kept_strict_negatives_only() -> None:
    """Strict-unsupported = partly or unsupported; DROPPED and not-evaluated claims are out of the set."""
    estimate = leak_rate(LETTERS, seed=0)
    assert (estimate.k, estimate.n) == (1, 3)
    assert estimate.point == pytest.approx(1 / 3)


def test_worst_case_counts_unlabeled_claims_as_unsupported() -> None:
    """Unlabeled kept claims count as leaks, unlabeled flagged ones as caught."""
    estimate = worst_case_leak_rate(LETTERS, seed=0)
    assert (estimate.k, estimate.n) == (2, 5)


def test_empty_letter_rate() -> None:
    """A letter with no KEPT claim is empty, including an all-flagged one (never 'leak 0')."""
    estimate = empty_letter_rate(LETTERS, seed=0)
    assert (estimate.k, estimate.n) == (1, 4)


def test_support_among_nonempty_letters_needs_every_kept_claim_and_conclusion() -> None:
    """p1 has a kept unsupported claim; p3 is supported; p4's kept claim is unlabeled, so not supported."""
    estimate = support_among_nonempty(LETTERS, seed=0)
    assert (estimate.k, estimate.n) == (1, 3)


def test_templated_conclusion_must_be_gold_met() -> None:
    """All claims KEPT and supported, but the criterion isn't gold-met: the conclusion is wrong."""
    letters = [letter("p1", c(KEEP, "supported", "a"), gold_met=("b",))]
    assert support_among_nonempty(letters, seed=0).k == 0


def test_criterion_with_a_flagged_claim_has_no_conclusion_to_check() -> None:
    """A conclusion exists only if every claim of the criterion is KEPT."""
    letters = [letter("p1", c(KEEP, "supported", "a"), c(FLAG, "unsupported", "a"), gold_met=())]
    assert support_among_nonempty(letters, seed=0).k == 1


def test_precision_of_kept_claims() -> None:
    """Supported among labeled KEPT claims."""
    estimate = precision_of_kept(LETTERS, seed=0)
    assert (estimate.k, estimate.n) == (2, 3)


def test_bootstrap_resamples_patients_not_claims() -> None:
    """One patient holds all negatives: every resample is all-leak or none, never in between."""
    units = [(5, 5), (0, 0), (0, 0)]
    draws = cluster_bootstrap(units, n_boot=200, seed=1)
    assert set(draws) == {1.0}


def test_bootstrap_is_seeded() -> None:
    """Same seed, same draws."""
    units = [(1, 3), (0, 2), (2, 2), (0, 1)]
    assert cluster_bootstrap(units, n_boot=50, seed=3) == cluster_bootstrap(units, n_boot=50, seed=3)


def test_bootstrap_with_no_denominator_anywhere_is_empty() -> None:
    """No negatives at all: no draws."""
    assert cluster_bootstrap([(0, 0)], n_boot=10, seed=0) == []


def test_clopper_pearson_known_values() -> None:
    """0 of 10 and 10 of 10 hit the edges; 5 of 10 brackets 0.5."""
    assert clopper_pearson(0, 10)[0] == 0.0
    assert clopper_pearson(10, 10)[1] == 1.0
    low, high = clopper_pearson(5, 10)
    assert low == pytest.approx(0.187, abs=1e-3) and high == pytest.approx(0.813, abs=1e-3)
    assert clopper_pearson(0, 0) == (0.0, 1.0)


def estimate(n: int, point: float, upper: float) -> RateEstimate:
    """A leak estimate with the given n, point and bootstrap upper end."""
    return RateEstimate(k=round(point * n), n=n, point=point, boot_low=0.0, boot_high=upper,
                        naive_low=0.0, naive_high=upper)


@pytest.mark.parametrize(
    ("n", "point", "upper", "verdict"),
    [
        (30, 0.10, 0.25, "pass"),
        (30, 0.15, 0.30, "pass"),
        (29, 0.10, 0.25, "inconclusive"),
        (30, 0.16, 0.25, "inconclusive"),
        (30, 0.10, 0.31, "inconclusive"),
    ],
)
def test_exit_rule_truth_table(n: int, point: float, upper: float, verdict: str) -> None:
    """Pass only if n >= 30, point <= 0.15 and bootstrap upper <= 0.30."""
    assert exit_verdict(estimate(n, point, upper)) == verdict


def test_rates_report_both_intervals() -> None:
    """Every rate carries a bootstrap and a naive interval around its point."""
    result = leak_rate(LETTERS, seed=0)
    assert result.naive_low <= result.point <= result.naive_high
    assert result.boot_low <= result.boot_high


def test_rate_with_no_negatives_is_undefined_and_inconclusive() -> None:
    """No strict-unsupported test claims: point is NaN, intervals are (0, 1), the verdict inconclusive."""
    result = leak_rate([letter("p1", c(KEEP, "supported"))], seed=0)
    assert result.n == 0 and result.point != result.point
    assert (result.boot_low, result.boot_high) == (0.0, 1.0)
    assert exit_verdict(result) == "inconclusive"
