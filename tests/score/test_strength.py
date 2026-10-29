"""Tests for the strength score: odds shifts, abstention rules, steps and improve list (ADR-0007, ADR-0019)."""

from pathlib import Path

import pytest

from pair.contracts import (
    Checklist,
    CriterionResult,
    CriterionStatus,
    Gap,
    Strength,
    Verdict,
)
from pair.policies.loader import load_all
from pair.rules.active import ContextFlag
from pair.score.base_model import BaseEstimate
from pair.score.strength import (
    Adjustments,
    AdjustmentsError,
    compute_strength,
    load_adjustments,
    load_ship_links,
    odds_shift,
)

MET, INS, UNMET = CriterionStatus.MET, CriterionStatus.INSUFFICIENT, CriterionStatus.UNMET
ADJ = Adjustments(shifts={MET: 1.25, INS: 0.8, UNMET: 0.35}, max_width=0.20, rationale={"met": "a", "insufficient": "b", "unmet": "c"})
INITIAL = {"initial": ContextFlag(True, "denial: 'initial'")}
CONTINUED = {"initial": ContextFlag(False, "denial: 'continued'")}


@pytest.fixture(scope="module")
def checklists(repo_root: Path) -> dict[str, Checklist]:
    """All shipped checklists."""
    return load_all(repo_root / "policies")


def verdict(checklist: Checklist, statuses: dict[str, CriterionStatus], overall: CriterionStatus = INS) -> Verdict:
    """A verdict with the given statuses (missing ones met) and a gap per non-met criterion."""
    results = [
        CriterionResult(criterion_id=cid, status=statuses.get(cid, MET), evidence=[], trace=f"trace for {cid}")
        for cid in checklist.criterion_ids
    ]
    gaps = [Gap(criterion_id=r.criterion_id, message=f"Ask for {r.criterion_id}") for r in results if r.status is not MET]
    return Verdict(policy_id=checklist.id, results=results, overall=overall, gaps=gaps)


def base(p: float = 0.5, width: float = 0.10) -> BaseEstimate:
    """An unshifted base estimate centered on ``p``."""
    return BaseEstimate(p=p, low=p - width / 2, high=p + width / 2, n_similar=118, imr_category="DME", widened=True)


def test_odds_shift_exact() -> None:
    """odds(0.5) = 1, times 3, back to 0.75; a shift of 1 changes nothing; ends stay ends."""
    assert odds_shift(0.5, 3.0) == pytest.approx(0.75)
    assert odds_shift(0.2, 1.0) == pytest.approx(0.2)
    assert odds_shift(0.0, 5.0) == 0.0 and odds_shift(1.0, 0.2) == 1.0


def test_active_criteria_only_and_exact_math(checklists: dict[str, Checklist]) -> None:
    """Initial PAP: only f2f and AHI shift; adherence/re-evaluation gaps are filtered out."""
    pap = checklists["pap-osa"]
    strength = compute_strength(pap, verdict(pap, {"adherence": INS, "reevaluation": INS}), base(), ADJ, INITIAL)

    assert [s.criterion_id for s in strength.explanation.steps] == ["f2f_visit", "ahi_threshold"]
    assert strength.p == pytest.approx(1.5625 / 2.5625)
    assert strength.interval.low == pytest.approx(odds_shift(0.45, 1.5625))
    assert strength.interval.high == pytest.approx(odds_shift(0.55, 1.5625))
    assert not strength.abstain and strength.explanation.improve == []
    assert strength.explanation.base_rate == 0.5 and strength.explanation.n_similar == 118
    assert strength.explanation.steps[0].why == "trace for f2f_visit"


def test_width_test_uses_the_unshifted_base(checklists: dict[str, Checklist]) -> None:
    """A wide base range abstains even when shifts toward 1 would narrow it; a narrow one doesn't."""
    pap = checklists["pap-osa"]
    wide = compute_strength(pap, verdict(pap, {}), base(0.7, 0.24), ADJ, CONTINUED)
    assert wide.abstain and "Too few similar past reviews" in (wide.abstain_reason or "")
    assert wide.interval.high - wide.interval.low < 0.24
    narrow = compute_strength(pap, verdict(pap, {}), base(0.5, 0.19), ADJ, CONTINUED)
    assert not narrow.abstain


def test_active_critical_insufficient_abstains_and_gets_an_improve_entry(checklists: dict[str, Checklist]) -> None:
    """Continued PAP with adherence insufficient: abstain, and fixing it raises p."""
    pap = checklists["pap-osa"]
    strength = compute_strength(pap, verdict(pap, {"adherence": INS}), base(), ADJ, CONTINUED)

    assert strength.abstain and "adherence" in (strength.abstain_reason or "")
    (item,) = strength.explanation.improve
    assert item.criterion_id == "adherence" and item.action == "Ask for adherence"
    assert item.p_if_fixed == pytest.approx(odds_shift(0.5, 1.25**4)) and item.p_if_fixed > strength.p


def test_initial_pap_does_not_abstain_on_adherence(checklists: dict[str, Checklist]) -> None:
    """With a sourced initial flag, adherence is inactive, so no critical abstention."""
    pap = checklists["pap-osa"]
    assert not compute_strength(pap, verdict(pap, {"adherence": INS}), base(), ADJ, INITIAL).abstain


@pytest.mark.parametrize("flags", [{}, {"initial": ContextFlag(True, None)}])
def test_unknown_initial_flag_keeps_adherence_critical(
    checklists: dict[str, Checklist], flags: dict[str, ContextFlag]
) -> None:
    """Missing or unsourced flag: both branches active, so an insufficient adherence abstains."""
    pap = checklists["pap-osa"]
    assert compute_strength(pap, verdict(pap, {"adherence": INS}), base(), ADJ, flags).abstain


def test_oxygen_both_groups_insufficient_abstains(checklists: dict[str, Checklist]) -> None:
    """Any-of group with no met member and an insufficient one: abstain."""
    oxygen = checklists["home-oxygen"]
    strength = compute_strength(
        oxygen, verdict(oxygen, {"group1_blood_gas": INS, "group2_blood_gas": INS}), base(), ADJ, {}
    )
    assert strength.abstain and "group1_blood_gas" in (strength.abstain_reason or "")


def test_oxygen_one_group_met_does_not_abstain(checklists: dict[str, Checklist]) -> None:
    """One group met, the other insufficient: no any-of abstention."""
    oxygen = checklists["home-oxygen"]
    strength = compute_strength(oxygen, verdict(oxygen, {"group2_blood_gas": INS}, MET), base(), ADJ, {})
    assert not strength.abstain


def test_unmet_is_never_in_improve_and_points_to_alternatives(checklists: dict[str, Checklist]) -> None:
    """Clearly unmet: a step that says to ask about alternatives, no 'what helps' entry."""
    pap = checklists["pap-osa"]
    strength = compute_strength(pap, verdict(pap, {"ahi_threshold": UNMET}, UNMET), base(), ADJ, INITIAL)
    assert strength.explanation.improve == []
    step = next(s for s in strength.explanation.steps if s.criterion_id == "ahi_threshold")
    assert step.status is UNMET and "ask your doctor about alternatives" in step.why


def test_extreme_shifts_keep_p_inside_the_interval(checklists: dict[str, Checklist]) -> None:
    """Large shifts still give a valid Strength (p inside the range)."""
    pap = checklists["pap-osa"]
    big = Adjustments(shifts={MET: 50.0, INS: 0.01, UNMET: 0.01}, max_width=0.2, rationale={})
    strength = compute_strength(pap, verdict(pap, {}), base(0.9, 0.1), big, CONTINUED)
    assert isinstance(strength, Strength)
    assert strength.interval.low <= strength.p <= strength.interval.high


def test_verdict_is_not_changed(checklists: dict[str, Checklist]) -> None:
    """The gap list stays complete; filtering happens only in the explanation."""
    pap = checklists["pap-osa"]
    v = verdict(pap, {"adherence": INS, "reevaluation": INS})
    before = v.model_dump()
    compute_strength(pap, v, base(), ADJ, INITIAL)
    assert v.model_dump() == before and len(v.gaps) == 2


def test_verdict_for_another_policy_is_rejected(checklists: dict[str, Checklist]) -> None:
    """Checklist and verdict must match."""
    with pytest.raises(ValueError, match="home-oxygen"):
        compute_strength(checklists["pap-osa"], verdict(checklists["home-oxygen"], {}), base(), ADJ, {})


def test_shipped_adjustments_and_ship_links_load(repo_root: Path) -> None:
    """The YAML files are valid: every shift positive with a rationale, max_width 0.20, https links."""
    adjustments = load_adjustments(repo_root / "src" / "pair" / "score" / "adjustments.yaml")
    assert adjustments.max_width == 0.20
    assert set(adjustments.rationale) == {"met", "insufficient", "unmet"}
    assert adjustments.shifts[MET] > 1 > adjustments.shifts[INS] > adjustments.shifts[UNMET] > 0
    links = load_ship_links(repo_root / "policies" / "_ship.yaml")
    assert links and all(link.url.startswith("https://") for link in links)


@pytest.mark.parametrize(
    "text",
    ["max_width: 0.2\nshifts: {met: {value: 0, rationale: x}}\n", "nonsense: [", "max_width: 2\nshifts: {}\n"],
)
def test_bad_adjustments_are_rejected(tmp_path: Path, text: str) -> None:
    """Invalid values or YAML fail loudly."""
    path = tmp_path / "adjustments.yaml"
    path.write_text(text)
    with pytest.raises(AdjustmentsError):
        load_adjustments(path)


def test_bad_ship_file_is_rejected(tmp_path: Path) -> None:
    """Links must be https."""
    path = tmp_path / "_ship.yaml"
    path.write_text("links:\n  - name: x\n    url: http://x\n")
    with pytest.raises(AdjustmentsError):
        load_ship_links(path)
