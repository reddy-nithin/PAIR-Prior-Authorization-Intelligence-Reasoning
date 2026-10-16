"""Tests for the strict policy YAML loader."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from pair.contracts import Checklist
from pair.policies.loader import PolicyValidationError, load_all, load_policy

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "policies"
VALID = FIXTURES / "fake-device.yaml"


def valid_data() -> dict[str, Any]:
    """Return the valid fixture as a fresh dict."""
    data: dict[str, Any] = yaml.safe_load(VALID.read_text(encoding="utf-8"))
    return data


def write_policy(directory: Path, data: dict[str, Any], name: str = "fake-device") -> Path:
    """Write ``data`` as ``<name>.yaml`` in ``directory`` and return its path."""
    path = directory / f"{name}.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_valid_policy_loads() -> None:
    """The fixture loads into a typed checklist."""
    checklist = load_policy(VALID)
    assert isinstance(checklist, Checklist)
    assert checklist.criterion_ids == ("ahi_threshold", "f2f_visit")


def first_criterion(change: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any]], None]:
    """Build a mutation that applies ``change`` to the first criterion."""
    return lambda data: change(data["criteria"][0])


BREAKAGES: list[tuple[str, Callable[[dict[str, Any]], None], str]] = [
    ("unknown top-level field", lambda d: d.update(owner="me"), "owner"),
    ("unknown criterion field", first_criterion(lambda c: c.update(weight=2)), "weight"),
    ("rule with subscript", first_criterion(lambda c: c.update(rule="ahi[0] > 1")), "Subscript"),
    ("undeclared variable", first_criterion(lambda c: c.update(rule="rdi >= 15")), "undeclared name 'rdi'"),
    ("unused variable", first_criterion(lambda c: c["variables"].update(spo2="number")), "declares unused variables: \\['spo2'\\]"),
    ("duplicate id", lambda d: d["criteria"][1].update(id="ahi_threshold"), "duplicate criterion id"),
    ("unknown id in logic", lambda d: d.update(logic="ahi_threshold and adherence"), "undeclared name 'adherence'"),
    ("dash in criterion id", first_criterion(lambda c: c.update(id="ahi-threshold")), "id"),
    ("missing rule", first_criterion(lambda c: c.pop("rule")), "rule"),
    ("unknown source", first_criterion(lambda c: c.update(source_id="L1")), "unknown source"),
]


@pytest.mark.parametrize(("label", "break_it", "message"), BREAKAGES, ids=[b[0] for b in BREAKAGES])
def test_invalid_policies_fail_loudly(tmp_path: Path, label: str, break_it: Callable[[dict[str, Any]], None], message: str) -> None:
    """Every kind of bad policy raises PolicyValidationError naming the file and problem."""
    data = valid_data()
    break_it(data)
    path = write_policy(tmp_path, data)
    with pytest.raises(PolicyValidationError, match=message) as info:
        load_policy(path)
    assert str(path) in str(info.value), label


def test_file_name_must_match_id(tmp_path: Path) -> None:
    """``pap-osa.yaml`` must hold the checklist with id ``pap-osa``."""
    path = write_policy(tmp_path, valid_data(), name="other-name")
    with pytest.raises(PolicyValidationError, match="does not match file name"):
        load_policy(path)


@pytest.mark.parametrize("content", ["", "- just\n- a list\n", "key: [unclosed\n"])
def test_non_mapping_or_broken_yaml_fails(tmp_path: Path, content: str) -> None:
    """Empty files, lists and broken YAML are rejected."""
    path = tmp_path / "fake-device.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(PolicyValidationError):
        load_policy(path)


def test_load_all_skips_underscore_files(tmp_path: Path) -> None:
    """``load_all`` loads every policy and ignores helper files starting with ``_``."""
    write_policy(tmp_path, valid_data())
    (tmp_path / "_imr-mapping.yaml").write_text("not: a policy\n", encoding="utf-8")
    policies = load_all(tmp_path)
    assert list(policies) == ["fake-device"]


def test_load_all_empty_dir_fails(tmp_path: Path) -> None:
    """No policies found is an error, not an empty dict."""
    with pytest.raises(PolicyValidationError, match="no policy files"):
        load_all(tmp_path)
