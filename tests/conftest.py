"""Shared pytest fixtures for the PAIR test suite."""

from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Return the absolute path to the repository root."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def mcd_export_dir(repo_root: Path) -> Path:
    """Return the downloaded MCD export folder, or skip if it isn't there."""
    path = repo_root / "data" / "raw" / "mcd"
    if not (path / "lcd_csv" / "lcd.csv").exists():
        pytest.skip("MCD export not downloaded (run `make data`)")
    return path


@pytest.fixture(scope="session")
def imr_csv(repo_root: Path) -> Path:
    """Return the downloaded IMR CSV, or skip if it isn't there."""
    path = repo_root / "data" / "raw" / "imr" / "imr_determinations.csv"
    if not path.exists():
        pytest.skip("IMR data not downloaded (run `make data`)")
    return path
