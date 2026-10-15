# ADR-0007: Bayes-style strength score with an explanation panel

**Status:** Accepted
**Date:** 2026-10-15
**Supersedes:** (none). Resolves spec §15 open question #6.

## Context

The spec (§6.6) says the strength score combines the IMR base rate for a treatment category with checklist completeness, but it left the combination method open (§15 #6). There were two options: a simple Bayes-style adjustment, or a small learned model trained on synthetic cases. Patients also need to see how the number was built and what they can do to raise it. A bare probability gives them neither.

## Decision

- **Base rate:** LightGBM or logistic regression on pre-decision IMR features (diagnosis and treatment category and subcategory, IMR type, age range, gender, year). Time split: train on 2022 and earlier, calibrate on 2023, test on 2024 and later. Mondrian conformal or Venn-Abers gives each treatment category its own interval.
- **Combination:** convert the category base rate to odds, multiply by a documented shift for each checklist outcome (all met / insufficient / clearly unmet), then convert back to a probability with an interval. Shift sizes live in `score/adjustments.yaml` with a written rationale. They are labeled as assumptions.
- **Contract:**
  ```
  Strength{
    p, interval, abstain, abstain_reason,
    explanation: {
      base_rate, n_similar, imr_category,
      steps:   [{criterion_id, status, shift, why}],
      improve: [{criterion_id, action, p_if_fixed}]
    }
  }
  ```
- **What helps:** each insufficient item is re-scored as if met, giving `p_if_fixed`. Clearly unmet items get no "raise your odds" path. They get a pointer to ask the doctor about alternatives.
- **Abstain ("get a human", with SHIP links):** when the interval is too wide, or when a `critical` criterion is insufficient.
- **Honesty:** always show the range and the data source (California independent medical reviews of commercial plans, not Medicare). Never promise an outcome.

## Consequences

**Easier:**
- Every step from base rate to final estimate is inspectable and maps to a rule-trace entry.
- The "what helps" list falls out of the same math with no extra model.
- Unit tests can check the score math exactly.

**Harder:**
- Shift sizes are expert assumptions, not learned. Phase 6 must run a sensitivity analysis on them and report it.
- The interval comes from the base model only. The shifts move the point estimate and interval together and add no uncertainty of their own, which the UI copy and limitations section must state.

## Alternatives Considered

1. **Small learned model on synthetic cases:** rejected. The labels would come from our own planted evidence, so the model would learn our generator. 30 to 150 cases are also too few to fit it reliably.
2. **Show only the IMR base rate:** rejected. It ignores the patient's own checklist and gives no actionable guidance.
3. **LLM-estimated probability:** rejected. It breaks the core rule that the LLM reads but never decides, and it is not calibrated.

## Notes

- Spec §6.6 and §15 #6 updated to point here.
- Related: [ADR-0006](0006-patient-side-appeal-copilot.md).
