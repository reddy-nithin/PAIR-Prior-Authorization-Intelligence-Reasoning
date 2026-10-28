"""Synthetic denial letters with a specific reason (CMS-0057-F style) and their gold ``Denial``.

The reason names the case's focus criterion. For type A (wrongly denied) the
records actually meet it, which is the situation an appeal should win.
Some letters omit the policy citation so the service-code fallback is exercised.
"""

import datetime as dt
import random
from dataclasses import dataclass

from pair.contracts import Denial, PlanType, ReasonCategory

CITE_PROBABILITY: float = 0.7
PLAN_NAMES: tuple[str, ...] = (
    "Heartland Senior Advantage",
    "Prairie Medicare Choice",
    "Riverbend MA Plus",
)
"""Fictional plan names."""

INSUF = ReasonCategory.INSUFFICIENT_DOCUMENTATION
NOT_MET = ReasonCategory.CRITERIA_NOT_MET


@dataclass(frozen=True)
class ServiceInfo:
    """What a policy's letters deny."""

    service: str
    codes: tuple[str, ...]
    citation: str
    """How the letter cites the policy, e.g. ``LCD L33718``."""
    policy_ref: str
    """The id a perfect parser returns, e.g. ``L33718``."""


SERVICES: dict[str, ServiceInfo] = {
    "pap-osa": ServiceInfo(
        "CPAP device (continuous positive airway pressure)",
        ("E0601",),
        "LCD L33718",
        "L33718",
    ),
    "home-oxygen": ServiceInfo(
        "Home oxygen concentrator", ("E1390",), "LCD L33797", "L33797"
    ),
    "facet-joint": ServiceInfo(
        "Lumbar radiofrequency ablation of the facet joint nerves",
        ("64635",),
        "LCD L38841",
        "L38841",
    ),
}

REASONS: dict[str, tuple[str, str]] = {
    "f2f_visit": (
        "The records do not show an in-person evaluation with your doctor before the sleep test.",
        "Your in-person evaluation with your doctor was after the sleep test, and the coverage rule requires it before.",
    ),
    "ahi_threshold": (
        "The records do not clearly show a sleep test AHI that meets the coverage rule.",
        "Your sleep test result is below the AHI the coverage rule requires (15 or more, or 5 to 14 with symptoms).",
    ),
    "adherence": (
        "The records do not include CPAP device data showing how often you used the device.",
        (
            "Your CPAP device data show use of 4 hours a night on fewer than 70% of nights in 30 days in a row "
            "in the first 3 months."
        ),
    ),
    "reevaluation": (
        "The records do not show a follow-up visit between day 31 and day 91 confirming benefit.",
        "Your follow-up visit was outside day 31 to day 91 or found that CPAP was not helping.",
    ),
    "ordered_and_evaluated": (
        "The records do not show that your doctor ordered and reviewed the oxygen test at the time you needed it.",
        "Your oxygen test was not done within 2 days of your hospital discharge, as the coverage rule requires.",
    ),
    "qualified_tester": (
        "The records do not show who performed your oxygen test.",
        "Your oxygen test was performed by the oxygen supplier, which the coverage rule does not allow.",
    ),
    "group1_blood_gas": (
        "The records do not clearly show oxygen test results at the levels required for home oxygen.",
        "Your oxygen test results are above the levels required for home oxygen.",
    ),
    "group2_blood_gas": (
        "The records do not clearly show oxygen test results at the levels required for home oxygen.",
        "Your oxygen test results are above the levels required for home oxygen.",
    ),
    "home_benefit": (
        "The records do not show that home oxygen is expected to improve your condition.",
        "Your doctor's notes say home oxygen is not expected to improve your condition.",
    ),
    "pain_and_function": (
        "The records do not document a pain score and how the pain limits your function.",
        "Your pain score is below the moderate level the coverage rule requires.",
    ),
    "duration_and_conservative_care": (
        "The records do not show how long you have had pain or what treatments you tried first.",
        "Your pain has lasted less than the 3 months the coverage rule requires.",
    ),
    "no_untreated_radiculopathy": (
        "The records do not show whether you have nerve-root pain (radiculopathy) or neurogenic claudication.",
        "The records show nerve-root pain (radiculopathy) that has not been treated.",
    ),
    "no_other_pathology": (
        "The records do not rule out another cause of your pain, such as a fracture, tumor or infection.",
        "Your imaging shows another cause of your pain that the coverage rule excludes.",
    ),
    "diagnostic_block_relief": (
        "The records do not show the results of two diagnostic nerve blocks.",
        "Fewer than two of your diagnostic nerve blocks gave 80% or more pain relief.",
    ),
}
"""Per criterion: (records missing or unclear → insufficient_documentation, a value fails → criteria_not_met)."""

NOT_MET_STATES: frozenset[str] = frozenset({"failing", "out_of_window", "negated"})
INSUF_STATES: frozenset[str] = frozenset({"absent", "vague", "conflicting"})
"""Focus states whose letter category is fixed; a met focus (type A) is denied either way at random."""

TEMPLATE: str = """SYNTHETIC TEST LETTER - not a real patient or health plan
{plan} (a Medicare Advantage plan)
Notice of Denial of Medical Coverage

Date: {date}
Member ID: SYN-{member}

We denied your request for: {service} ({code_label} {codes}).

Why we denied it: {reason}
{citation_line}
You have the right to appeal this decision. Ask for an appeal within 65 days of the date of this notice.
Call Member Services at 1-800-555-0100 (TTY 711).
"""


@dataclass(frozen=True)
class DenialLetter:
    """A rendered letter and its gold parse."""

    text: str
    denial: Denial


def render_denial(
    policy_id: str,
    focus_criterion: str,
    focus_state: str,
    date: dt.date,
    rng: random.Random,
) -> DenialLetter:
    """Render a denial letter for a policy and the criterion the plan says is missing.

    The reason's wording and category follow the focus state: a failed value is
    ``criteria_not_met``, a missing or unclear record ``insufficient_documentation``
    (the definitions in ``pair.ingest.denial``).

    Raises:
        KeyError: If the policy or criterion has no template.
    """
    info = SERVICES[policy_id]
    category = _category(focus_state, rng)
    reason = REASONS[focus_criterion][0 if category is INSUF else 1]
    cite = rng.random() < CITE_PROBABILITY
    code_label = "CPT" if info.codes[0].isdigit() else "HCPCS"
    text = TEMPLATE.format(
        plan=rng.choice(PLAN_NAMES),
        date=f"{date:%B} {date.day}, {date.year}",
        member=rng.randint(100000, 999999),
        service=info.service,
        code_label=code_label,
        codes=", ".join(info.codes),
        reason=reason,
        citation_line=f"Coverage rule used: {info.citation}.\n" if cite else "",
    )
    denial = Denial(
        service=info.service,
        codes=list(info.codes),
        reason_text=reason,
        reason_category=category,
        policy_ref=info.policy_ref if cite else None,
        plan_type=PlanType.MEDICARE_ADVANTAGE,
        date=date,
    )
    return DenialLetter(text=text, denial=denial)


def _category(focus_state: str, rng: random.Random) -> ReasonCategory:
    """The letter's reason category for the focus unit's state."""
    if focus_state in NOT_MET_STATES:
        return NOT_MET
    if focus_state in INSUF_STATES:
        return INSUF
    return rng.choice([INSUF, NOT_MET])


def reason_categories(reason_text: str) -> set[ReasonCategory]:
    """The categories whose template has this exact reason text (empty if none does)."""
    return {
        category
        for insufficient, not_met in REASONS.values()
        for category, text in ((INSUF, insufficient), (NOT_MET, not_met))
        if text == reason_text
    }
