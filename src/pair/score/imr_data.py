"""Typed loader for the California DMHC Independent Medical Review (IMR) dataset.

The strength score (ADR-0007) learns base rates from these real appeal outcomes.
Only pre-decision columns may be features. ``Findings`` (written after the
decision) and the review-timing columns are leakage: the features loader never
reads them, and ``Findings`` is reachable only through ``load_imr_findings`` for
drafting exemplars (spec §5.4). Column facts are documented in
``docs/data/imr-schema.md``.
"""

import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


class ColumnRole(StrEnum):
    """What a column is allowed to be used for."""

    ID = "id"
    FEATURE = "feature"
    YEAR = "year"
    LABEL = "label"
    POST_DECISION = "post_decision"
    FINDINGS = "findings"


@dataclass(frozen=True)
class ColumnSpec:
    """Type, role and meaning of one IMR column."""

    dtype: str
    role: ColumnRole
    description: str


IMR_SCHEMA: dict[str, ColumnSpec] = {
    "ReferenceID": ColumnSpec("string", ColumnRole.ID, "Unique case id, e.g. MN26-46990."),
    "ReportYear": ColumnSpec("Int16", ColumnRole.YEAR, "Year the case was reported (2001 onward)."),
    "DiagnosisCategory": ColumnSpec("category", ColumnRole.FEATURE, "Main diagnosis category."),
    "DiagnosisSubCategory": ColumnSpec("category", ColumnRole.FEATURE, "Secondary diagnosis category."),
    "TreatmentCategory": ColumnSpec("category", ColumnRole.FEATURE, "Main treatment category, e.g. DME."),
    "TreatmentSubCategory": ColumnSpec("category", ColumnRole.FEATURE, "Secondary treatment category."),
    "Determination": ColumnSpec("Int8", ColumnRole.LABEL, "Overturned (1) or upheld (0) the plan's decision."),
    "Type": ColumnSpec(
        "category", ColumnRole.FEATURE, "Case type: Medical Necessity, Experimental/Investigational, Urgent Care."
    ),
    "AgeRange": ColumnSpec("category", ColumnRole.FEATURE, "Patient age band, e.g. '51 to 64'; blank if unknown."),
    "PatientGender": ColumnSpec("category", ColumnRole.FEATURE, "Female, Male or Other; blank if unknown."),
    "IMRType": ColumnSpec("category", ColumnRole.FEATURE, "Review track: Standard or Expedited (set at filing)."),
    "DaysToReview": ColumnSpec("Int16", ColumnRole.POST_DECISION, "Days the review took; known only after it ends."),
    "DaysToAdopt": ColumnSpec("Int16", ColumnRole.POST_DECISION, "Days to adopt the decision; known only after it."),
    "Findings": ColumnSpec("string", ColumnRole.FINDINGS, "Reviewer's written findings; written after the decision."),
}

FEATURE_COLUMNS: tuple[str, ...] = tuple(n for n, s in IMR_SCHEMA.items() if s.role is ColumnRole.FEATURE)
POST_DECISION_COLUMNS: tuple[str, ...] = tuple(
    n for n, s in IMR_SCHEMA.items() if s.role is ColumnRole.POST_DECISION
)
FINDINGS_COLUMN = "Findings"
YEAR_COLUMN = "ReportYear"
LABEL_COLUMN = "Determination"
LABEL_VALUES: dict[str, int] = {
    "Overturned Decision of Health Plan": 1,
    "Upheld Decision of Health Plan": 0,
}

if FINDINGS_COLUMN in FEATURE_COLUMNS or set(POST_DECISION_COLUMNS) & set(FEATURE_COLUMNS):  # pragma: no cover
    raise RuntimeError("IMR leakage guard: a post-decision column is listed as a feature")


class IMRSchemaError(ValueError):
    """The IMR file's columns or values don't match the documented schema."""


def load_imr_features(path: Path) -> pd.DataFrame:
    """Load pre-decision features, year and label; post-decision columns are never read.

    Args:
        path: The IMR determinations CSV.

    Returns:
        A frame with ``FEATURE_COLUMNS`` (categorical, blanks as missing),
        ``report_year`` (Int16) and ``label`` (Int8: overturned = 1).

    Raises:
        IMRSchemaError: If columns are missing or unexpected, a year isn't a
            number, or a determination value is unknown.
    """
    _check_columns(path)
    raw = _read_strings(path, [*FEATURE_COLUMNS, YEAR_COLUMN, LABEL_COLUMN])
    frame = pd.DataFrame({column: _to_category(raw[column]) for column in FEATURE_COLUMNS})
    frame["report_year"] = _to_year(raw[YEAR_COLUMN], path)
    frame["label"] = _to_label(raw[LABEL_COLUMN], path)
    return frame


def load_imr_findings(path: Path) -> pd.DataFrame:
    """Load findings text with treatment category and outcome, for drafting exemplars only.

    Never pass this frame to the strength model: findings are written after the
    decision (spec §5.4).
    """
    _check_columns(path)
    columns = ["ReferenceID", "TreatmentCategory", "TreatmentSubCategory", LABEL_COLUMN, FINDINGS_COLUMN]
    raw = _read_strings(path, columns)
    return pd.DataFrame(
        {
            "reference_id": raw["ReferenceID"],
            "treatment_category": _to_category(raw["TreatmentCategory"]),
            "treatment_subcategory": _to_category(raw["TreatmentSubCategory"]),
            "label": _to_label(raw[LABEL_COLUMN], path),
            "findings": raw[FINDINGS_COLUMN].astype("string"),
        }
    )


def _check_columns(path: Path) -> None:
    """Fail if the header differs from ``IMR_SCHEMA`` in either direction."""
    header = set(pd.read_csv(path, nrows=0).columns)
    missing = sorted(set(IMR_SCHEMA) - header)
    unexpected = sorted(header - set(IMR_SCHEMA))
    problems = []
    if missing:
        problems.append(f"missing columns: {missing}")
    if unexpected:
        problems.append(f"unexpected columns: {unexpected} (review for leakage before use)")
    if problems:
        message = f"{path}: " + "; ".join(problems)
        logger.error(message)
        raise IMRSchemaError(message)


def _read_strings(path: Path, columns: list[str]) -> pd.DataFrame:
    """Read only ``columns``, all as strings, keeping blanks as empty strings."""
    return pd.read_csv(path, usecols=columns, dtype=str, keep_default_na=False)


def _to_category(values: pd.Series) -> pd.Series:
    """Convert strings to a categorical, treating blanks as missing."""
    stripped = values.str.strip()
    return stripped.where(stripped != "").astype("category")


def _to_year(values: pd.Series, path: Path) -> pd.Series:
    """Convert the year column to Int16, failing on anything non-numeric."""
    numeric = pd.to_numeric(values, errors="coerce")
    bad = sorted(set(values[numeric.isna()]))
    if bad:
        message = f"{path}: non-numeric {YEAR_COLUMN} values: {bad[:5]}"
        logger.error(message)
        raise IMRSchemaError(message)
    return numeric.astype("Int16")


def _to_label(values: pd.Series, path: Path) -> pd.Series:
    """Map determinations to 1/0, failing on any value not in ``LABEL_VALUES``."""
    unknown = sorted(set(values) - set(LABEL_VALUES))
    if unknown:
        message = f"{path}: unknown {LABEL_COLUMN} values: {unknown}"
        logger.error(message)
        raise IMRSchemaError(message)
    return values.map(LABEL_VALUES).astype("Int8")
