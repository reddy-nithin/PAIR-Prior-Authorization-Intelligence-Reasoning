"""Synthea CSV → PatientProfile (T9)."""

import datetime as dt
from pathlib import Path

import pytest

from pair.eval.cases import PatientProfile
from pair.eval.synth.profiles import (
    TEST_POOL_SIZE,
    ProfileError,
    load_synthea_profiles,
    profile_pool,
)

PATIENTS = """Id,BIRTHDATE,DEATHDATE,FIRST,LAST,GENDER
p2,1950-12-01,,Ann,Doe,F
p1,1955-01-01,,Bob,Roe,M
p3,1940-01-01,2020-01-01,Cy,Poe,M
p4,1990-01-01,,Di,Moe,F
"""
CONDITIONS = """START,STOP,PATIENT,ENCOUNTER,SYSTEM,CODE,DESCRIPTION
2000-01-01,,p1,e,SNOMED-CT,1,Hypertension (disorder)
2000-01-01,,p1,e,SNOMED-CT,2,Hypertension (disorder)
2000-01-01,2001-01-01,p1,e,SNOMED-CT,3,Acute bronchitis (disorder)
2000-01-01,,p1,e,SNOMED-CT,4,Full-time employment (finding)
2000-01-01,,p2,e,SNOMED-CT,5,Obesity (disorder)
"""


def write(
    tmp_path: Path, patients: str = PATIENTS, conditions: str = CONDITIONS
) -> Path:
    """Write fake Synthea CSVs."""
    (tmp_path / "patients.csv").write_text(patients)
    (tmp_path / "conditions.csv").write_text(conditions)
    return tmp_path


def test_living_older_patients_with_active_disorders(tmp_path: Path) -> None:
    """Only living patients aged 65+ are kept, sorted by id, with active disorders only."""
    profiles = load_synthea_profiles(write(tmp_path), dt.date(2026, 10, 19))
    assert [p.synthea_id for p in profiles] == ["p1", "p2"]
    assert profiles[0].age == 71
    assert profiles[0].sex == "M"
    assert profiles[0].conditions == ["Hypertension"]
    assert profiles[1].age == 75
    assert profiles[1].conditions == ["Obesity"]


def test_names_are_not_copied(tmp_path: Path) -> None:
    """Synthetic names never reach the profile."""
    profiles = load_synthea_profiles(write(tmp_path), dt.date(2026, 10, 19))
    assert "Bob" not in str(profiles[0].model_dump())


def test_missing_file_or_columns_raise(tmp_path: Path) -> None:
    """Missing output or columns fail loudly."""
    with pytest.raises(ProfileError, match="missing Synthea file"):
        load_synthea_profiles(tmp_path, dt.date(2026, 1, 1))
    write(tmp_path, patients="Id,GENDER\np1,M\n")
    with pytest.raises(ProfileError, match="BIRTHDATE"):
        load_synthea_profiles(tmp_path, dt.date(2026, 1, 1))


def test_other_gender_codes_are_skipped(tmp_path: Path) -> None:
    """Profiles need F or M for the note prompt."""
    write(tmp_path, patients="Id,BIRTHDATE,DEATHDATE,GENDER\np9,1950-01-01,,X\n")
    assert load_synthea_profiles(tmp_path, dt.date(2026, 1, 1)) == []


def test_ckd_stages_collapse_to_the_highest(tmp_path: Path) -> None:
    """Synthea leaves several CKD stages active at once; a profile keeps only the highest."""
    conditions = CONDITIONS + (
        "2000-01-01,,p2,e,SNOMED-CT,6,Chronic kidney disease stage 1 (disorder)\n"
        "2001-01-01,,p2,e,SNOMED-CT,7,Chronic kidney disease stage 3 (disorder)\n"
        "2002-01-01,,p2,e,SNOMED-CT,8,Chronic kidney disease stage 2 (disorder)\n"
    )
    profiles = load_synthea_profiles(
        write(tmp_path, conditions=conditions), dt.date(2026, 10, 19)
    )
    assert profiles[1].conditions == ["Chronic kidney disease stage 3", "Obesity"]


def _profiles(n: int) -> list[PatientProfile]:
    """``n`` fake profiles with ids p00, p01, ... (already sorted, as the loader returns them)."""
    return [
        PatientProfile(synthea_id=f"p{i:02d}", age=70, sex="F", conditions=[])
        for i in range(n)
    ]


def test_test_pool_is_the_first_profiles_so_the_test_set_is_unchanged() -> None:
    """The test pool keeps the first ``TEST_POOL_SIZE`` profiles, the ones `cases-v3` was built from."""
    profiles = _profiles(TEST_POOL_SIZE + 10)
    assert profile_pool(profiles, "test") == profiles[:TEST_POOL_SIZE]


def test_dev_pool_shares_no_patient_with_the_test_pool() -> None:
    """ADR-0017: the dev set is held out by patient, not only by seed."""
    profiles = _profiles(TEST_POOL_SIZE + 10)
    test_ids = {p.synthea_id for p in profile_pool(profiles, "test")}
    dev_ids = {p.synthea_id for p in profile_pool(profiles, "dev")}
    assert dev_ids == {p.synthea_id for p in profiles[TEST_POOL_SIZE:]}
    assert not test_ids & dev_ids


def test_profile_pool_errors() -> None:
    """An empty dev pool or an unknown split is an error, never a silent reuse of test patients."""
    with pytest.raises(ProfileError, match="dev pool is empty"):
        profile_pool(_profiles(TEST_POOL_SIZE), "dev")
    with pytest.raises(ProfileError, match="unknown split"):
        profile_pool(_profiles(TEST_POOL_SIZE + 1), "train")
