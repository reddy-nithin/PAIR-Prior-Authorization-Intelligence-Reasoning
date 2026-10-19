"""Makefile exposes the five project targets and stubs fail loudly."""

import subprocess
from pathlib import Path

import pytest

ALL_TARGETS: list[str] = ["setup", "data", "data-mcd", "data-imr", "data-synthea", "cases", "eval-core", "strip-notebooks", "demo", "eval", "test"]
NOT_BUILT_TARGETS: list[str] = ["demo", "eval"]


def run_make(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run ``make`` with ``args`` in ``repo_root`` and capture its output."""
    return subprocess.run(
        ["make", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("target", ALL_TARGETS)
def test_target_is_defined(repo_root: Path, target: str) -> None:
    """``make -n <target>`` (dry run) succeeds for every documented target."""
    result = run_make(repo_root, "-n", target)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("target", NOT_BUILT_TARGETS)
def test_unbuilt_target_fails_loudly(repo_root: Path, target: str) -> None:
    """Targets for later phases exit non-zero and name the phase."""
    result = run_make(repo_root, target)
    assert result.returncode != 0
    assert "not built yet" in (result.stdout + result.stderr)
    assert "Phase" in (result.stdout + result.stderr)
