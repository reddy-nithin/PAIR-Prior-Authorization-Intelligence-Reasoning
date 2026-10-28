"""Synthetic denial letters round-trip to their gold Denial (T9)."""

import datetime as dt
import random

import pytest

from pair.contracts import PlanType, ReasonCategory
from pair.eval.synth.denials import REASONS, SERVICES, render_denial
from pair.policies.loader import load_all
from pair.policies.select import load_service_codes, normalize_ref, select_policy
from tests.conftest import REPO_ROOT

CHECKLISTS = load_all(REPO_ROOT / "policies")
CODES = load_service_codes(REPO_ROOT / "policies" / "_service-codes.yaml", CHECKLISTS)
DATE = dt.date(2026, 6, 3)


def test_every_criterion_has_a_reason() -> None:
    """Each criterion of each policy has a denial reason."""
    assert set(REASONS) == {
        c.id for checklist in CHECKLISTS.values() for c in checklist.criteria
    }


@pytest.mark.parametrize("policy_id", sorted(SERVICES))
@pytest.mark.parametrize("seed", range(6))
def test_letter_states_every_gold_field(policy_id: str, seed: int) -> None:
    """The rendered text contains the service, codes, reason, date and (if cited) the policy ref."""
    letter = render_denial(
        policy_id,
        CHECKLISTS[policy_id].criteria[0].id,
        "absent",
        DATE,
        random.Random(seed),
    )
    gold = letter.denial
    assert gold.service in letter.text
    assert all(code in letter.text for code in gold.codes)
    assert gold.reason_text in letter.text
    assert "June 3, 2026" in letter.text
    assert gold.plan_type is PlanType.MEDICARE_ADVANTAGE
    assert letter.text.startswith("SYNTHETIC TEST LETTER")
    if gold.policy_ref:
        assert gold.policy_ref in letter.text
    else:
        assert "Coverage rule used" not in letter.text


@pytest.mark.parametrize("policy_id", sorted(SERVICES))
def test_gold_denial_selects_its_policy(policy_id: str) -> None:
    """With or without a citation, policy selection on the gold Denial finds the right checklist."""
    seen_ref = seen_none = False
    for seed in range(20):
        gold = render_denial(
            policy_id,
            CHECKLISTS[policy_id].criteria[0].id,
            "absent",
            DATE,
            random.Random(seed),
        ).denial
        seen_ref |= gold.policy_ref is not None
        seen_none |= gold.policy_ref is None
        assert (
            select_policy(gold.policy_ref, gold.codes, CHECKLISTS, CODES).policy_id
            == policy_id
        )
    assert seen_ref and seen_none


def test_service_refs_are_policy_sources() -> None:
    """Each letter's citation is one of the checklist's own source ids."""
    for policy_id, info in SERVICES.items():
        assert normalize_ref(info.citation) == info.policy_ref
        assert info.policy_ref in {s.id for s in CHECKLISTS[policy_id].sources}


@pytest.mark.parametrize("criterion", sorted(REASONS))
@pytest.mark.parametrize(
    ("state", "category"),
    [
        ("failing", ReasonCategory.CRITERIA_NOT_MET),
        ("out_of_window", ReasonCategory.CRITERIA_NOT_MET),
        ("negated", ReasonCategory.CRITERIA_NOT_MET),
        ("absent", ReasonCategory.INSUFFICIENT_DOCUMENTATION),
        ("vague", ReasonCategory.INSUFFICIENT_DOCUMENTATION),
        ("conflicting", ReasonCategory.INSUFFICIENT_DOCUMENTATION),
    ],
)
def test_reason_category_follows_the_focus_state(
    criterion: str, state: str, category: ReasonCategory
) -> None:
    """A failed value is criteria_not_met; a missing or unclear record is insufficient_documentation (Step 8, D2)."""
    policy_id = next(
        pid for pid, c in CHECKLISTS.items() if criterion in {x.id for x in c.criteria}
    )
    gold = render_denial(policy_id, criterion, state, DATE, random.Random(0)).denial
    assert gold.reason_category is category
    says_missing = (
        "do not show" in gold.reason_text
        or "do not include" in gold.reason_text
        or "do not document" in gold.reason_text
        or "do not clearly" in gold.reason_text
        or "do not rule out" in gold.reason_text
    )
    assert says_missing is (category is ReasonCategory.INSUFFICIENT_DOCUMENTATION), (
        gold.reason_text
    )


def test_wrongly_denied_letters_use_both_categories() -> None:
    """A met focus criterion can be denied either way."""
    seen = {
        render_denial(
            "pap-osa", "adherence", "present", DATE, random.Random(s)
        ).denial.reason_category
        for s in range(20)
    }
    assert seen == {
        ReasonCategory.CRITERIA_NOT_MET,
        ReasonCategory.INSUFFICIENT_DOCUMENTATION,
    }
