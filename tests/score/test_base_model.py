"""Tests for the IMR base model: splits, level pooling, model/window choice, group estimates (ADR-0019)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pair.score.base_model import (
    CANDIDATE_MODELS,
    WINDOWS,
    BaseModelError,
    LevelPooler,
    feature_matrix,
    fit_base_model,
    load_base_model,
    save_base_model,
    split_years,
)
from pair.score.calibration import wilson_width
from pair.score.imr_data import FEATURE_COLUMNS, load_imr_features
from pair.score.imr_mapping import PolicyImrMapping

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "imr" / "fake_imr.csv"
MAPPINGS = {
    "pap-osa": PolicyImrMapping(rationale="t", match_any=[{"TreatmentSubCategory": ["C-Pap Machine"]}]),
    "facet-joint": PolicyImrMapping(rationale="t", match_any=[{"TreatmentSubCategory": ["Nerve Block"]}]),
}


def synthetic(n: int = 4000, seed: int = 0) -> pd.DataFrame:
    """A fake IMR frame with signal in the treatment category and a little drift."""
    rng = np.random.default_rng(seed)
    cats = rng.choice(["DME", "Pharmacy", "Pain Management", "Diagnostic"], size=n, p=[0.3, 0.4, 0.2, 0.1])
    subs = np.where(cats == "DME", rng.choice(["C-Pap Machine", "Oxygen", "Other"], size=n),
                    np.where(cats == "Pain Management", "Nerve Block", rng.choice(["Other", "Brand Name"], size=n)))
    years = rng.integers(2005, 2027, size=n)
    base = {"DME": 0.6, "Pharmacy": 0.35, "Pain Management": 0.45, "Diagnostic": 0.5}
    p = np.array([base[c] for c in cats]) + (years - 2015) * 0.005
    frame = pd.DataFrame({
        "DiagnosisCategory": rng.choice(["Respiratory System", "Orth/Musculoskeletal", "Mental"], size=n),
        "DiagnosisSubCategory": np.array(["Sleep Apnea", "Back Pain", "Other", None], dtype=object)[rng.integers(0, 4, size=n)],
        "TreatmentCategory": cats,
        "TreatmentSubCategory": subs,
        "Type": rng.choice(["Medical Necessity", "Experimental/Investigational"], size=n),
        "AgeRange": np.array(["41 to 50", "51 to 64", "65+", None], dtype=object)[rng.integers(0, 4, size=n)],
        "PatientGender": rng.choice(["Female", "Male"], size=n),
        "IMRType": rng.choice(["Standard", "Expedited"], size=n),
    }).astype("category")
    frame["report_year"] = pd.array(years, dtype="Int16")
    frame["label"] = pd.array((rng.uniform(size=n) < p).astype(int), dtype="Int8")
    return frame


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    """Shared synthetic frame."""
    return synthetic()


@pytest.fixture(scope="module")
def model(frame: pd.DataFrame):  # type: ignore[no-untyped-def]
    """A base model fit on the synthetic frame."""
    return fit_base_model(frame, MAPPINGS, seed=0)


def test_split_never_leaks_years(frame: pd.DataFrame) -> None:
    """Train <= 2022, calibration = 2023, test >= 2024, and every row lands in one split."""
    train, calib, test = split_years(frame)
    assert train["report_year"].max() <= 2022
    assert set(calib["report_year"]) == {2023}
    assert test["report_year"].min() >= 2024
    assert len(train) + len(calib) + len(test) == len(frame)


def test_pooler_caps_levels_and_maps_unseen_to_other() -> None:
    """At most 250 levels per feature (native categoricals allow 255); unseen and rare levels become 'other'."""
    n = 3000
    wide = pd.DataFrame({c: ["x"] * n for c in FEATURE_COLUMNS})
    wide["DiagnosisSubCategory"] = [f"level-{i % 600}" for i in range(n)]
    pooler = LevelPooler().fit(wide)
    out = pooler.transform(wide)
    assert out["DiagnosisSubCategory"].nunique() <= 250
    unseen = pooler.transform(wide.assign(TreatmentCategory="never seen"))
    assert set(unseen["TreatmentCategory"]) == {"other"}


def test_feature_matrix_has_only_pre_decision_columns(frame: pd.DataFrame) -> None:
    """Findings and review-timing columns never reach the model, even if present in the frame."""
    leaky = frame.assign(Findings="text", DaysToReview=1, DaysToAdopt=2)
    assert list(feature_matrix(leaky).columns) == list(FEATURE_COLUMNS)


def test_selection_table_covers_every_model_and_window(model) -> None:  # type: ignore[no-untyped-def]
    """2 models x 3 windows, picked by the lowest 2023 Brier score."""
    table = model.selection
    assert len(table) == len(CANDIDATE_MODELS) * len(WINDOWS)
    best = min(table, key=lambda row: row.brier_2023)
    assert (model.model_name, model.window) == (best.model, best.window)


def test_test_years_never_affect_the_fit(frame: pd.DataFrame, model) -> None:  # type: ignore[no-untyped-def]
    """Flipping every 2024+ label changes nothing about the fitted model."""
    flipped = frame.copy()
    mask = flipped["report_year"] >= 2024
    flipped.loc[mask, "label"] = 1 - flipped.loc[mask, "label"]
    other = fit_base_model(flipped, MAPPINGS, seed=0)
    assert other.estimate("pap-osa") == model.estimate("pap-osa")
    assert [r.brier_2023 for r in other.selection] == [r.brier_2023 for r in model.selection]


def test_group_estimate_is_floored_and_counted(frame: pd.DataFrame, model) -> None:  # type: ignore[no-untyped-def]
    """p inside the range, range at least the Wilson width, n_similar = group rows in window + 2023."""
    estimate = model.estimate("pap-osa")
    assert estimate.low <= estimate.p <= estimate.high
    train, calib, _ = split_years(frame)
    group = pd.concat([train, calib])
    in_window = WINDOWS[model.window].mask(group["report_year"])
    rows = group[in_window & (group["TreatmentSubCategory"] == "C-Pap Machine")]
    assert estimate.n_similar == len(rows)
    width = wilson_width(int(rows["label"].sum()), len(rows))
    assert estimate.high - estimate.low >= width - 1e-9
    assert estimate.imr_category == "DME"


def test_unknown_policy_raises(model) -> None:  # type: ignore[no-untyped-def]
    """Only mapped policies have a base rate."""
    with pytest.raises(KeyError):
        model.estimate("made-up")


def test_abstention_on_2023_reported_per_group(model) -> None:  # type: ignore[no-untyped-def]
    """Width and abstain-on-width per policy group, computed without 2024+."""
    rows = model.width_check(max_width=0.20)
    assert set(rows) == set(MAPPINGS)
    for row in rows.values():
        assert row.abstain == (row.width > 0.20)


def test_test_report(frame: pd.DataFrame, model) -> None:  # type: ignore[no-untyped-def]
    """AUROC, Brier, reliability, coverage and set shares on 2024+, overall and per group."""
    _, _, test = split_years(frame)
    report = model.evaluate(test)
    assert 0.5 < report.auroc <= 1.0
    assert 0.0 < report.brier < 0.5
    assert sum(b.n for b in report.reliability) == len(test)
    assert report.coverage.n == len(test)
    assert set(report.per_group) == set(MAPPINGS)
    assert report.per_group["pap-osa"].coverage.n == int((test["TreatmentSubCategory"] == "C-Pap Machine").sum())


def test_fixture_rows_load_into_the_feature_matrix() -> None:
    """The real loader's output is accepted as-is."""
    assert list(feature_matrix(load_imr_features(FIXTURE)).columns) == list(FEATURE_COLUMNS)


def test_model_round_trips_and_missing_file_is_clear(tmp_path: Path, model) -> None:  # type: ignore[no-untyped-def]
    """Saved models load back; a missing or foreign file raises ``BaseModelError``."""
    path = save_base_model(model, tmp_path / "m.pkl")
    assert load_base_model(path).estimate("pap-osa") == model.estimate("pap-osa")
    with pytest.raises(BaseModelError, match="imr-fit"):
        load_base_model(tmp_path / "none.pkl")
    import pickle

    (tmp_path / "x.pkl").write_bytes(pickle.dumps({"not": "a model"}))
    with pytest.raises(BaseModelError):
        load_base_model(tmp_path / "x.pkl")
    (tmp_path / "bad.pkl").write_bytes(b"garbage")
    with pytest.raises(BaseModelError):
        load_base_model(tmp_path / "bad.pkl")
