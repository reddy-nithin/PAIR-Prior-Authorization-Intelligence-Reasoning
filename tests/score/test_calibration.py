"""Tests for inductive Venn-Abers and Mondrian conformal sets (ADR-0019)."""

import numpy as np
import pytest
from venn_abers import VennAbers as ReferenceVennAbers

from pair.score.calibration import (
    MondrianSets,
    VennAbers,
    pool_small_groups,
    wilson_floor,
)


def toy(n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Distinct scores with labels drawn from a calibrated-ish model."""
    rng = np.random.default_rng(seed)
    scores = np.sort(rng.uniform(0.02, 0.98, n)) + np.arange(n) * 1e-9
    labels = (rng.uniform(size=n) < scores).astype(int)
    return scores, labels


def test_p0_never_exceeds_p1_and_both_rise_with_the_score() -> None:
    """p0 <= p1 everywhere; both are non-decreasing in the score."""
    scores, labels = toy(200, 0)
    model = VennAbers().fit(scores, labels)
    grid = np.linspace(0.0, 1.0, 41)
    p0, p1 = model.predict(grid)
    assert np.all(p0 <= p1 + 1e-12)
    assert np.all(np.diff(p0) >= -1e-12) and np.all(np.diff(p1) >= -1e-12)


def test_matches_the_venn_abers_package() -> None:
    """Same p0 and p1 as the reference implementation on toy data."""
    scores, labels = toy(120, 1)
    test = np.array([0.05, 0.3, 0.51, 0.77, 0.95])
    ours = VennAbers().fit(scores, labels).predict(test)
    reference = ReferenceVennAbers().fit(np.c_[1 - scores, scores], labels)
    _, p0_p1 = reference.predict_proba(np.c_[1 - test, test])
    assert np.allclose(ours[0], p0_p1[:, 0]) and np.allclose(ours[1], p0_p1[:, 1])


def test_point_estimate_formula() -> None:
    """p = p1 / (1 - p0 + p1) lies within [p0, p1]."""
    p0, p1 = np.array([0.2, 0.0]), np.array([0.4, 1.0])
    p = VennAbers.point(p0, p1)
    assert p == pytest.approx([0.4 / 1.2, 0.5])


def test_fit_needs_both_labels() -> None:
    """A calibration set with one class can't be fit."""
    with pytest.raises(ValueError):
        VennAbers().fit(np.array([0.1, 0.2]), np.array([1, 1]))


def test_small_groups_are_pooled_into_other() -> None:
    """Groups under the minimum become 'other'; others keep their names."""
    groups = np.array(["DME"] * 40 + ["Rx"] * 10 + ["Lab"] * 5)
    pooled = pool_small_groups(groups, minimum=30)
    assert set(pooled) == {"DME", "other"}


def test_mondrian_coverage_on_exchangeable_data() -> None:
    """At 90%, coverage on fresh exchangeable data is close to 90% and set shares add up."""
    rng = np.random.default_rng(5)

    def draw(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        groups = rng.choice(["a", "b"], size=n)
        p = np.where(groups == "a", 0.7, 0.3) + rng.normal(0, 0.05, n)
        y = (rng.uniform(size=n) < p).astype(int)
        return np.clip(p, 0.01, 0.99), y, groups

    model = MondrianSets(alpha=0.1).fit(*draw(2000))
    report = model.evaluate(*draw(4000))
    assert report.coverage == pytest.approx(0.9, abs=0.03)
    assert report.low <= report.coverage <= report.high
    assert report.share_both + report.share_single + report.share_empty == pytest.approx(1.0)
    assert set(report.per_group) == {"a", "b"}


def test_mondrian_unknown_group_uses_other_or_both_labels() -> None:
    """A test group never seen in calibration falls back to 'other', else the full set {0, 1}."""
    model = MondrianSets(alpha=0.1).fit(np.full(40, 0.5), np.array([0, 1] * 20), np.array(["a"] * 40))
    assert model.predict_set(0.5, "zzz") == frozenset({0, 1})


def test_wilson_floor_widens_and_slides_inside_unit_interval() -> None:
    """A narrow range is widened to the Wilson width around p, sliding inside [0, 1] near the edges."""
    low, high, widened = wilson_floor(p=0.5, low=0.49, high=0.51, successes=20, n=40)
    assert widened and high - low > 0.02 and low < 0.5 < high

    low, high, widened = wilson_floor(p=0.02, low=0.01, high=0.03, successes=1, n=40)
    width = high - low
    assert widened and low == 0.0 and high == pytest.approx(width)
    low, high, widened = wilson_floor(p=0.98, low=0.97, high=0.99, successes=39, n=40)
    assert widened and high == 1.0 and high - low == pytest.approx(width)


def test_wilson_floor_keeps_a_wider_range() -> None:
    """If the range is already wider than the floor, it is unchanged."""
    assert wilson_floor(p=0.5, low=0.1, high=0.9, successes=200, n=400) == (0.1, 0.9, False)


def test_coverage_on_an_empty_test_set_is_undefined() -> None:
    """No test rows for a group: coverage NaN, interval (0, 1)."""
    model = MondrianSets(alpha=0.1).fit(np.full(40, 0.5), np.array([0, 1] * 20), np.array(["a"] * 40))
    report = model.evaluate(np.array([]), np.array([]), np.array([]))
    assert report.n == 0 and report.coverage != report.coverage and (report.low, report.high) == (0.0, 1.0)
