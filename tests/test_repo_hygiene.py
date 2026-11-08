"""Repo hygiene: private, agent and data files must never be committable."""

import json
import subprocess
from pathlib import Path

import pytest

MUST_BE_IGNORED: list[str] = [
    "CLAUDE.md",
    "web/AGENTS.md",
    ".claude/TRACKER.md",
    "data/raw/x.csv",
    "data/interim/x.parquet",
    "data/cases/c1.json",
    ".env",
    ".env.local",
    "data/IMR_Determinations.csv",
    "IMR_Determinations_Trend.csv",
    "notebooks/.ipynb_checkpoints/eda-checkpoint.ipynb",
    "data/demo-cache/manifest.json",
    "web/public/demo/index.json",
    "web/public/demo/views/pap-osa-01.json",
]

MUST_BE_TRACKABLE: list[str] = [
    "pyproject.toml",
    "src/pair/__init__.py",
    "data/.gitkeep",
    ".env.example",
    "policies/pap-osa.yaml",
    "tests/fixtures/imr/fake_imr.csv",
    "web/src/copy/en.json",
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


def notebook_paths(repo_root: Path) -> list[Path]:
    """Return every notebook under ``notebooks/``, skipping checkpoints."""
    return sorted(p for p in (repo_root / "notebooks").rglob("*.ipynb") if ".ipynb_checkpoints" not in p.parts)


def test_notebooks_have_no_outputs(repo_root: Path) -> None:
    """Notebook outputs could carry data rows; strip them with `make strip-notebooks`."""
    dirty = []
    for path in notebook_paths(repo_root):
        cells = json.loads(path.read_text(encoding="utf-8"))["cells"]
        code_cells = [c for c in cells if c["cell_type"] == "code"]
        if any(c.get("outputs") or c.get("execution_count") is not None for c in code_cells):
            dirty.append(path.name)
    assert not dirty, f"notebooks with outputs: {dirty} (run `make strip-notebooks`)"
