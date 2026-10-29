"""Phase 3 report: claim funnel, conformal rates, exit verdict and IMR numbers for ``RESULTS.md`` (T10).

The claim funnel follows the claim funnel study (spec §6.3): coverage (gold-met
criteria argued by at least one claim), verbatim (citations pass the span and
criterion-link checks), lenient support (S1 supported or partly), strict support
(S1 supported), and CCR after the verifier (strict support among KEPT claims).
Every support number is relative to the critic's S1 labels.
"""

import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scipy.stats import ks_2samp

from pair.contracts import ClaimDecision
from pair.eval.claims import ClaimRecord, Label
from pair.eval.metrics import update_results
from pair.eval.trust_stats import ClaimOutcome, LetterOutcome, RateEstimate, Verdict
from pair.score.strength import IMR_NOTE
from pair.verify.pipeline import VerifiedLetter

MARKER = "phase3-trust"


@dataclass(frozen=True)
class Count:
    """k of n."""

    k: int
    n: int

    @property
    def rate(self) -> float:
        """k / n, NaN when n is 0."""
        return self.k / self.n if self.n else math.nan


@dataclass(frozen=True)
class Funnel:
    """The claim funnel over natural claims."""

    n_claims: int
    coverage: Count
    verbatim: Count
    lenient: Count
    strict: Count
    ccr_after: Count


def claim_records(
    case_id: str, patient_id: str, verified: VerifiedLetter
) -> list[ClaimRecord]:
    """One record per claim of a verified letter, with its premise and run tags."""
    meta = verified.metadata
    return [
        ClaimRecord(
            claim_id=f"{case_id}-{i:02d}", case_id=case_id, patient_id=patient_id,
            policy_id=verified.letter.policy_id, criterion_id=claim.criterion_id, text=claim.text,
            doc_id=claim.evidence_cite.doc_id, char_start=claim.evidence_cite.char_start,
            char_end=claim.evidence_cite.char_end, quote=claim.evidence_cite.quote, premise=premise or "",
            score=claim.score, decision=claim.decision, drafter=meta["drafter"],
            verifier_backend=meta["verifier_backend"], verifier_model=meta["verifier_model"], premise_rule=meta["premise_rule"],
        )
        for i, (claim, premise) in enumerate(zip(verified.letter.claims, verified.premises, strict=True))
    ]


def _natural(records: Sequence[ClaimRecord]) -> list[ClaimRecord]:
    """Pipeline claims only (seeded gate claims never count)."""
    return [r for r in records if r.kind == "natural"]


def claim_funnel(
    records: Sequence[ClaimRecord], labels: Mapping[str, Label], gold_met: Mapping[str, frozenset[str]]
) -> Funnel:
    """Coverage, verbatim, lenient, strict and CCR after the verifier."""
    natural = _natural(records)
    argued = {(r.case_id, r.criterion_id) for r in natural}
    gold_pairs = [(case, cid) for case, met in gold_met.items() for cid in met]
    passed = [r for r in natural if r.decision is not ClaimDecision.DROP]
    labeled = [labels[r.claim_id] for r in passed if r.claim_id in labels]
    kept = [labels[r.claim_id] for r in passed if r.decision is ClaimDecision.KEEP and r.claim_id in labels]
    return Funnel(
        n_claims=len(natural),
        coverage=Count(sum(pair in argued for pair in gold_pairs), len(gold_pairs)),
        verbatim=Count(len(passed), len(natural)),
        lenient=Count(sum(label in ("supported", "partly") for label in labeled), len(labeled)),
        strict=Count(sum(label == "supported" for label in labeled), len(labeled)),
        ccr_after=Count(sum(label == "supported" for label in kept), len(kept)),
    )


def letter_outcomes(
    records: Sequence[ClaimRecord], labels: Mapping[str, Label], gold_met: Mapping[str, frozenset[str]]
) -> list[LetterOutcome]:
    """Natural claims grouped into one outcome per case, for the conformal rates."""
    by_case: dict[str, list[ClaimRecord]] = {}
    for record in _natural(records):
        by_case.setdefault(record.case_id, []).append(record)
    return [
        LetterOutcome(
            case_id=case_id,
            patient_id=rows[0].patient_id,
            claims=tuple(ClaimOutcome(r.criterion_id, r.decision, labels.get(r.claim_id)) for r in rows),
            gold_met=gold_met.get(case_id, frozenset()),
        )
        for case_id, rows in sorted(by_case.items())
    ]


@dataclass(frozen=True)
class Shift:
    """Dev (calibration) against test: claim mix and unsupported verifier scores (ADR-0020 exchangeability check)."""

    policy_mix: dict[str, tuple[float, float]]
    criterion_tv: float
    n_calib: int
    n_test: int
    median_calib: float
    median_test: float
    ks_stat: float
    ks_p: float


def _shares(values: Sequence[str]) -> dict[str, float]:
    """Share of each value."""
    counts = Counter(values)
    return {key: count / len(values) for key, count in counts.items()}


def _unsupported_scores(records: Sequence[ClaimRecord], labels: Mapping[str, Label]) -> list[float]:
    """Verifier scores of checked natural claims labeled partly or unsupported (the set q̂ is fit on)."""
    return [r.score for r in _natural(records) if r.decision is not ClaimDecision.DROP
            and labels.get(r.claim_id) in ("partly", "unsupported") and r.score is not None]


def exchangeability(
    calib: Sequence[ClaimRecord], calib_labels: Mapping[str, Label],
    test: Sequence[ClaimRecord], test_labels: Mapping[str, Label],
) -> Shift:
    """Compare policy mix, criterion mix (total variation) and unsupported scores (two-sample KS) across the split."""
    calib_nat, test_nat = _natural(calib), _natural(test)
    pol_c, pol_t = _shares([r.policy_id for r in calib_nat]), _shares([r.policy_id for r in test_nat])
    crit_c = _shares([f"{r.policy_id}/{r.criterion_id}" for r in calib_nat])
    crit_t = _shares([f"{r.policy_id}/{r.criterion_id}" for r in test_nat])
    tv = 0.5 * sum(abs(crit_c.get(k, 0.0) - crit_t.get(k, 0.0)) for k in crit_c.keys() | crit_t.keys())
    scores_c, scores_t = _unsupported_scores(calib, calib_labels), _unsupported_scores(test, test_labels)
    ks = ks_2samp(scores_c, scores_t)
    return Shift(
        policy_mix={k: (pol_c.get(k, 0.0), pol_t.get(k, 0.0)) for k in sorted(pol_c.keys() | pol_t.keys())},
        criterion_tv=tv, n_calib=len(scores_c), n_test=len(scores_t),
        median_calib=statistics.median(scores_c), median_test=statistics.median(scores_t),
        ks_stat=float(ks.statistic), ks_p=float(ks.pvalue),
    )


def _shift_lines(shift: Shift) -> list[str]:
    """The exchangeability section."""
    return [
        "",
        "### Exchangeability check: dev calibration vs test (ADR-0020)",
        "",
        ("Disjoint patients are not the same as exchangeable sets, so the claim mix and the verifier scores of "
         "unsupported claims are compared here rather than assumed equal."),
        "",
        "| Policy | Dev share | Test share |",
        "|---|---|---|",
        *(f"| {policy} | {dev:.1%} | {test:.1%} |" for policy, (dev, test) in shift.policy_mix.items()),
        "",
        f"Criterion mix, total variation distance: {shift.criterion_tv:.3f} (0 = same mix, 1 = no overlap).",
        (f"Unsupported (partly or unsupported) verifier scores: dev n {shift.n_calib}, median {shift.median_calib:.3f}; "
         f"test n {shift.n_test}, median {shift.median_test:.3f}; two-sample KS statistic {shift.ks_stat:.3f}, "
         f"p {shift.ks_p:.3f}."),
    ]


def _agreement_line(agreement: Mapping[str, float], source: str) -> str:
    """Spot-check agreement next to the leak rate (ADR-0020, both kappas after the 2026-10-29 clarification)."""
    a = agreement
    return (f"Critic labels checked against Nithin's {source} spot check (n {int(a['n'])}): "
            f"binary kappa {a['kappa_binary']:.2f} [{a['kappa_binary_low']:.2f}, {a['kappa_binary_high']:.2f}], "
            f"AC1 {a['ac1_binary']:.2f}; 3-class kappa {a['kappa']:.2f} [{a['kappa_low']:.2f}, {a['kappa_high']:.2f}], "
            f"AC1 {a['ac1']:.2f}. The labels count on the binary kappa (rule: at least 0.7).")


def _reliability_lines(bins: Sequence[Mapping[str, Any]]) -> list[str]:
    """Venn-Abers reliability table on 2024 and later."""
    return [
        "",
        "Reliability (Venn-Abers point estimate, bins with at least one case):",
        "",
        "| Predicted | n | Mean predicted | Observed overturn rate |",
        "|---|---|---|---|",
        *(f"| {b['low']:.1f} to {b['high']:.1f} | {int(b['n'])} | {b['mean_predicted']:.3f} | {b['observed']:.3f} |"
          for b in bins if b["n"]),
    ]


def _count(name: str, count: Count) -> str:
    """One funnel row."""
    return f"| {name} | {count.k} / {count.n} | {count.rate:.1%} |"


def _rate(name: str, rate: RateEstimate) -> str:
    """One conformal row with both intervals."""
    return (f"| {name} | {rate.k} / {rate.n} | {rate.point:.3f} | [{rate.boot_low:.3f}, {rate.boot_high:.3f}] | "
            f"[{rate.naive_low:.3f}, {rate.naive_high:.3f}] |")


def trust_markdown(
    funnel: Funnel,
    rates: Mapping[str, RateEstimate],
    verdict: Verdict,
    leak_bound: float | None,
    imr: Mapping[str, Any] | None,
    meta: Mapping[str, str],
    agreement: Mapping[str, float] | None = None,
    agreement_source: str = "dev",
    shift: Shift | None = None,
) -> str:
    """The ``phase3-trust`` section of ``RESULTS.md``."""
    lines = [
        "## Phase 3: trust layer",
        "",
        "Run: " + ", ".join(f"{k} `{v}`" for k, v in meta.items()),
        "",
        "### Claim funnel (natural claims; support relative to critic labels)",
        "",
        "| Stage | k / n | Rate |",
        "|---|---|---|",
        _count("Coverage (gold-met criteria argued)", funnel.coverage),
        _count("Verbatim (span and criterion link)", funnel.verbatim),
        _count("Lenient support", funnel.lenient),
        _count("Strict support", funnel.strict),
        _count("CCR after verifier (strict among kept)", funnel.ccr_after),
        "",
        "### Conformal filter on the test side (relative to critic labels)",
        "",
        "Intervals: patient-level cluster bootstrap 95%, and Clopper-Pearson labeled naive (assumes independent claims).",
        "",
        "| Rate | k / n | Point | Bootstrap 95% | Naive 95% |",
        "|---|---|---|---|---|",
    ]
    names = {"leak": "Leak rate (kept among strict-unsupported, alpha 0.1)", "empty": "Empty-letter rate",
             "support": "Support among non-empty letters", "precision": "Precision of kept claims (descriptive)",
             "worst_leak": "Worst-case leak (unlabeled counted unsupported)"}
    lines += [_rate(names.get(key, key), rate) for key, rate in rates.items()]
    bound = "not fit" if leak_bound is None else f"{leak_bound:.3f}"
    lines += [
        "",
        f"P(leak > 0.2) for the fitted threshold: {bound}.",
        "Exit rule (pre-registered, ADR-0020): pass only if n >= 30, point <= 0.15 and bootstrap upper <= 0.30.",
        f"Verdict: **{verdict}**.",
    ]
    if agreement:
        lines += ["", _agreement_line(agreement, agreement_source)]
    if shift:
        lines += _shift_lines(shift)
    if imr:
        lines += [
            "",
            "### IMR base model on 2024 and later (scored once)",
            "",
            (f"n {int(imr['n'])}, AUROC {imr['auroc']:.3f}, Brier {imr['brier']:.4f}, Mondrian 90% coverage "
            f"{imr['coverage']:.3f} (Clopper-Pearson [{imr['coverage_low']:.3f}, {imr['coverage_high']:.3f}]), "
            f"share of uninformative {{0,1}} sets {imr['share_both']:.2f}."),
            *_reliability_lines(imr.get("reliability", ())),
            "",
            IMR_NOTE,
        ]
    return "\n".join(lines)


def write_trust_results(path: Path, section: str) -> Path:
    """Write the section between the ``phase3-trust`` markers."""
    return update_results(path, section, marker=MARKER)
