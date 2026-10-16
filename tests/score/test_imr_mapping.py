"""Tests for the policy → IMR category mapping."""

from pathlib import Path

import pytest
import yaml

from pair.score.imr_data import load_imr_features
from pair.score.imr_mapping import ImrMappingError, load_imr_mapping, select_rows

FIXTURE_CSV = Path(__file__).resolve().parent.parent / "fixtures" / "imr" / "fake_imr.csv"
MIN_ROWS = 30

VALID = {
    "pap-osa": {
        "rationale": "PAP devices for sleep apnea.",
        "match_any": [
            {"TreatmentSubCategory": ["CPAP"]},
            {"TreatmentCategory": ["DME"], "DiagnosisSubCategory": ["Sleep Apnea"]},
        ],
    },
    "facet-joint": {
        "rationale": "Facet injections for back pain.",
        "match_any": [{"TreatmentSubCategory": ["Facet Injection"], "DiagnosisSubCategory": ["Back Pain"]}],
    },
}


def write_mapping(tmp_path: Path, data: object) -> Path:
    """Write ``data`` as a mapping YAML file and return its path."""
    path = tmp_path / "_imr-mapping.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_select_rows_ors_filters_and_ands_columns(tmp_path: Path) -> None:
    """Filters in match_any are OR-ed; columns inside one filter are AND-ed."""
    mapping = load_imr_mapping(write_mapping(tmp_path, VALID))
    frame = load_imr_features(FIXTURE_CSV)
    assert select_rows(frame, mapping["pap-osa"]).tolist() == [True, True, False, False, False, False]
    assert select_rows(frame, mapping["facet-joint"]).sum() == 2


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"pap-osa": {"rationale": "x", "match_any": [{"Findings": ["a"]}]}}, "Findings"),
        ({"pap-osa": {"rationale": "x", "match_any": [{"DaysToReview": ["1"]}]}}, "DaysToReview"),
        ({"pap-osa": {"rationale": "x", "match_any": []}}, "match_any"),
        ({"pap-osa": {"rationale": "x", "match_any": [{}]}}, "at least one column"),
        ({"pap-osa": {"rationale": "x", "match_any": [{"TreatmentCategory": []}]}}, "TreatmentCategory"),
        ({"pap-osa": {"rationale": "", "match_any": [{"TreatmentCategory": ["DME"]}]}}, "rationale"),
        ({"pap-osa": {"rationale": "x", "match_any": [{"TreatmentCategory": ["DME"]}], "extra": 1}}, "extra"),
        (["not", "a", "mapping"], "mapping"),
    ],
)
def test_invalid_mappings_fail(tmp_path: Path, data: object, message: str) -> None:
    """Only feature columns may be matched, and every part must be non-empty."""
    with pytest.raises(ImrMappingError, match=message):
        load_imr_mapping(write_mapping(tmp_path, data))


@pytest.mark.imr
def test_real_mapping_covers_policies_with_enough_rows(repo_root: Path, imr_csv: Path) -> None:
    """Every shipped policy maps to real IMR categories with at least MIN_ROWS cases."""
    from pair.policies.loader import load_all

    mapping = load_imr_mapping(repo_root / "policies" / "_imr-mapping.yaml")
    assert set(mapping) == set(load_all(repo_root / "policies"))
    frame = load_imr_features(imr_csv)
    for policy_id, policy_mapping in mapping.items():
        for rule in policy_mapping.match_any:
            for column, values in rule.items():
                unknown = set(values) - set(frame[column].cat.categories)
                assert not unknown, f"{policy_id}: {column} values not in data: {unknown}"
        assert select_rows(frame, policy_mapping).sum() >= MIN_ROWS, policy_id
