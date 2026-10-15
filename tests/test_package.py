"""Package layout matches spec §11: pair plus one subpackage per pipeline stage."""

import importlib

import pytest

SUBPACKAGES: list[str] = [
    "ingest",
    "policies",
    "extract",
    "rules",
    "draft",
    "verify",
    "score",
    "ui",
    "eval",
]


def test_package_exposes_version() -> None:
    """The top-level package imports and declares a string version."""
    pair = importlib.import_module("pair")
    assert isinstance(pair.__version__, str)
    assert pair.__version__


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_imports_with_docstring(name: str) -> None:
    """Each pipeline subpackage imports and says what it is for."""
    module = importlib.import_module(f"pair.{name}")
    assert module.__doc__ and module.__doc__.strip(), f"pair.{name} has no docstring"
