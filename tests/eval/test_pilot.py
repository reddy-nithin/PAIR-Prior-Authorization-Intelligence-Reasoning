"""Tests for the ADR-0021 pilot sizing rule and the fresh-pool checks."""

import math

import pytest

from pair.eval.pilot import PoolError, audit_sample, check_disjoint, size_pools


def test_u_at_least_eleven_needs_no_new_dev_cases() -> None:
    """Enough dev negatives already: N_dev = 0."""
    sizing = size_pools(claims=300, unsupported=12, n_cases=30)
    assert sizing.n_dev == 0


def test_formula_on_toy_counts() -> None:
    """r_c = 0.75 r-hat, e = r_c m, N_dev = ceil((11 - U) / e), N_test = ceil(30 / e) - 30."""
    sizing = size_pools(claims=300, unsupported=6, n_cases=30)
    assert sizing.r_hat == pytest.approx(0.02)
    assert sizing.r_c == pytest.approx(0.75 * 0.02)
    assert sizing.m == pytest.approx(10.0)
    assert sizing.e == pytest.approx(0.15)
    assert sizing.n_dev == math.ceil(5 / 0.15)
    assert sizing.n_test == math.ceil(30 / 0.15) - 30
    assert sizing.path == "test_over_cap"


def test_zero_unsupported_is_infinite_and_over_cap() -> None:
    """U = 0: e = 0, both counts infinite, no pools."""
    sizing = size_pools(claims=300, unsupported=0, n_cases=30)
    assert sizing.e == 0.0 and sizing.n_dev == math.inf and sizing.n_test == math.inf
    assert sizing.path == "no_pools"


@pytest.mark.parametrize(
    ("unsupported", "claims", "path"),
    [
        (60, 300, "pools"),
        (6, 300, "test_over_cap"),
    ],
)
def test_paths(unsupported: int, claims: int, path: str) -> None:
    """Both within cap: pools; only dev within cap: dev pool, test over cap."""
    assert size_pools(claims=claims, unsupported=unsupported, n_cases=30).path == path


def test_cap_boundaries() -> None:
    """N_dev 60 is within the cap, 61 is over; N_test 120 within, 121 over."""
    within = size_pools(claims=300, unsupported=6, n_cases=30, e_override=5 / 60)
    over = size_pools(claims=300, unsupported=6, n_cases=30, e_override=5 / 61)
    assert within.n_dev == 60 and within.dev_within_cap
    assert over.n_dev == 61 and not over.dev_within_cap
    test_in = size_pools(claims=300, unsupported=11, n_cases=30, e_override=30 / 150)
    test_out = size_pools(claims=300, unsupported=11, n_cases=30, e_override=30 / 151)
    assert test_in.n_test == 120 and test_in.test_within_cap
    assert test_out.n_test == 121 and not test_out.test_within_cap


def test_no_claims_is_an_error() -> None:
    """A pilot with no claims can't be sized."""
    with pytest.raises(PoolError):
        size_pools(claims=0, unsupported=0, n_cases=30)


def test_new_pools_must_be_disjoint() -> None:
    """Any shared Synthea id between new dev, new test or the existing 40 fails."""
    check_disjoint({"a", "b"}, {"c"}, existing={"x"})
    with pytest.raises(PoolError, match="b"):
        check_disjoint({"a", "b"}, {"b"}, existing=set())
    with pytest.raises(PoolError, match="x"):
        check_disjoint({"x"}, {"c"}, existing={"x"})


def test_audit_sample_is_twenty_percent_seeded_and_reproducible() -> None:
    """ceil(20%) of cases, the same for the same seed, sorted."""
    ids = [f"case-{i:02d}" for i in range(23)]
    sample = audit_sample(ids, seed=11)
    assert len(sample) == 5
    assert sample == audit_sample(list(reversed(ids)), seed=11)
    assert sample == tuple(sorted(sample))


def test_pilot_rate_reports_a_patient_bootstrap_interval() -> None:
    """r-hat with its cluster-bootstrap interval."""
    from pair.eval.pilot import pilot_rate

    rate = pilot_rate([(1, 10), (0, 12), (2, 8)], seed=0)
    assert (rate.k, rate.n) == (3, 30)
    assert rate.boot_low <= rate.point <= rate.boot_high
