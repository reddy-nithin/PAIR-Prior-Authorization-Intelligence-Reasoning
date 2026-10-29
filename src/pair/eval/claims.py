"""Claim labels for the conformal filter: records, the seeded-claim gate, S1 import, spot checks (ADR-0020).

Natural claims come from the real pipeline (predicted evidence) and are stored
one per line with the premise the verifier scored. The critic labels each claim
S1 ``supported``, ``partly`` or ``unsupported`` against that same premise. A
verdict counts only with a quote found verbatim in the premise.

Before labeling, a seeded set checks the critic: faults built from natural
claims (number swap, overclaim, wrong criterion, negation flip) and clean twins
that quote the record word for word. Seeded claims never enter the conformal sets.
"""

import json
import logging
import math
import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pair.contracts import ClaimDecision, Evidence
from pair.contracts._base import ContractModel
from pair.policies.mcd import normalize_whitespace

logger = logging.getLogger(__name__)

Label = Literal["supported", "partly", "unsupported"]
LABELS: tuple[Label, ...] = ("supported", "partly", "unsupported")
FAULT_TYPES = ("number_swap", "overclaim", "wrong_criterion", "negation_flip")
GATE_MIN = 30
GATE_MIN_NATURAL = 20
GATE_CATCH = 0.90
GATE_CLEAN_FLAGS = 0.10
GATE_AGREEMENT = 0.80
KAPPA_MIN = 0.70
_NUMBER = re.compile(r"(?<![A-Za-z])\d+(?![A-Za-z])")  # free-standing numbers, not the 2 in "SpO2"


class ClaimRecord(ContractModel):
    """One drafted (or seeded) claim with its premise, score and provenance."""

    claim_id: str
    case_id: str
    patient_id: str
    policy_id: str
    criterion_id: str
    text: str
    doc_id: str
    char_start: int
    char_end: int
    quote: str
    premise: str
    score: float | None
    decision: ClaimDecision | None
    drafter: str
    verifier_backend: str
    verifier_model: str
    kind: Literal["natural", "fault", "clean"] = "natural"
    fault_type: str | None = None
    premise_rule: str | None = None


def write_records(records: Sequence[ClaimRecord], path: Path) -> None:
    """Write records as JSONL."""
    path.write_text("".join(r.model_dump_json() + "\n" for r in records), encoding="utf-8")


def read_records(path: Path) -> list[ClaimRecord]:
    """Read JSONL records (validated)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ClaimRecord.model_validate_json(line) for line in lines if line.strip()]


# --- seeded gate ----------------------------------------------------------------------------


def _verbatim(quote: str) -> str:
    """The clean-twin sentence: the record quote word for word."""
    return f'My records state: "{quote}".'


def _fault_text(fault: str, source: ClaimRecord, other: ClaimRecord | None) -> str:
    """The sentence for one fault type, built from the source quote."""
    if fault == "number_swap":
        swapped = _NUMBER.sub(lambda m: str(int(m.group(0)) + 7), source.quote, count=1)
        return _verbatim(swapped)
    if fault == "overclaim":
        return f'My records state: "{source.quote}", and my doctor wrote that my condition is severe and getting worse.'
    if fault == "wrong_criterion":
        assert other is not None
        return _verbatim(other.quote)
    return f'My records say it is not true that "{source.quote}".'


def _partners(source: ClaimRecord, natural: Sequence[ClaimRecord]) -> list[ClaimRecord]:
    """Claims from the same case about another criterion whose quote isn't in the source premise."""
    return [r for r in natural if r.case_id == source.case_id and r.criterion_id != source.criterion_id
            and r.quote not in source.premise]


def _can_seed(fault: str, source: ClaimRecord, natural: Sequence[ClaimRecord]) -> bool:
    """Whether ``source`` can carry this fault type."""
    if fault == "number_swap":
        return bool(_NUMBER.search(source.quote))
    if fault == "wrong_criterion":
        return bool(_partners(source, natural))
    return True


def build_gate_set(
    records: Sequence[ClaimRecord], seed: int, n_faults: int = GATE_MIN, n_clean: int = GATE_MIN
) -> list[ClaimRecord]:
    """Seeded faults and clean twins from natural claims, deterministic by seed.

    Each source claim gives one clean twin and one fault; fault types rotate.

    Raises:
        ValueError: If there aren't enough natural claims to seed from.
    """
    natural = sorted((r for r in records if r.kind == "natural" and r.decision is not ClaimDecision.DROP),
                     key=lambda r: r.claim_id)
    needed = max(n_faults, n_clean)
    if len(natural) < needed:
        raise ValueError(f"{len(natural)} natural claims; the gate needs at least {needed} to seed from")
    rng = random.Random(seed)
    pool = rng.sample(natural, len(natural))
    gate: list[ClaimRecord] = []
    used_quotes: set[str] = set()
    for i in range(n_faults):
        fault = FAULT_TYPES[i % len(FAULT_TYPES)]
        source = next((r for r in pool if _can_seed(fault, r, natural)), None)
        if source is None:
            raise ValueError(f"no natural claim left that supports a {fault} fault")
        pool.remove(source)
        other = None
        if fault == "wrong_criterion":
            partners = _partners(source, natural)
            fresh = [r for r in partners if r.quote not in used_quotes]
            other = rng.choice(fresh or partners)
            used_quotes.add(other.quote)
        gate.append(source.model_copy(update={
            "claim_id": f"{source.claim_id}-{fault}", "text": _fault_text(fault, source, other),
            "kind": "fault", "fault_type": fault, "score": None, "decision": None,
        }))
        if i < n_clean:
            gate.append(source.model_copy(update={
                "claim_id": f"{source.claim_id}-clean", "text": _verbatim(source.quote),
                "kind": "clean", "score": None, "decision": None,
            }))
    for source in pool[: max(0, n_clean - n_faults)]:
        gate.append(source.model_copy(update={
            "claim_id": f"{source.claim_id}-clean", "text": _verbatim(source.quote),
            "kind": "clean", "score": None, "decision": None,
        }))
    logger.info("gate set: %d faults, %d clean twins (seed %d)", n_faults, n_clean, seed)
    return gate


def export_batch(records: Sequence[ClaimRecord]) -> list[dict[str, str]]:
    """Rows for the critic: claim id, claim text and premise only (no kind, label or score)."""
    return [{"claim_id": r.claim_id, "claim": r.text, "premise": r.premise} for r in records]


@dataclass(frozen=True)
class GateResult:
    """How the critic did on the seeded set and on Nithin's natural labels."""

    n_faults: int
    caught: int
    n_clean: int
    clean_flagged: int
    n_natural: int
    natural_agree: int
    passed: bool
    reasons: tuple[str, ...]


def score_gate(
    gate: Sequence[ClaimRecord],
    labels: Mapping[str, Label],
    natural_critic: Mapping[str, Label],
    natural_human: Mapping[str, Label],
) -> GateResult:
    """Score the gate: ≥90% faults caught, ≤10% clean twins flagged, ≥80% agreement on ≥20 natural claims.

    An unlabeled fault is a miss and an unlabeled clean twin counts as flagged.
    """
    faults = [r for r in gate if r.kind == "fault"]
    clean = [r for r in gate if r.kind == "clean"]
    caught = sum(labels.get(r.claim_id) in ("partly", "unsupported") for r in faults)
    flagged = sum(labels.get(r.claim_id) != "supported" for r in clean)
    shared = [cid for cid in natural_human if cid in natural_critic]
    agree = sum(natural_critic[cid] == natural_human[cid] for cid in shared)
    reasons = []
    if len(faults) < GATE_MIN or len(clean) < GATE_MIN:
        reasons.append(f"only {len(faults)} faults and {len(clean)} clean twins; need {GATE_MIN} each")
    if faults and caught / len(faults) < GATE_CATCH:
        reasons.append(f"catch rate {caught / len(faults):.0%} < {GATE_CATCH:.0%}")
    if clean and flagged / len(clean) > GATE_CLEAN_FLAGS:
        reasons.append(f"clean twins flagged {flagged / len(clean):.0%} > {GATE_CLEAN_FLAGS:.0%}")
    if len(shared) < GATE_MIN_NATURAL:
        reasons.append(f"only {len(shared)} natural claims labeled by Nithin; need {GATE_MIN_NATURAL}")
    elif agree / len(shared) < GATE_AGREEMENT:
        reasons.append(f"agreement with Nithin {agree / len(shared):.0%} < {GATE_AGREEMENT:.0%}")
    return GateResult(len(faults), caught, len(clean), flagged, len(shared), agree, not reasons, tuple(reasons))


# --- S1 import ------------------------------------------------------------------------------


@dataclass(frozen=True)
class LabelImport:
    """Valid S1 labels, claims to re-run (no valid verdict) and why lines were rejected."""

    labels: dict[str, Label]
    rerun: tuple[str, ...]
    rejected: tuple[str, ...]


@dataclass(frozen=True)
class FinalLabels:
    """Labels after the one re-run, and the claims left out (still unlabeled)."""

    labels: dict[str, Label]
    excluded: tuple[str, ...]


def import_labels(path: Path, premises: Mapping[str, str]) -> LabelImport:
    """Read S1 verdicts; keep those with a valid label and a quote verbatim in the claim's premise.

    Args:
        path: The critic's JSONL output.
        premises: Premise per claim id the batch contained.

    Returns:
        Labels, the claim ids to re-run once, and the rejected lines.
    """
    normalized = {cid: normalize_whitespace(text) for cid, text in premises.items()}
    labels: dict[str, Label] = {}
    rejected: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            rejected.append(f"line {number}: not JSON ({error})")
            continue
        problem = _s1_problem(row, normalized)
        if problem:
            rejected.append(f"line {number}: {problem}")
            continue
        labels[row["claim_id"]] = row["label"]
    rerun = tuple(cid for cid in premises if cid not in labels)
    if rejected or rerun:
        logger.warning("%s: %d lines rejected, %d claims to re-run", path, len(rejected), len(rerun))
    return LabelImport(labels, rerun, tuple(rejected))


def _s1_problem(row: object, premises: Mapping[str, str]) -> str:
    """Why an S1 row is invalid, or an empty string."""
    if not isinstance(row, dict):
        return "not an object"
    premise = premises.get(str(row.get("claim_id")))
    if premise is None:
        return f"unknown claim {row.get('claim_id')!r}"
    if row.get("label") not in LABELS:
        return f"bad label {row.get('label')!r}"
    quotes = row.get("quotes")
    if not isinstance(quotes, list) or not quotes:
        return "no quote"
    for quote in quotes:
        text = normalize_whitespace(str(quote.get("text", ""))) if isinstance(quote, dict) else ""
        if not text or text not in premise:
            return f"quote not verbatim in the premise: {text[:60]!r}"
    return ""


def finalize_labels(first: LabelImport, rerun: LabelImport | None) -> FinalLabels:
    """Merge the one re-run; claims still unlabeled are excluded and counted."""
    labels = dict(first.labels)
    if rerun is not None:
        labels.update({cid: label for cid, label in rerun.labels.items() if cid in first.rerun})
    excluded = tuple(cid for cid in first.rerun if cid not in labels)
    return FinalLabels(labels, excluded)


# --- review queue and spot check ------------------------------------------------------------


def overlaps_gold(record: ClaimRecord, gold: Sequence[Evidence]) -> bool:
    """Whether the record quote overlaps a gold span of the same criterion in the same document."""
    return any(
        item.doc_id == record.doc_id
        and item.criterion_id == record.criterion_id
        and item.char_start < record.char_end
        and record.char_start < item.char_end
        for item in gold
    )


def disagreement_queue(labels: Mapping[str, Label], overlap: Mapping[str, bool]) -> tuple[str, ...]:
    """Claims where gold overlap and S1 disagree: overlap but unsupported, or none but supported."""
    return tuple(sorted(
        cid for cid, label in labels.items()
        if (overlap.get(cid, False) and label == "unsupported") or (not overlap.get(cid, False) and label == "supported")
    ))


def spot_check_sample(
    labels: Mapping[str, Label], queue: Sequence[str], seed: int, fraction: float = 0.1, min_negative: int = 20
) -> tuple[str, ...]:
    """Nithin's sample: a random ``fraction``, every queued claim, and negatives until ``min_negative``."""
    rng = random.Random(seed)
    ids = sorted(labels)
    sample = set(rng.sample(ids, math.ceil(fraction * len(ids)))) | set(queue)
    negatives = [cid for cid in ids if labels[cid] != "supported" and cid not in sample]
    rng.shuffle(negatives)
    while negatives and sum(labels[cid] != "supported" for cid in sample if cid in labels) < min_negative:
        sample.add(negatives.pop())
    return tuple(sorted(sample))


# --- agreement ------------------------------------------------------------------------------


@dataclass(frozen=True)
class AgreementReport:
    """Critic vs Nithin on the spot-check sample.

    ``labels_count`` is decided on the binary kappa (supported vs not), the split
    calibration uses (ADR-0020 clarification, 2026-10-29); the three-class kappa
    and AC1 are always reported beside it.
    """

    n: int
    percent: float
    per_class: dict[str, float]
    kappa: float
    kappa_low: float
    kappa_high: float
    ac1: float
    kappa_binary: float
    kappa_binary_low: float
    kappa_binary_high: float
    ac1_binary: float
    labels_count: bool


def gwet_ac1(a: Sequence[Label], b: Sequence[Label]) -> float:
    """Gwet's AC1 over the three S1 classes: (pa − pe) / (1 − pe), pe = Σ π_k(1 − π_k) / (q − 1)."""
    n = len(a)
    pa = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pe = sum((pi := (a.count(k) + b.count(k)) / (2 * n)) * (1 - pi) for k in LABELS) / (len(LABELS) - 1)
    return (pa - pe) / (1 - pe)


def _kappa(a: Sequence[Label], b: Sequence[Label]) -> float:
    """Cohen's kappa over the three S1 classes (NaN when chance agreement is 1)."""
    n = len(a)
    pa = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pe = sum(a.count(k) * b.count(k) for k in LABELS) / (n * n)
    return math.nan if pe == 1 else (pa - pe) / (1 - pe)


def agreement(
    critic: Mapping[str, Label], human: Mapping[str, Label], seed: int, n_boot: int = 1000
) -> AgreementReport:
    """Percent and per-class agreement, kappa with a bootstrap 95% interval, and AC1.

    Only claims both raters labeled count. Kappa below 0.7 means the labels don't count.
    """
    shared = sorted(cid for cid in human if cid in critic)
    a = [critic[cid] for cid in shared]
    b = [human[cid] for cid in shared]
    per_class: dict[str, float] = {
        k: sum(x == y for x, y in zip(a, b, strict=True) if y == k) / b.count(k) for k in LABELS if b.count(k)
    }
    a2: list[Label] = ["supported" if x == "supported" else "unsupported" for x in a]
    b2: list[Label] = ["supported" if x == "supported" else "unsupported" for x in b]
    kappa, low, high = _kappa_with_interval(a, b, seed, n_boot)
    kappa2, low2, high2 = _kappa_with_interval(a2, b2, seed, n_boot)
    percent = sum(x == y for x, y in zip(a, b, strict=True)) / len(shared) if shared else math.nan
    ac1 = gwet_ac1(a, b) if shared else math.nan
    ac1_2 = gwet_ac1(a2, b2) if shared else math.nan
    return AgreementReport(len(shared), percent, per_class, kappa, low, high, ac1, kappa2, low2, high2, ac1_2,
                           kappa2 >= KAPPA_MIN)


def _kappa_with_interval(a: Sequence[Label], b: Sequence[Label], seed: int, n_boot: int) -> tuple[float, float, float]:
    """Cohen's kappa and a bootstrap 95% interval over claims."""
    kappa = _kappa(a, b)
    rng = random.Random(seed)
    draws = []
    for _ in range(n_boot):
        idx = [rng.randrange(len(a)) for _ in a]
        value = _kappa([a[i] for i in idx], [b[i] for i in idx])
        if not math.isnan(value):
            draws.append(value)
    draws.sort()
    if not draws:
        return kappa, math.nan, math.nan
    return kappa, draws[int(0.025 * (len(draws) - 1))], draws[math.ceil(0.975 * (len(draws) - 1))]


def load_label_file(path: Path) -> dict[str, Label]:
    """Read a ``{claim_id: label}`` JSON file (Nithin's labels).

    Raises:
        ValueError: If a label isn't one of the three S1 classes.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    bad = {cid: label for cid, label in data.items() if label not in LABELS}
    if bad:
        raise ValueError(f"{path}: unknown labels {bad}")
    return dict(data)


# --- blind export ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BlindBatches:
    """Critic batches under opaque ids, and the key back to the real claim ids (kept from the critic)."""

    batches: tuple[tuple[dict[str, str], ...], ...]
    key: dict[str, str]


def blind_batches(records: Sequence[ClaimRecord], seed: int, batch_size: int, prefix: str) -> BlindBatches:
    """Shuffle claims, give each an opaque id and split into batches, so ids and order reveal nothing."""
    order = random.Random(seed).sample(list(records), len(records))
    rows = [{"claim_id": f"{prefix}-{i:03d}", "claim": r.text, "premise": r.premise}
            for i, r in enumerate(order, start=1)]
    key = {row["claim_id"]: r.claim_id for row, r in zip(rows, order, strict=True)}
    batches = tuple(tuple(rows[i:i + batch_size]) for i in range(0, len(rows), batch_size))
    return BlindBatches(batches, key)


def unblind(labels: Mapping[str, Label], key: Mapping[str, str]) -> dict[str, Label]:
    """Labels keyed by blind id, returned keyed by the real claim id (unknown ids dropped)."""
    return {key[blind]: label for blind, label in labels.items() if blind in key}


def pick_human_naturals(
    records: Sequence[ClaimRecord], gate: Sequence[ClaimRecord], n: int, seed: int
) -> list[ClaimRecord]:
    """Natural claims for Nithin's own labels: half scored below 0.5, half at or above, none a gate source.

    Raises:
        ValueError: If either score half has too few claims left.
    """
    used = {g.premise for g in gate}
    pool = sorted((r for r in records if r.kind == "natural" and r.decision is not ClaimDecision.DROP
                   and r.score is not None and r.premise not in used), key=lambda r: r.claim_id)
    low = [r for r in pool if r.score is not None and r.score < 0.5]
    high = [r for r in pool if r.score is not None and r.score >= 0.5]
    half = n // 2
    if len(low) < half or len(high) < n - half:
        raise ValueError(f"{len(low)} low and {len(high)} high non-gate claims; the human set needs {half} and {n - half}")
    rng = random.Random(seed)
    return rng.sample(low, half) + rng.sample(high, n - half)


def load_human_jsonl(path: Path) -> tuple[dict[str, Label], tuple[str, ...]]:
    """Nithin's labeling file: one ``{claim_id, claim, premise, label}`` per line.

    Returns:
        Filled labels, and the claim ids still blank.

    Raises:
        ValueError: If a filled label isn't one of the three S1 classes, or a line isn't JSON.
    """
    labels: dict[str, Label] = {}
    blank: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} line {number}: {exc}") from exc
        label = str(row.get("label", "")).strip().lower()
        if not label:
            blank.append(row["claim_id"])
        elif label in LABELS:
            labels[row["claim_id"]] = label
        else:
            raise ValueError(f"{path} line {number}: unknown label {row.get('label')!r} (use supported, partly or unsupported)")
    return labels, tuple(blank)
