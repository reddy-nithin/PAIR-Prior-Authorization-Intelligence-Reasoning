# ADR-0019: Strength score calibration, IMR drift and abstention

**Status:** Accepted (Nithin, 2026-10-28)
**Date:** 2026-10-28
**Supersedes:** (none; fills in the method choices that ADR-0007 left as "or", and narrows its abstention rule to the criteria that apply)

## Context

ADR-0007 fixed the shape of the strength score: an IMR base rate, Bayes-style odds shifts per checklist outcome, an explanation, and abstention. It left these choices open:

- "LightGBM or logistic regression", and "Mondrian conformal or Venn-Abers".
- How to handle drift. The IMR overturn rate rises from 0.45 (2010) to 0.72 (2025), so a model trained on 2022 and earlier will under-predict 2024+.
- How abstention treats an any-of group. Home-oxygen `group1_blood_gas or group2_blood_gas` are alternatives, so neither is marked `critical`, and the critical-only rule would never abstain when both are missing.

Two more problems turned up in review:

- **Criteria off the active branch.** `run_rules` gives every criterion a status whatever the context flags say (`src/pair/rules/engine.py`), and a criterion with no evidence is `insufficient`. PAP `adherence` (critical) only applies when `initial` is false. Facet `diagnostic_block_relief` (critical) only applies when `diagnostic_only` is false. Read literally, ADR-0007's rule would abstain on every initial PAP case and every diagnostic-only facet case. The same criteria would also get an "insufficient" odds shift, an improve entry and a gap.
- **Thin calibration data for our policies.** The 2023 calibration year has 2,246 rows in all, but only 5 (PAP), 3 (home oxygen) and 23 (facet) in the policy groups from `policies/_imr-mapping.yaml`. The 2024+ test slices are 6, 8 and 28 rows. A calibrator fit on all categories gives a narrow Venn-Abers range, so a width rule alone would almost never abstain, even for home oxygen.

## Decision

- **Model.** Fit both logistic regression (one-hot categories) and `HistGradientBoostingClassifier` (native categoricals) on all IMR categories, not only the three policies. Pick the one with the lower Brier score on the 2023 calibration year.
- **Training window, chosen on 2023 only.** Candidates: all years up to 2022, 2016 to 2022, and all years up to 2022 with recency weights. The winner is the lowest 2023 Brier score. The 2024+ test years are scored once, after the choice is frozen. Model and window selection reuse the 2023 rows that the calibrators are then fit on. With 6 candidates and 2,246 rows the effect is small, and the README says so.
- **Category.** The Mondrian category is the IMR `TreatmentCategory`. Categories with fewer than 30 rows in 2023 are pooled into one "other" category for calibration.
- **Shown interval: inductive Venn-Abers.** It is fit on 2023 per category and gives `[p0, p1]` for each prediction. The point estimate is `p = p1 / (1 - p0 + p1)`. The range reflects how much calibration data there is, not the uncertainty of this case's own probability (Vovk and Petej 2014), so it is never called a probability interval or a confidence interval. Venn-Abers validity also assumes 2023 and 2024+ are exchangeable, which drift breaks, so T8 reports Venn-Abers calibration on 2024+ (Brier score and a reliability table, overall and per policy group).
- **Width floor for thin policy groups.** For a case in one of our policy groups, the shown interval is never narrower than a 90% Wilson interval on that group's own overturn rate, counted over the chosen training window plus 2023. If the Venn-Abers range is narrower, it is widened around `p` to the Wilson width. When the widened window would cross 0 or 1, it slides inside [0, 1] instead of being clipped, so the floor width is always met. The explanation says the range was widened because few similar cases exist, and gives `n_similar`. This is how a thin group like home oxygen reaches the `max_width` rule, as `_imr-mapping.yaml` expects.
- **Validity number: Mondrian conformal prediction sets at 90%.** Per category, on the same 2023 calibration scores. On 2024+ report overall coverage with a 95% Clopper-Pearson interval, and coverage per policy group with its row count and Clopper-Pearson interval, labeled **descriptive only**: the Mondrian taxonomy is `TreatmentCategory`, and a policy group is a subcategory filter inside it, so per-group coverage has no guarantee even under exchangeability. Also report the share of sets that are `{0,1}`, singletons and empty. Mostly-`{0,1}` sets give high coverage but no information, so the set-size shares are always shown next to coverage. Drift means 2023 and 2024+ aren't exchangeable, so a coverage miss is reported and explained, not hidden.
- **Odds shifts.** `score/adjustments.yaml` holds one multiplier per outcome (met, insufficient, unmet), each with a written rationale, labeled as assumptions. The interval ends move with `p` by the same odds shift (ADR-0007: the shifts add no uncertainty of their own). Because an odds shift narrows an interval as `p` moves toward 0 or 1 (for example [0.40, 0.66] times odds 3 gives [0.67, 0.85], width 0.26 to 0.19), the width test below uses the **unshifted** base interval, so assumed shifts can never make the score look more certain.
- **Active criteria.** A new `active_criteria(checklist, context)` in `rules/` returns the criteria whose status can still change the overall result once the context flags are bound. It uses `parse_rule` from `rules/expressions.py`: a criterion inside an `and` or `or` that a context flag has already decided is inactive. Odds shifts, the improve list and the abstention rules below use active criteria only. The rule engine's gap list stays complete, so the `Verdict` contract and its validator (a gap for every non-met criterion) don't change; inactive gaps are filtered downstream, in the strength explanation and the UI. Inactive criteria stay in the rule trace, marked "doesn't apply" in the UI.
- **Context flags carry their source.** `initial` and `diagnostic_only` come from upstream parsing, so one wrong flag could silently remove a critical criterion. Each flag passed to `active_criteria` must cite where it came from: a record or denial span, or explicit user input. A flag that is missing or has no source is **Unknown**, and Unknown keeps both branches active, so critical gaps on either branch still abstain. T9 tests the wrong-flag and missing-flag cases.
- **Abstention ("get a human", with SHIP links from `policies/_ship.yaml`).** Abstain if any of these is true:
  1. the unshifted base interval (after the Wilson floor) is wider than `max_width = 0.20` in `adjustments.yaml`;
  2. an active `critical` criterion is insufficient;
  3. an active **any-of group** has no met member and at least one insufficient member.
  An any-of group is an `or` node in the checklist `logic` whose operands are all bare criterion ids. Today only home-oxygen's `group1_blood_gas or group2_blood_gas` qualifies. PAP's `initial or (...)` and facet's `diagnostic_only or ...` involve context flags, so they are handled by active criteria instead. No YAML or contract change.
- **`max_width` is fixed now, at 0.20,** before any 2024+ scoring: a range wider than 20 points (say 40% to 60%) is too vague to act on. For reference, the 90% Wilson floor widths (counted 2026-10-28) are PAP 0.149, home oxygen 0.196, facet 0.153 with all years up to 2023, and 0.185, 0.296, 0.169 with 2016 to 2023. So whether home oxygen abstains on width alone depends on the window T8 picks. The value 0.20 was set after seeing these widths, which use training years and 2023 only; no 2024+ test data was looked at. T8 reports the resulting abstention rate per policy group on 2023 before 2024+ is touched.
- **What rule 1 means in practice.** For our policy groups the Wilson floor sets the width, so rule 1 effectively means "abstain when the policy group has too few similar past cases". It is not a statement about the model's uncertainty for this patient, and the UI copy says it that way (for example, "Too few similar past reviews to give a useful range").
- **Population gap, stated everywhere.** Every validity number here (Mondrian coverage, Venn-Abers calibration, the Wilson floor) is measured on California independent medical reviews of commercial plans. The ADR, the README and the UI copy say that coverage is measured on IMR outcomes and is not a guarantee for Medicare Advantage appeals.

## Consequences

**Easier:**
- Drift is handled by the calibration year, the setup ADR-0007 already planned for, and the window choice can't peek at the test years.
- Initial PAP and diagnostic-only facet cases are scored on the criteria that apply to them, so they don't abstain or lose odds over requirements they don't have.
- The any-of rule closes the Phase 1 tracker item without new policy fields.
- Thin policy groups show a range that admits how little data there is, and can abstain, instead of borrowing the narrow all-category range without saying so. The range is about IMR outcomes, not Medicare Advantage, and the copy says so.
- Both interval methods are small, hand-rolled and unit-tested (ADR-0018).

**Harder:**
- Two calibration views (Venn-Abers for display, Mondrian sets for validity) need one sentence in the README so nobody reads the shown range as a 90% interval.
- The Wilson width floor is our own rule, not part of Venn-Abers. The README and the explanation must label it.
- Home oxygen will often abstain, by design. Facet and PAP depend on how many rows fall inside the chosen window.
- `active_criteria` is a new function beside the engine; the engine's gap list and the `Verdict` contract are unchanged. Strength and UI tests need cases for `initial=true`, `diagnostic_only=true`, and an Unknown flag.
- Shift sizes are still assumptions. Phase 6 runs the sensitivity analysis.

## Alternatives Considered

1. **Train on 2010 to 2022 only, no window choice:** rejected. With the drift above, it under-predicts recent years, and the calibration step would have to absorb all of it.
2. **Per-category binomial interval on the raw rate as the shown interval:** rejected. It ignores the other features and fails under drift. It is used only as a width floor.
3. **Abstain whenever a policy group has fewer than 30 calibration rows:** rejected. All three policies would always abstain, and the score would never show.
4. **A "not applicable" criterion status in the `Verdict` contract:** rejected for now. It is a contract change, and computing active criteria from `logic` and context gives the same result.
5. **Abstain whenever the overall verdict is insufficient:** rejected. Most fixable-gap cases would abstain, and the "what helps" panel would rarely show.

## Notes

- Related: [ADR-0007](0007-bayes-strength-score-with-explanation.md), [ADR-0008](0008-rule-expression-language.md), [ADR-0018](0018-phase-3-verifier-and-dependencies.md).
- Row counts: IMR snapshot of 2026-10-15 (42,749 rows), filtered with `policies/_imr-mapping.yaml`, counted 2026-10-28.
- Methods review findings applied: `data/audit/methods-review/adr-0018-0020.jsonl` #11 to #18.
- Plan: `.claude/plan/phase-3-trust-layer.md` T8, T9.
