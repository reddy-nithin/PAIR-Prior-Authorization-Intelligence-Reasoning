"""The three shipped policy checklists load and quote the MCD verbatim."""

from pathlib import Path

import pytest

from pair.contracts import Checklist, PolicySource
from pair.policies.loader import load_all
from pair.policies.mcd import MCDDocument, MCDExport

EXPECTED_POLICIES: dict[str, set[str]] = {
    "pap-osa": {"240.4", "L33718"},
    "home-oxygen": {"240.2", "L33797"},
    "facet-joint": {"L38841"},
}


@pytest.fixture(scope="module")
def policies(repo_root: Path) -> dict[str, Checklist]:
    """Load every shipped policy once."""
    return load_all(repo_root / "policies")


def test_all_three_policies_load(policies: dict[str, Checklist]) -> None:
    """Exactly the three Phase 1 policies load, citing the expected documents."""
    assert set(policies) == set(EXPECTED_POLICIES)
    for policy_id, source_ids in EXPECTED_POLICIES.items():
        assert {s.id for s in policies[policy_id].sources} == source_ids


def test_every_policy_has_a_critical_criterion(policies: dict[str, Checklist]) -> None:
    """Abstention (ADR-0007) needs at least one critical criterion per policy."""
    for checklist in policies.values():
        assert any(c.critical for c in checklist.criteria), checklist.id


@pytest.fixture(scope="module")
def export(mcd_export_dir: Path) -> MCDExport:
    """One cached reader over the downloaded export."""
    return MCDExport(mcd_export_dir)


def find_source(export: MCDExport, source: PolicySource) -> MCDDocument:
    """Look up a policy source in the MCD export."""
    return export.find_ncd(source.id) if source.type == "NCD" else export.find_lcd(source.id)


@pytest.mark.mcd
def test_sources_match_current_mcd_versions(policies: dict[str, Checklist], export: MCDExport) -> None:
    """Source versions, titles and URLs match the downloaded export (catches policy drift)."""
    for checklist in policies.values():
        for source in checklist.sources:
            document = find_source(export, source)
            assert (source.version, source.url) == (document.version, document.url), source.id
            assert source.title == document.title, source.id


@pytest.mark.mcd
def test_every_clause_is_verbatim_in_its_source(policies: dict[str, Checklist], export: MCDExport) -> None:
    """Each clause appears word for word (whitespace-insensitive) in the cited document."""
    for checklist in policies.values():
        sources = {s.id: s for s in checklist.sources}
        for criterion in checklist.criteria:
            document = find_source(export, sources[criterion.source_id])
            assert document.contains(criterion.clause), f"{checklist.id}.{criterion.id}"
