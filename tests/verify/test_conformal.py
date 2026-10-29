"""Tests for the split-conformal threshold on unsupported claims (ADR-0020)."""

import math
from pathlib import Path

import pytest

from pair.contracts import ClaimDecision
from pair.verify.conformal import (
    ConformalError,
    Threshold,
    ThresholdBook,
    conformal_k,
    conformal_quantile,
    decide,
    fit_threshold,
    leak_bound,
)

DRAFTER = "gemma4:e4b"
BACKEND = "minicheck"
MODEL = "bespoke-minicheck"


def fit(scores: list[float]) -> Threshold:
    """Fit on ``scores`` for the Phase 3 pair."""
    return fit_threshold(scores, drafter=DRAFTER, verifier_backend=BACKEND, verifier_model=MODEL)


def test_k_uses_the_n_plus_one_correction() -> None:
    """k = ceil((n + 1)(1 - alpha))."""
    assert conformal_k(9, 0.1) == 9
    assert conformal_k(11, 0.1) == 11
    assert conformal_k(30, 0.1) == 28


def test_quantile_is_finite_at_n9_and_infinite_at_n8() -> None:
    """At alpha 0.1 a finite threshold needs n >= 9."""
    scores = [0.1 * i for i in range(1, 10)]
    assert conformal_quantile(scores, 0.1) == pytest.approx(0.9)
    assert conformal_quantile(scores[:8], 0.1) == math.inf


def test_quantile_is_the_kth_smallest_regardless_of_order() -> None:
    """Input order doesn't matter."""
    scores = [0.5, 0.2, 0.9, 0.1, 0.3, 0.8, 0.4, 0.7, 0.6, 0.05, 0.95, 0.15]
    assert conformal_quantile(scores, 0.1) == sorted(scores)[conformal_k(12, 0.1) - 1]


def test_fit_refuses_below_eleven_negatives() -> None:
    """n < 11: no threshold is fit (ADR-0020)."""
    with pytest.raises(ConformalError, match="11"):
        fit([0.1] * 10)


def test_fit_records_its_pair_and_bound() -> None:
    """The threshold carries (drafter, backend, model), n, k and P(leak > 0.2)."""
    threshold = fit([i / 20 for i in range(11)])
    assert threshold.q_hat == pytest.approx(0.5)
    assert (threshold.n, threshold.k) == (11, 11)
    assert threshold.key == (DRAFTER, BACKEND, MODEL)
    assert threshold.leak_bound == pytest.approx(0.8**11)


def test_gemini_backend_never_gets_a_threshold() -> None:
    """Same-family judge: no threshold, so it can never KEEP (ADR-0018)."""
    with pytest.raises(ConformalError, match="gemini"):
        fit_threshold([0.1] * 20, drafter=DRAFTER, verifier_backend="gemini", verifier_model="gemini-3.5-flash")


def test_leak_bound_matches_the_binomial() -> None:
    """P(leak > 0.2) = P(Binomial(n, 0.2) <= n - k); 0.8^11 at n = k = 11."""
    assert leak_bound(11, 11) == pytest.approx(0.8**11)
    assert leak_bound(30, 28) == pytest.approx(sum(math.comb(30, j) * 0.2**j * 0.8 ** (30 - j) for j in range(3)))


def test_keep_needs_a_score_strictly_above_q_hat() -> None:
    """Ties at q-hat are FLAGGED."""
    threshold = fit([i / 20 for i in range(11)])
    assert decide(0.5, threshold) is ClaimDecision.FLAG
    assert decide(0.5000001, threshold) is ClaimDecision.KEEP
    assert decide(0.1, threshold) is ClaimDecision.FLAG


def test_book_lookup_misses_for_an_unfitted_pair(tmp_path: Path) -> None:
    """Only the fitted pair has a threshold; the book round-trips through JSON."""
    book = ThresholdBook([fit([i / 20 for i in range(11)])])
    path = tmp_path / "thresholds.json"
    book.save(path)
    loaded = ThresholdBook.load(path)

    assert loaded.lookup(DRAFTER, BACKEND, MODEL) == book.lookup(DRAFTER, BACKEND, MODEL)
    assert loaded.lookup("gemma4:e2b-it-qat", BACKEND, MODEL) is None


def test_missing_book_file_is_empty(tmp_path: Path) -> None:
    """No file yet means no thresholds, so every claim is 'not evaluated'."""
    assert ThresholdBook.load(tmp_path / "none.json").lookup(DRAFTER, BACKEND, MODEL) is None


def test_corrupt_book_file_raises(tmp_path: Path) -> None:
    """A malformed threshold file fails loudly."""
    path = tmp_path / "thresholds.json"
    path.write_text("[{}]")
    with pytest.raises(ConformalError):
        ThresholdBook.load(path)


def test_book_rejects_duplicate_pairs() -> None:
    """One threshold per (drafter, verifier) pair."""
    threshold = fit([i / 20 for i in range(11)])
    with pytest.raises(ConformalError, match="duplicate"):
        ThresholdBook([threshold, threshold])
