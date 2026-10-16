"""Tests for the typed IMR loader and its leakage guard (fake fixture rows only)."""

import json
from pathlib import Path

import pandas as pd
import pytest

from pair.score.imr_data import (
    FEATURE_COLUMNS,
    FINDINGS_COLUMN,
    IMR_SCHEMA,
    POST_DECISION_COLUMNS,
    IMRSchemaError,
    load_imr_features,
    load_imr_findings,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "imr" / "fake_imr.csv"


@pytest.fixture
def fake_rows() -> pd.DataFrame:
    """The fake fixture as raw strings, for building broken variants."""
    return pd.read_csv(FIXTURE, dtype=str, keep_default_na=False)


def test_features_have_exact_columns_and_dtypes() -> None:
    """Features come back typed: categoricals, a nullable year and an int label."""
    frame = load_imr_features(FIXTURE)
    assert list(frame.columns) == [*FEATURE_COLUMNS, "report_year", "label"]
    for column in FEATURE_COLUMNS:
        assert isinstance(frame[column].dtype, pd.CategoricalDtype), column
    assert str(frame["report_year"].dtype) == "Int16"
    assert str(frame["label"].dtype) == "Int8"
    assert len(frame) == 6


def test_label_maps_overturned_to_one() -> None:
    """Overturned = 1, upheld = 0 (spec §5.4)."""
    assert load_imr_features(FIXTURE)["label"].tolist() == [1, 0, 1, 0, 1, 0]


def test_blank_categories_become_missing() -> None:
    """Empty strings are missing values, not a category called ''."""
    frame = load_imr_features(FIXTURE)
    assert frame["AgeRange"].isna().sum() == 1
    assert "" not in frame["PatientGender"].cat.categories


def test_findings_and_post_decision_columns_never_reach_features() -> None:
    """The leakage guard: post-decision columns are not features, by constant and by output."""
    leaky = {FINDINGS_COLUMN, *POST_DECISION_COLUMNS}
    assert not leaky & set(FEATURE_COLUMNS)
    assert not leaky & set(load_imr_features(FIXTURE).columns)


def test_schema_documents_every_column() -> None:
    """Every real column has a dtype, role and description."""
    assert set(IMR_SCHEMA) >= {FINDINGS_COLUMN, *FEATURE_COLUMNS, *POST_DECISION_COLUMNS}
    for name, spec in IMR_SCHEMA.items():
        assert spec.description, name


def test_missing_column_raises(tmp_path: Path, fake_rows: pd.DataFrame) -> None:
    """A dropped or renamed column fails loudly, naming it."""
    path = tmp_path / "imr.csv"
    fake_rows.drop(columns=["TreatmentCategory"]).to_csv(path, index=False)
    with pytest.raises(IMRSchemaError, match="missing columns: \\['TreatmentCategory'\\]"):
        load_imr_features(path)


def test_unexpected_column_raises(tmp_path: Path, fake_rows: pd.DataFrame) -> None:
    """A new column in a dataset update must be reviewed for leakage before use."""
    path = tmp_path / "imr.csv"
    fake_rows.assign(AppealOutcomeNotes="x").to_csv(path, index=False)
    with pytest.raises(IMRSchemaError, match="unexpected columns: \\['AppealOutcomeNotes'\\]"):
        load_imr_features(path)


def test_unknown_determination_raises(tmp_path: Path, fake_rows: pd.DataFrame) -> None:
    """A label value we don't know is an error, not a silent NaN."""
    path = tmp_path / "imr.csv"
    fake_rows.assign(Determination="Withdrawn").to_csv(path, index=False)
    with pytest.raises(IMRSchemaError, match="Withdrawn"):
        load_imr_features(path)


def test_bad_year_raises(tmp_path: Path, fake_rows: pd.DataFrame) -> None:
    """A non-numeric year fails loudly."""
    path = tmp_path / "imr.csv"
    fake_rows.assign(ReportYear="soon").to_csv(path, index=False)
    with pytest.raises(IMRSchemaError, match="ReportYear"):
        load_imr_features(path)


def test_findings_loader_is_separate() -> None:
    """Findings are reachable only through their own loader, for drafting exemplars."""
    findings = load_imr_findings(FIXTURE)
    assert list(findings.columns) == ["reference_id", "treatment_category", "treatment_subcategory", "label", "findings"]
    assert findings["findings"].iloc[0] == "Fake findings text one."


RECORDED_DATASET = {
    "sha256": "f68951823f6ffc09566cc190d97b2808e0269a069843efe809a3f5f90d4c893b",
    "rows": 42749,
    "year_min": 2001,
    "year_max": 2026,
}


@pytest.mark.imr
def test_real_dataset_matches_documented_schema(imr_csv: Path) -> None:
    """The downloaded file loads and matches the counts in docs/data/imr-schema.md."""
    manifest = json.loads((imr_csv.parent / "manifest.json").read_text())
    sha = next(f["sha256"] for f in manifest["files"] if f["path"] == imr_csv.name)
    if sha != RECORDED_DATASET["sha256"]:
        pytest.skip("IMR dataset was updated; refresh docs/data/imr-schema.md and RECORDED_DATASET")
    frame = load_imr_features(imr_csv)
    assert len(frame) == RECORDED_DATASET["rows"]
    assert frame["report_year"].min() == RECORDED_DATASET["year_min"]
    assert frame["report_year"].max() == RECORDED_DATASET["year_max"]
    assert frame["label"].notna().all()
