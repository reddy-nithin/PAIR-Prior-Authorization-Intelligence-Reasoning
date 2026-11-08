"""Tests for IMR argument exemplars: drafting few-shot only, never a score feature (spec §5.4)."""

import ast
from pathlib import Path

import pytest

from pair.draft.exemplars import load_exemplars
from pair.score.imr_mapping import PolicyImrMapping

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "imr" / "fake_imr.csv"
FACET = PolicyImrMapping(rationale="test", match_any=[{"TreatmentSubCategory": ["Facet Injection"]}])
CPAP = PolicyImrMapping(rationale="test", match_any=[{"TreatmentSubCategory": ["CPAP"]}])


def test_overturned_matches_newest_first() -> None:
    """Only overturned rows of the policy group, newest year first."""
    assert load_exemplars(FIXTURE, FACET, n=3) == ("Fake findings text five.", "Fake findings text three.")


def test_upheld_rows_are_never_exemplars() -> None:
    """CPAP has one overturned and one upheld row; only the overturned one is used."""
    assert load_exemplars(FIXTURE, CPAP, n=3) == ("Fake findings text one.",)


def test_n_limits_the_count() -> None:
    """At most ``n`` exemplars."""
    assert load_exemplars(FIXTURE, FACET, n=1) == ("Fake findings text five.",)


def test_long_findings_are_truncated(tmp_path: Path) -> None:
    """Exemplars are cut to ``max_chars`` so prompts stay short."""
    text = FIXTURE.read_text().replace("Fake findings text five.", "x" * 900)
    path = tmp_path / "imr.csv"
    path.write_text(text)

    (first, _) = load_exemplars(path, FACET, n=2, max_chars=100)
    assert len(first) <= 100 and first.endswith("...")


def test_no_path_means_no_exemplars() -> None:
    """Offline demo runs draft without exemplars."""
    assert load_exemplars(None, FACET) == ()


def test_missing_file_fails_loudly(tmp_path: Path) -> None:
    """A given path that doesn't exist is an error, not a silent empty list."""
    with pytest.raises(FileNotFoundError):
        load_exemplars(tmp_path / "nope.csv", FACET)


def test_score_package_never_imports_drafting(repo_root: Path) -> None:
    """Leakage guard: findings text reaches drafting only; no score module imports ``pair.draft``."""
    offenders = []
    for path in (repo_root / "src" / "pair" / "score").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [alias.name for alias in node.names] if isinstance(node, ast.Import)
                else [node.module or ""] if isinstance(node, ast.ImportFrom)
                else []
            )
            offenders += [f"{path.name}: {name}" for name in names if name.startswith("pair.draft")]
    assert offenders == []
