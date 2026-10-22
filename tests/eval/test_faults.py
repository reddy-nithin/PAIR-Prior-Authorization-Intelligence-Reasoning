"""Seeded faults for the critic test (ADR-0013, critic plan Step 6)."""

import random
import re

import pytest

from pair.eval.audit import check_case
from pair.eval.cases import CaseBundle, CaseType
from pair.eval.faults import DEFAULT_MIX, FAULTS, PARAPHRASES, SeedingError, seed_suite
from pair.eval.synth.planners import UNITS
from tests.eval.test_audit import CHECKLISTS, make, with_state


def suite_cases() -> list[CaseBundle]:
    """Ten fake-written cases per policy, all four types."""
    types = [CaseType.WRONGLY_DENIED, CaseType.FIXABLE_GAP, CaseType.CORRECTLY_DENIED, CaseType.TRICKY]
    return [
        make(policy_id, types[i % 4], seed=100 + i).model_copy(update={"id": f"{policy_id}-{i:02d}"})
        for policy_id in sorted(CHECKLISTS)
        for i in range(10)
    ]


def test_every_unit_has_a_paraphrase_that_dodges_its_regex() -> None:
    """Each paraphrased leak supplies the value without tripping the generator's leak regex."""
    for policy_id, units in UNITS.items():
        for unit in units:
            sentence = PARAPHRASES[(policy_id, unit.name)]
            if unit.forbidden:
                assert not re.search(unit.forbidden, sentence, flags=re.IGNORECASE), (policy_id, unit.name)


@pytest.mark.parametrize("kind", sorted(FAULTS))
def test_fault_keeps_case_loadable(kind: str) -> None:
    """A faulted case still validates (spans slice the notes) and its key names rubric checks."""
    for case in suite_cases():
        result = FAULTS[kind](case, CHECKLISTS[case.policy_id], random.Random(1))
        if result is None:
            continue
        bad, fault = result
        CaseBundle.model_validate(bad.model_dump())
        assert fault.kind == kind and fault.expected and fault.severity in {"blocker", "major", "minor"}
        assert bad != case
        return
    pytest.fail(f"no case accepted {kind}")


def test_paraphrase_leak_evades_the_precheck() -> None:
    """The point of the fault: code can't see it, so only the critic can catch it."""
    case = with_state("pap-osa", "ahi_threshold", "absent")
    bad, fault = FAULTS["paraphrase_leak"](case, CHECKLISTS["pap-osa"], random.Random(0)) or (None, None)
    assert bad is not None and fault is not None
    assert not [f for f in check_case(bad, CHECKLISTS) if f.check_id == "K1"]


def test_label_flip_is_caught_by_the_precheck() -> None:
    """The mechanical fault is caught without the critic."""
    case = make()
    bad, _ = FAULTS["label_flip"](case, CHECKLISTS["pap-osa"], random.Random(0)) or (None, None)
    assert bad is not None
    assert "L1" in {f.check_id for f in check_case(bad, CHECKLISTS)}


def test_denial_swap_skips_type_a() -> None:
    """Type A letters are wrong by design, so the swap fault doesn't apply."""
    case = make(case_type=CaseType.WRONGLY_DENIED)
    assert FAULTS["denial_reason_swap"](case, CHECKLISTS["pap-osa"], random.Random(0)) is None


def test_seed_suite_mix_and_ids() -> None:
    """20 faults + 10 clean twins, shuffled, renamed so ids reveal nothing."""
    seeded = seed_suite(suite_cases(), CHECKLISTS, seed=7)
    assert len(seeded) == sum(DEFAULT_MIX.values()) + 10
    assert [s.seed_id for s in seeded] == [f"seed-{i:02d}" for i in range(1, 31)]
    assert all(s.case.id == s.seed_id for s in seeded)
    kinds = [s.fault.kind for s in seeded if s.fault]
    assert {k: kinds.count(k) for k in DEFAULT_MIX} == dict(DEFAULT_MIX)
    clean = [s for s in seeded if s.fault is None]
    faulted_bases = {s.base_case for s in seeded if s.fault}
    assert len(clean) == 10 and all(s.base_case in faulted_bases for s in clean)


def test_seed_suite_is_reproducible() -> None:
    """Same seed, same set."""
    first = [(s.base_case, s.fault) for s in seed_suite(suite_cases(), CHECKLISTS, seed=3)]
    assert first == [(s.base_case, s.fault) for s in seed_suite(suite_cases(), CHECKLISTS, seed=3)]


def test_seed_suite_reports_an_impossible_mix() -> None:
    """Asking for a fault no case can take is an error, not a short set."""
    cases = [make(case_type=CaseType.WRONGLY_DENIED)]
    with pytest.raises(SeedingError):
        seed_suite(cases, CHECKLISTS, seed=1, mix={"denial_reason_swap": 1})
