"""Read Synthea CSV output into ``PatientProfile``s (age, sex, active disorders only).

Synthea's synthetic names, addresses and ids are never copied into cases.
"""

import csv
import datetime as dt
import logging
import re
from pathlib import Path

from pair.eval.cases import PatientProfile

logger = logging.getLogger(__name__)

MAX_CONDITIONS: int = 5
_SUFFIX = " (disorder)"
_STAGED = re.compile(r"^(?P<base>.+) stage (?P<stage>\d+)$")


class ProfileError(ValueError):
    """The Synthea output is missing or malformed."""


def load_synthea_profiles(csv_dir: Path, reference: dt.date, min_age: int = 65) -> list[PatientProfile]:
    """Load living patients aged ``min_age`` or more, sorted by Synthea id.

    Raises:
        ProfileError: If ``patients.csv`` or ``conditions.csv`` is missing or lacks columns.
    """
    patients = _rows(csv_dir / "patients.csv", {"Id", "BIRTHDATE", "DEATHDATE", "GENDER"})
    conditions = _rows(csv_dir / "conditions.csv", {"STOP", "PATIENT", "DESCRIPTION"})
    active: dict[str, list[str]] = {}
    for row in conditions:
        description = row["DESCRIPTION"]
        if row["STOP"] or not description.endswith(_SUFFIX):
            continue
        names = active.setdefault(row["PATIENT"], [])
        name = description.removesuffix(_SUFFIX)
        if name not in names:
            names.append(name)
    profiles = []
    for row in sorted(patients, key=lambda r: r["Id"]):
        if row["DEATHDATE"]:
            continue
        age = _age(dt.date.fromisoformat(row["BIRTHDATE"]), reference)
        if age < min_age or row["GENDER"] not in {"F", "M"}:
            continue
        profiles.append(
            PatientProfile(
                synthea_id=row["Id"],
                age=age,
                sex=row["GENDER"],  # type: ignore[arg-type]  # checked above
                conditions=sorted(_highest_stages(active.get(row["Id"], [])))[:MAX_CONDITIONS],
            )
        )
    logger.info("loaded %d Synthea profiles from %s", len(profiles), csv_dir)
    return profiles


def _highest_stages(names: list[str]) -> list[str]:
    """Keep only the highest stage of a staged disorder (Synthea leaves CKD stage 1 to 3 active at once)."""
    best: dict[str, tuple[int, str]] = {}
    plain: list[str] = []
    for name in names:
        match = _STAGED.match(name)
        if match is None:
            plain.append(name)
            continue
        stage = int(match["stage"])
        if match["base"] not in best or stage > best[match["base"]][0]:
            best[match["base"]] = (stage, name)
    return plain + [name for _, name in best.values()]


def _rows(path: Path, needed: set[str]) -> list[dict[str, str]]:
    """Read a CSV and check its columns."""
    if not path.is_file():
        raise ProfileError(f"missing Synthea file {path} (run Synthea, see scripts/generate_cases.py)")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = needed - set(reader.fieldnames or [])
        if missing:
            raise ProfileError(f"{path.name} lacks columns {sorted(missing)}")
        return list(reader)


def _age(birth: dt.date, on: dt.date) -> int:
    """Whole years from ``birth`` to ``on``."""
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))
