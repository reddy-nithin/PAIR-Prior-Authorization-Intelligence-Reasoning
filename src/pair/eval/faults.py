"""Seeded faults for testing the audit critic (ADR-0013, critic plan Step 6).

Each fault takes a clean synthetic case and returns a copy with one known
problem, plus a key entry saying which rubric checks should catch it. The
critic never sees the key. Faults only append text or swap text of equal
length, so gold span offsets stay valid and the case still loads.
"""

import random
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pair.contracts import Checklist, CriterionStatus, Evidence, ReasonCategory
from pair.eval.cases import CaseBundle, CaseType, Note
from pair.eval.synth.denials import REASONS
from pair.eval.synth.planners import UNITS


@dataclass(frozen=True)
class Fault:
    """The key entry for one seeded fault.

    Attributes:
        kind: Fault type, e.g. ``paraphrase_leak``.
        expected: Rubric check ids that should flag it (any one counts).
        severity: The rubric severity a correct critic gives it.
        target: The criterion, unit or field it affects.
        description: What was changed, for the score report.
    """

    kind: str
    expected: tuple[str, ...]
    severity: str
    target: str
    description: str


FaultFn = Callable[
    [CaseBundle, Checklist, random.Random], tuple[CaseBundle, Fault] | None
]

PARAPHRASES: dict[tuple[str, str], str] = {
    ("pap-osa", "f2f_visit"): "He was examined in person in sleep clinic two weeks before the home study.",
    ("pap-osa", "ahi_threshold"): "The overnight study found 27 breathing pauses or shallow-breathing episodes per hour of sleep.",
    ("pap-osa", "adherence"): "Machine download: mask worn on 24 of the last 30 nights, averaging about five and a half hours of use.",
    ("pap-osa", "reevaluation"): "Seen back in clinic 6 weeks after starting CPAP; he wakes rested and the daytime sleepiness is gone.",
    ("home-oxygen", "ordered_and_evaluated"): "The treating physician ordered the oximetry and went over the results at this visit.",
    ("home-oxygen", "qualified_tester"): "The overnight oximetry was done by the hospital's respiratory therapy department.",
    ("home-oxygen", "blood_gas"): "Resting oxygen level on room air read 86 percent on the finger probe.",
    ("home-oxygen", "home_benefit"): "Oxygen at home should make the breathlessness and exercise tolerance better.",
    ("facet-joint", "pain_and_function"): "She rates the back pain a seven out of ten and can no longer stand long enough to cook.",
    ("facet-joint", "duration_and_conservative_care"): (
        "The pain began well over half a year ago, and a course of supervised exercise therapy did not help."
    ),
    ("facet-joint", "no_untreated_radiculopathy"): "Also describes shooting pain down the back of the left leg to the foot, with numbness.",
    ("facet-joint", "no_other_pathology"): "MRI also shows a compression deformity of the L2 vertebral body, age indeterminate.",
    ("facet-joint", "diagnostic_block_relief"): "After the test injections the pain went from 8 to 1 for about six hours.",
}  # fmt: skip
"""For each planner unit: a sentence that supplies its value without matching the unit's leak regex."""

_AGE = re.compile(r"\b(\d{2})-year-old")
_LEADING_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _replace_note(case: CaseBundle, doc_id: str, text: str) -> list[Note]:
    """The case's notes with one note's text replaced."""
    return [
        Note(doc_id=n.doc_id, title=n.title, text=text) if n.doc_id == doc_id else n
        for n in case.notes
    ]


def _append(case: CaseBundle, doc_id: str, sentence: str) -> list[Note]:
    """The case's notes with a sentence appended to one note (gold offsets stay valid)."""
    note = next(n for n in case.notes if n.doc_id == doc_id)
    return _replace_note(case, doc_id, note.text.rstrip() + " " + sentence)


def _numeric(case: CaseBundle) -> list[Evidence]:
    """Asserted gold evidence with a numeric value."""
    return [
        e for e in case.gold_evidence
        if e.status.value == "asserted" and isinstance(e.value, int | float) and not isinstance(e.value, bool)
    ]  # fmt: skip


def label_flip(
    case: CaseBundle, checklist: Checklist, rng: random.Random
) -> tuple[CaseBundle, Fault] | None:
    """Flip one gold criterion status (a mechanical fault the precheck must catch)."""
    cid = rng.choice(sorted(case.gold_statuses))
    old = case.gold_statuses[cid]
    new = (
        CriterionStatus.UNMET
        if old is not CriterionStatus.UNMET
        else CriterionStatus.MET
    )
    bad = case.model_copy(update={"gold_statuses": {**case.gold_statuses, cid: new}})
    return bad, Fault(
        "label_flip", ("L1",), "blocker", cid, f"gold {cid} changed from {old} to {new}"
    )


def span_value_mismatch(
    case: CaseBundle, checklist: Checklist, rng: random.Random
) -> tuple[CaseBundle, Fault] | None:
    """Change the number inside a planted span, keeping the gold value (span no longer states it)."""
    candidates = [e for e in _numeric(case) if _LEADING_NUMBER.search(e.span_text)]
    if not candidates:
        return None
    item = rng.choice(candidates)
    match = _LEADING_NUMBER.search(item.span_text)
    assert match is not None
    digits = match.group()
    first = str((int(digits[0]) + rng.randint(3, 6)) % 10 or 1)
    changed = first + digits[1:]
    new_span = item.span_text[: match.start()] + changed + item.span_text[match.end() :]
    note = next(n for n in case.notes if n.doc_id == item.doc_id)
    text = note.text[: item.char_start] + new_span + note.text[item.char_end :]
    evidence = [
        e.model_copy(update={"span_text": new_span})
        if (e.doc_id, e.char_start) == (item.doc_id, item.char_start)
        else e
        for e in case.gold_evidence
    ]
    bad = case.model_copy(
        update={
            "notes": _replace_note(case, item.doc_id, text),
            "gold_evidence": evidence,
        }
    )
    description = (
        f"{item.variable}: note now says {new_span!r}, gold value still {item.value}"
    )
    return bad, Fault(
        "span_value_mismatch", ("L3", "L1"), "blocker", item.criterion_id, description
    )


def paraphrase_leak(
    case: CaseBundle, checklist: Checklist, rng: random.Random
) -> tuple[CaseBundle, Fault] | None:
    """Supply a missing unit's value in words its leak regex doesn't catch."""
    absent = [
        u.name for u in UNITS[case.policy_id] if case.states.get(u.name) == "absent"
    ]
    if not absent:
        return None
    unit = rng.choice(sorted(absent))
    sentence = PARAPHRASES[(case.policy_id, unit)]
    bad = case.model_copy(update={"notes": _append(case, "clinic", sentence)})
    return bad, Fault(
        "paraphrase_leak",
        ("K1", "L1"),
        "blocker",
        unit,
        f"clinic note now says: {sentence}",
    )


def contradiction(
    case: CaseBundle, checklist: Checklist, rng: random.Random
) -> tuple[CaseBundle, Fault] | None:
    """Add a second, different value for a planted number in the other note."""
    candidates = _numeric(case)
    if not candidates:
        return None
    item = rng.choice(candidates)
    match = _LEADING_NUMBER.search(item.span_text)
    if match is None or float(match.group()) != float(item.value):  # type: ignore[arg-type]
        return None
    other = next((n.doc_id for n in case.notes if n.doc_id != item.doc_id), item.doc_id)
    alt = f"{float(item.value) * rng.choice((0.5, 1.6)):.1f}".removesuffix(".0")  # type: ignore[arg-type]
    restated = item.span_text[: match.start()] + alt + item.span_text[match.end() :]
    sentence = f"An outside summary from the referring office lists: {restated}."
    bad = case.model_copy(update={"notes": _append(case, other, sentence)})
    description = f"{other} now has {alt} for {item.variable} (gold {item.value})"
    return bad, Fault(
        "contradiction", ("K2", "L1", "R1"), "major", item.criterion_id, description
    )


def denial_reason_swap(
    case: CaseBundle, checklist: Checklist, rng: random.Random
) -> tuple[CaseBundle, Fault] | None:
    """For a type B to D case, make the letter's reason name a criterion the record meets."""
    if case.case_type is CaseType.WRONGLY_DENIED:
        return None
    met = [
        c
        for c, s in sorted(case.gold_statuses.items())
        if s is CriterionStatus.MET and c in REASONS
    ]
    category = case.gold_denial.reason_category
    wording = 0 if category is ReasonCategory.INSUFFICIENT_DOCUMENTATION else 1
    met = [c for c in met if REASONS[c][wording] != case.gold_denial.reason_text]
    if not met:
        return None
    cid = rng.choice(met)
    reason = REASONS[cid][wording]
    text = case.denial_text.replace(case.gold_denial.reason_text, reason)
    denial = case.gold_denial.model_copy(
        update={"reason_text": reason, "reason_category": category}
    )
    bad = case.model_copy(update={"denial_text": text, "gold_denial": denial})
    return bad, Fault(
        "denial_reason_swap",
        ("D2",),
        "major",
        cid,
        f"type {case.case_type.value} letter now denies on met {cid}",
    )


def age_mismatch(
    case: CaseBundle, checklist: Checklist, rng: random.Random
) -> tuple[CaseBundle, Fault] | None:
    """Change the patient's age in the clinic note so it disagrees with the profile."""
    note = next(n for n in case.notes if n.doc_id == "clinic")
    new_age = str(case.profile.age + rng.choice((-11, -9, 9, 11)))
    match = _AGE.search(note.text)
    in_span = match is not None and any(
        e.doc_id == "clinic" and e.char_start <= match.start(1) < e.char_end
        for e in case.gold_evidence
    )
    if match and not in_span and len(new_age) == len(match.group(1)):
        notes = _replace_note(
            case,
            "clinic",
            note.text[: match.start(1)] + new_age + note.text[match.end(1) :],
        )
    else:
        person = "woman" if case.profile.sex == "F" else "man"
        notes = _append(
            case, "clinic", f"Addendum: patient is a {new_age}-year-old {person}."
        )
    bad = case.model_copy(update={"notes": notes})
    return bad, Fault(
        "age_mismatch",
        ("R1",),
        "major",
        "profile",
        f"clinic age now {new_age}, profile {case.profile.age}",
    )


def impossible_vital(
    case: CaseBundle, checklist: Checklist, rng: random.Random
) -> tuple[CaseBundle, Fault] | None:
    """Add a physiologically impossible vital sign to the clinic note."""
    sentence = (
        "Vitals today: BP 134/82, HR 74, temperature 44.9 C."
        if case.policy_id == "home-oxygen"
        else "Vitals today: BP 134/82, HR 74, SpO2 106% on room air."
    )
    bad = case.model_copy(update={"notes": _append(case, "clinic", sentence)})
    return bad, Fault("impossible_vital", ("R2",), "major", "vitals", sentence)


def template_echo(
    case: CaseBundle, checklist: Checklist, rng: random.Random
) -> tuple[CaseBundle, Fault] | None:
    """Leak case-spec wording into a note, as a broken generator would."""
    unit = rng.choice(sorted(case.states))
    sentence = f"[plan: {unit} = {case.states[unit]}]"
    bad = case.model_copy(update={"notes": _append(case, "report", sentence)})
    return bad, Fault(
        "template_echo", ("R3",), "minor", unit, f"report now ends with {sentence}"
    )


FAULTS: Mapping[str, FaultFn] = {
    "label_flip": label_flip,
    "span_value_mismatch": span_value_mismatch,
    "paraphrase_leak": paraphrase_leak,
    "contradiction": contradiction,
    "denial_reason_swap": denial_reason_swap,
    "age_mismatch": age_mismatch,
    "impossible_vital": impossible_vital,
    "template_echo": template_echo,
}

DEFAULT_MIX: Mapping[str, int] = {
    "label_flip": 2,
    "span_value_mismatch": 3,
    "paraphrase_leak": 3,
    "contradiction": 3,
    "denial_reason_swap": 3,
    "age_mismatch": 2,
    "impossible_vital": 2,
    "template_echo": 2,
}
"""20 faults; with 10 clean twins that makes 30 seeded cases."""


@dataclass(frozen=True)
class SeededCase:
    """One case in the seeded set and its key entry (``fault`` is None for a clean twin)."""

    seed_id: str
    base_case: str
    case: CaseBundle
    fault: Fault | None


class SeedingError(ValueError):
    """The base cases can't supply the requested fault mix."""


def seed_suite(
    cases: list[CaseBundle],
    checklists: Mapping[str, Checklist],
    seed: int,
    mix: Mapping[str, int] = DEFAULT_MIX,
    n_clean: int = 10,
) -> list[SeededCase]:
    """Build a shuffled seeded set: faulted copies plus clean twins of some of their bases.

    Ids are renamed ``seed-01`` and up after shuffling, so an id says nothing about the fault.

    Raises:
        SeedingError: If no base case accepts a requested fault.
    """
    rng = random.Random(seed)
    made: list[tuple[CaseBundle, CaseBundle, Fault | None]] = []
    for kind, count in mix.items():
        pool = cases[:]
        rng.shuffle(pool)
        added = 0
        for base in pool:
            if added == count:
                break
            result = FAULTS[kind](base, checklists[base.policy_id], rng)
            if result is not None:
                made.append((base, result[0], result[1]))
                added += 1
        if added < count:
            raise SeedingError(f"only {added} of {count} {kind} faults could be seeded")
    bases = list(dict.fromkeys(base.id for base, _, _ in made))
    rng.shuffle(bases)
    by_id = {case.id: case for case in cases}
    made += [(by_id[b], by_id[b], None) for b in bases[:n_clean]]
    rng.shuffle(made)
    width = max(2, len(str(len(made))))
    seeded: list[SeededCase] = []
    for i, (base, case, fault) in enumerate(made, start=1):
        seed_id = f"seed-{i:0{width}d}"
        seeded.append(
            SeededCase(seed_id, base.id, case.model_copy(update={"id": seed_id}), fault)
        )
    return seeded
