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
PLAN_NAMES: tuple[str, ...] = ("Heartland Senior Advantage", "Prairie Medicare Choice", "Riverbend MA Plus")
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
    "pap-osa": ServiceInfo("CPAP device (continuous positive airway pressure)", ("E0601",), "LCD L33718", "L33718"),
    "home-oxygen": ServiceInfo("Home oxygen concentrator", ("E1390",), "LCD L33797", "L33797"),
    "facet-joint": ServiceInfo(
        "Lumbar radiofrequency ablation of the facet joint nerves", ("64635",), "LCD L38841", "L38841"
    ),
}

REASONS: dict[str, tuple[ReasonCategory, str]] = {
    "f2f_visit": (INSUF, "The records do not show an in-person evaluation with your doctor before the sleep test."),
    "ahi_threshold": (NOT_MET, "The sleep test results do not show an AHI of 15 or more, or 5 to 14 with symptoms."),
    "adherence": (NOT_MET, "The device data do not show use of 4 hours a night on 70% of nights in 30 days in a row."),
    "reevaluation": (INSUF, "The records do not show a follow-up visit between day 31 and day 91 confirming benefit."),
    "ordered_and_evaluated": (INSUF, "The records do not show that your doctor ordered and reviewed the oxygen test."),
    "qualified_tester": (NOT_MET, "The oxygen test was not performed by a qualified provider or laboratory."),
    "group1_blood_gas": (NOT_MET, "Your oxygen test results do not meet the levels required for home oxygen."),
    "group2_blood_gas": (NOT_MET, "Your oxygen test results do not meet the levels required for home oxygen."),
    "home_benefit": (INSUF, "The records do not show that home oxygen is expected to improve your condition."),
    "pain_and_function": (INSUF, "The records do not document a pain score and how the pain limits your function."),
    "duration_and_conservative_care": (
        NOT_MET,
        "The records do not show 3 months of pain with failed conservative treatment such as physical therapy.",
    ),
    "no_untreated_radiculopathy": (NOT_MET, "The records show nerve-root pain (radiculopathy) that has not been treated."),
    "no_other_pathology": (NOT_MET, "The records do not rule out another cause of your pain."),
    "diagnostic_block_relief": (
        NOT_MET,
        "The records do not show two diagnostic nerve blocks that each gave 80% or more pain relief.",
    ),
}

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


def render_denial(policy_id: str, focus_criterion: str, date: dt.date, rng: random.Random) -> DenialLetter:
    """Render a denial letter for a policy and the criterion the plan says is missing.

    Raises:
        KeyError: If the policy or criterion has no template.
    """
    info = SERVICES[policy_id]
    category, reason = REASONS[focus_criterion]
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
