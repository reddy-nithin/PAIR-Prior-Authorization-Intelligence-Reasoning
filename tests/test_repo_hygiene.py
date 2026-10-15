"""Repo hygiene: private, agent and data files must never be committable."""

import subprocess
from pathlib import Path

import pytest

MUST_BE_IGNORED: list[str] = [
    "CLAUDE.md",
    ".claude/TRACKER.md",
    "data/raw/x.csv",
    "data/interim/x.parquet",
    "data/cases/c1.json",
    ".env",
    ".env.local",
    "data/IMR_Determinations.csv",
    "IMR_Determinations_Trend.csv",
    "notebooks/.ipynb_checkpoints/eda-checkpoint.ipynb",
]

MUST_BE_TRACKABLE: list[str] = [
    "pyproject.toml",
    "src/pair/__init__.py",
    "data/.gitkeep",
    ".env.example",
    "policies/pap-osa.yaml",
]


def is_git_ignored(repo_root: Path, relative_path: str) -> bool:
    """Return True if git would ignore ``relative_path`` in ``repo_root``.

    Uses ``git check-ignore --no-index`` so the answer depends only on
    ignore rules, not on whether the file is already tracked.
    """
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", relative_path],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"git check-ignore failed: {result.stderr.strip()}")
    return result.returncode == 0


@pytest.mark.parametrize("relative_path", MUST_BE_IGNORED)
def test_private_and_data_paths_are_ignored(repo_root: Path, relative_path: str) -> None:
    """Agent files, secrets, IMR files and data folders are gitignored."""
    assert is_git_ignored(repo_root, relative_path), f"{relative_path} is not ignored"


@pytest.mark.parametrize("relative_path", MUST_BE_TRACKABLE)
def test_project_paths_are_trackable(repo_root: Path, relative_path: str) -> None:
    """Source, config and placeholder files stay committable."""
    assert not is_git_ignored(repo_root, relative_path), f"{relative_path} is ignored"
