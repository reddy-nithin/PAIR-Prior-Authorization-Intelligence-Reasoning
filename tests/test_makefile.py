"""Makefile exposes the five project targets and stubs fail loudly."""

import subprocess
from pathlib import Path

import pytest

ALL_TARGETS: list[str] = ["setup", "data", "data-mcd", "data-imr", "data-synthea", "cases", "eval-core", "strip-notebooks", "demo", "eval", "test", "demo-cache", "demo-verify", "demo-publish", "api", "demo-fixture"]
NOT_BUILT_TARGETS: list[str] = ["eval"]


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


def test_demo_builds_and_starts_the_web_app(repo_root: Path) -> None:
    """``make demo`` builds the Next.js app and serves it on localhost (cached mode needs no API)."""
    plan = run_make(repo_root, "-n", "demo").stdout
    assert "npm --prefix web run build" in plan
    assert "next start -H 127.0.0.1" in plan


def test_demo_refuses_without_a_published_cache(repo_root: Path, tmp_path: Path) -> None:
    """With no web/public/demo/index.json, ``make demo`` stops and says how to publish one."""
    result = run_make(repo_root, "demo", f"DEMO_INDEX={tmp_path / 'missing.json'}")
    assert result.returncode != 0
    assert "make demo-publish" in result.stderr and "make demo-fixture" in result.stderr
