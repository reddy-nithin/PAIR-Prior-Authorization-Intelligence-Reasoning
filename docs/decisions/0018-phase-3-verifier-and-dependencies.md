# ADR-0018: Phase 3 verifier, claim granularity and dependencies

**Status:** Accepted (Nithin, 2026-10-28). Amended by [ADR-0022](0022-premise-previous-sentence.md): after a referring opener the premise also includes the previous sentence.
**Date:** 2026-10-28
**Supersedes:** (none; settles spec §6.3, §6.4 and the §7 verifier and strength-model rows for Phase 3)

## Context

Phase 3 drafts a cited appeal letter and checks every claim (spec §6.3 to 6.5). Three things are open.

1. **Claim granularity.** The `Claim` contract (Phase 1) has exactly one policy quote and one record quote. Most criteria need two or more record facts: `f2f_visit` needs two dates, `adherence` needs a percentage and a window, `reevaluation` needs dates and an improvement statement. One claim per criterion with one record quote couldn't be fully supported for those criteria. Some facts the rule engine uses are also computed, not written: day counts between dates (ADR-0012) appear in no record line.
2. **Where the entailment model runs.** Bespoke-MiniCheck-7B is the spec's verifier. At about 4.7 GB on Ollama it doesn't fit beside the demo model on the 8 GB M2 (ADR-0011).
3. **New libraries.** The strength score needs a tabular model and calibration. The spec lists LightGBM, MAPIE and crepes as options.

## Decision

- **One claim per fact.** Each asserted evidence item bound to a met criterion becomes one claim, with the criterion's verbatim clause as the policy quote and the evidence span as the record quote. A claim asserts only what its record quote says. The letter groups a criterion's claims into one paragraph. Unmet and insufficient criteria get no claims; the reason is passed to the UI. The `Claim` and `Letter` contracts don't change (the `contracts/letter.py` docstring is updated to say one claim per fact).
- **Computed facts and conclusions are templated, not claimed.** Values the rule engine derives (day counts, windows) and the "so this requirement is met" sentence come from the rule trace through a fixed template. They aren't `Claim`s and the entailment model doesn't score them. The rule engine is their check, which keeps the core rule: the LLM never states a conclusion.
- **A conclusion follows its claims.** A criterion's templated conclusion sentence is emitted only if every claim for that criterion is KEPT. If any claim is FLAGGED or DROPPED, the paragraph has no conclusion sentence. Templated sentences count in the letter-level support rate (ADR-0020), so the letter metrics cover every sentence the patient reads.
- **Claim-to-criterion link, checked in code.** Beside the span check, a claim is DROPPED unless its `evidence_cite` (doc id and offsets) matches an asserted `Evidence` item whose `criterion_id` equals the claim's `criterion_id`. This catches the "wrong criterion" fault deterministically.
- **Verifier interface.** `verify/nli.py` defines one `Verifier` protocol, `score(claim, premise) -> float` in [0, 1]. The premise is the record quote extended only to complete its own sentence: from the start of the sentence the quote begins in to the end of the sentence it ends in, capped at 300 characters on each side, with no neighboring sentences. One function builds it, and the S1 labeler (ADR-0020) judges each claim against exactly this premise, so the verifier and its labels see the same text. The policy quote is **not** in the premise: a claim that restates the policy threshold would otherwise be "supported" by the policy text alone. The policy citation is checked by the span check and the criterion link, not by entailment. Two backends sit behind a config switch, like the LLM backend switch:
  - `bespoke-minicheck` on the lab server's Ollama (reached through the existing tunnel). The score is the probability of "Yes" from token log-probabilities.
  - A Gemini Flash judge on Vertex (thinking off) as the laptop fallback. It answers a plain "Yes" or "No" (not JSON), and its score is the "Yes" token probability from `responseLogprobs`. A self-reported confidence number is never used as a score.
  Every run logs drafter model, verifier backend, model tag and host (ADR-0011 rule).
- **Log-probabilities and score resolution are required.** A backend that returns only Yes/No can't be calibrated: one unsupported calibration claim scored 1.0 sets the threshold to 1.0 and every "Yes" claim gets flagged. T4 checks, for both backends, that log-probabilities come back, and measures score resolution: the share of distinct scores among Yes-scored dev claims, and the share tied at the top value. If MiniCheck on the lab server's Ollama (0.40.5) gives no log-probabilities, or its scores saturate so ties at the top would push q̂ to the maximum, Phase 3 stops at T4 and this ADR is amended.
- **Thresholds are keyed by (drafter model, verifier backend).** The conformal threshold (ADR-0020) is stored with the drafter model tag and the verifier backend and model tag. In Phase 3 one threshold is fit: **(gemma4:e4b, bespoke-minicheck)**.
  - The Gemini verifier backend gets **no threshold**. It can only FLAG or DROP, never KEEP. Gemini and Gemma are one model family, and the Gemini Flash labeler (ADR-0020) is the same model, so a Gemini threshold would have no independent validation.
  - If the running (drafter, verifier) pair has no fitted threshold, a claim that passed the span and link checks can still be shown, but it is labeled **"not evaluated"** in the UI and the logs. It never counts as KEPT in any metric.
  - The demo pair (gemma4:e2b-it-qat drafter) stays "not evaluated" until E2B-drafted dev claims are labeled and calibrated, which is the Phase 6 A4 row.
  - FLAGGED claims are removed from the letter text and listed separately for the patient or a helper to check (ADR-0020).
- **Span check first, never cut.** Deterministic, in `verify/span.py`: the record quote must equal `doc[char_start:char_end]` and the policy quote must appear verbatim in the criterion clause. No whitespace or case normalizing. A failure sets the claim to DROP with score 0 before the entailment model sees it. Dropped claims stay out of the conformal sets (ADR-0020).
- **Dependencies.** Add `scikit-learn`, and declare `scipy` explicitly (scikit-learn already depends on it, but the code imports it directly) because the Clopper-Pearson intervals in ADR-0019 and ADR-0020 use its beta quantile. `HistGradientBoostingClassifier` handles categorical features natively, so LightGBM isn't needed. Native categoricals allow at most 255 levels per feature; the IMR snapshot has 532 `DiagnosisSubCategory` and 498 `TreatmentSubCategory` levels (counted 2026-10-28), so T8 counts levels in the chosen training window and pools rare ones into "other" before fitting. Venn-Abers and split conformal are hand-rolled (about 30 to 60 lines each, unit-tested), so MAPIE and crepes aren't needed either. The hand-rolled Venn-Abers is checked against the `venn-abers` package in one test, added as a dev-only dependency.

## Consequences

**Easier:**
- Atomic claims are the kind the claim funnel study found checkable (spec §6.3). Each claim has one fact to support.
- No contract migration. Phase 1 contract tests stay valid.
- Two small runtime dependencies, and the calibration code is readable in the repo.
- A letter never says a requirement is met when one of its supporting claims failed.

**Harder:**
- Letters have more, shorter sentences, plus templated conclusion sentences. Wording must keep a paragraph readable (grade-8 target, Phase 4).
- Verifier quality numbers depend on the lab server being up.
- The live demo shows "not evaluated" claims until the Phase 6 A4 row calibrates the E2B pair. That is honest, but the demo letter carries no verifier guarantee before then.
- Without the policy text in the premise, MiniCheck judges only whether the record supports the fact, so a claim that states the fact correctly but applies it to the wrong rule is caught by the criterion link, not by entailment.
- Bespoke-MiniCheck-7B is licensed CC BY-NC 4.0. That is fine for research and the demo, and the README must say so.

## Alternatives Considered

1. **Claims with a list of record quotes:** rejected. It needs a contract change, and multi-fact claims are where support breaks.
2. **MiniCheck-7B on the laptop:** rejected. It would compete with the demo model for the GPU's share of memory.
3. **A small MiniCheck (Flan-T5-Large or RoBERTa-Large) on the laptop CPU,** which spec §6.4 names: not now. It is a different family from the drafter and gives real probabilities, but it adds `torch` and `transformers`. It is the preferred route for any future demo that KEEPs claims, through a new ADR, since the Gemini backend never will.
4. **A threshold for the Gemini backend:** rejected. It would be fit and validated with same-family labels, so its guarantee couldn't be checked.
5. **Policy quote in the premise:** rejected. It lets a restated threshold pass as supported.
6. **LightGBM / MAPIE / crepes:** not needed for 42,749 rows and two calibration methods. They can be added later through a new ADR.

## Notes

- Related: [ADR-0011](0011-llm-placement-lab-e4b-mac-e2b.md), [ADR-0012](0012-rule-evaluation-semantics.md), [ADR-0019](0019-strength-calibration-and-abstention.md), [ADR-0020](0020-claim-labels-and-conformal-split.md).
- Methods review findings applied: `data/audit/methods-review/adr-0018-0020.jsonl` #1 to #10.
- Plan: `.claude/plan/phase-3-trust-layer.md` T1 to T5.
