"""Tests for deterministic policy selection (spec §4 step 2)."""

from pathlib import Path

import pytest

from pair.contracts import Checklist
from pair.policies.loader import load_all
from pair.policies.select import (
    PolicySelectionError,
    load_service_codes,
    normalize_ref,
    select_policy,
)


@pytest.fixture(scope="module")
def policies(repo_root: Path) -> dict[str, Checklist]:
    """The shipped policy checklists."""
    return load_all(repo_root / "policies")


@pytest.fixture(scope="module")
def codes(repo_root: Path, policies: dict[str, Checklist]) -> dict[str, str]:
    """The shipped service-code table."""
    return load_service_codes(repo_root / "policies" / "_service-codes.yaml", policies)


@pytest.mark.parametrize(
    ("ref", "expected"),
    [("L33718", "L33718"), ("LCD L33718", "L33718"), (" lcd  l33718 ", "L33718"), ("NCD 240.4", "240.4"), ("240.2", "240.2"), ("LCD-L38841", "L38841")],
)
def test_normalize_ref(ref: str, expected: str) -> None:
    """Prefixes, spacing and case don't matter."""
    assert normalize_ref(ref) == expected


@pytest.mark.parametrize(
    ("ref", "expected"),
    [("L33718", "pap-osa"), ("NCD 240.4", "pap-osa"), ("L33797", "home-oxygen"), ("240.2", "home-oxygen"), ("LCD L38841", "facet-joint")],
)
def test_policy_ref_selects_checklist(policies: dict[str, Checklist], codes: dict[str, str], ref: str, expected: str) -> None:
    """A cited NCD/LCD id picks the checklist that quotes it."""
    selection = select_policy(ref, [], policies, codes)
    assert selection.policy_id == expected
    assert "policy_ref" in selection.reason


@pytest.mark.parametrize(("code", "expected"), [("E0601", "pap-osa"), ("e1390", "home-oxygen"), ("64635", "facet-joint")])
def test_service_code_selects_checklist(policies: dict[str, Checklist], codes: dict[str, str], code: str, expected: str) -> None:
    """With no policy reference, a known HCPCS/CPT code picks the checklist."""
    selection = select_policy(None, [code], policies, codes)
    assert selection.policy_id == expected
    assert "service code" in selection.reason


def test_policy_ref_beats_service_code(policies: dict[str, Checklist], codes: dict[str, str]) -> None:
    """The letter's own policy citation wins over the code table."""
    assert select_policy("L33797", ["E0601"], policies, codes).policy_id == "home-oxygen"


def test_unknown_ref_falls_back_to_codes(policies: dict[str, Checklist], codes: dict[str, str]) -> None:
    """A cited policy PAIR doesn't model (e.g. another MAC's LCD) falls back to codes."""
    selection = select_policy("L34892", ["64490"], policies, codes)
    assert selection.policy_id == "facet-joint"


@pytest.mark.parametrize(
    ("ref", "service_codes"),
    [(None, []), ("L99999", ["99213"]), (None, ["E0601", "E1390"]), (None, ["E0470"])],
)
def test_unsupported_never_guesses(policies: dict[str, Checklist], codes: dict[str, str], ref: str | None, service_codes: list[str]) -> None:
    """No match, or codes pointing at two policies: unsupported, with a reason."""
    selection = select_policy(ref, service_codes, policies, codes)
    assert selection.policy_id is None
    assert selection.reason.startswith("unsupported")


def test_code_table_rejects_unknown_policy(tmp_path: Path, policies: dict[str, Checklist]) -> None:
    """Every code must map to a loaded policy."""
    path = tmp_path / "_service-codes.yaml"
    path.write_text("not-a-policy: [E0601]\n", encoding="utf-8")
    with pytest.raises(PolicySelectionError, match="not-a-policy"):
        load_service_codes(path, policies)


def test_code_table_rejects_duplicate_code(tmp_path: Path, policies: dict[str, Checklist]) -> None:
    """A code may belong to only one policy."""
    path = tmp_path / "_service-codes.yaml"
    path.write_text("pap-osa: [E0601]\nhome-oxygen: [e0601]\n", encoding="utf-8")
    with pytest.raises(PolicySelectionError, match="E0601"):
        load_service_codes(path, policies)


@pytest.mark.parametrize("text", ["- E0601\n", "pap-osa: E0601\n", "pap-osa: [1]\n", "pap-osa: [E0601\n"])
def test_code_table_rejects_malformed_files(tmp_path: Path, policies: dict[str, Checklist], text: str) -> None:
    """The file must be a mapping of policy id to a list of code strings."""
    path = tmp_path / "_service-codes.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(PolicySelectionError):
        load_service_codes(path, policies)
