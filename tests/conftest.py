"""Shared pytest fixtures for the PAIR test suite."""

from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Return the absolute path to the repository root."""
    return REPO_ROOT
