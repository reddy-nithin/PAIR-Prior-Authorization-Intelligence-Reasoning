# ADR-0013: Adversarial critic for audits, with source-backed verdicts

**Status:** Accepted. Amended by [ADR-0020](0020-claim-labels-and-conformal-split.md): the critic may run on Gemini Flash once it passes the seeded gate, which reverses Alternative 3 below.
**Date:** 2026-10-22
**Supersedes:** (none; changes how spec §8.1 audits are done)

## Context

Several open checks need a medical reader: the synthetic case audit (realism, labels, leaks, denial match), three policy rule interpretations (the facet "moderate" pain cut-off, the PAP event-count minimums, the PAP 31st-to-91st-day window), and, in Phase 3, a few hundred claim labels. They were waiting on a clinician or the mentor. Dr. Uddin is a computer science professor, so medical judgment is outside his role. No clinician is on the project.

## Decision

**An adversarial critic does the audits, and Nithin signs off.**
- **Mechanical checks** run in tested Python (`pair audit precheck`): planted phrases, regex leaks, exact span offsets, gold labels reproduced by the rule engine, clause text found verbatim in the MCD export, and the denial letter matching `gold_denial`.
- **Judgment checks** run in a Claude Code critic agent, using the rubric in [docs/audit/critic-rubric.md](../audit/critic-rubric.md). The cases were written by Gemini, so a different model family judges them.
- **Every critic verdict quotes its evidence**: a case span, a policy clause, or a cited source with its URL. A pass without a quote counts as a fail.
- **The critic must be tested before its verdicts count.** On a seeded-fault set with clean twins, it must catch at least 90% of blocker faults and flag at most 10% of clean cases with a blocker.
- **Nithin signs off** by checking the critic's logic and quotes, not the medicine. Every blocker ends as fixed, rejected with a reason, or accepted as a known limit.
- **Dr. Uddin's role is mentor.** He can review methods, code and evaluation design, not medical content.

**Wording rule.** Write "source-verified by an adversarial critic (N% seeded-fault catch rate), signed off by the author." Never write "clinician-validated" or "expert-reviewed," in the README, the deck or the paper.

**Scope.** The case audit, the rule review, and Phase 3 claim labels (the critic's S check). The Phase 5 50-claim human audit stays human. Nithin does it, and it measures agreement with the critic (percent agreement and Cohen's kappa).

## Consequences

**Easier:**
- Audits stop waiting on someone outside the project and can cover all 60 cases instead of 6.
- Each verdict is traceable to a quote, so a reader can check it.

**Harder:**
- The critic is still a language model, so it can share blind spots with the generator. The seeded-fault score bounds this risk, but it doesn't remove it.
- The project can't claim clinical validation. A clinician spot check stays an optional upgrade.

## Alternatives Considered

1. **Wait for a clinician**: rejected for now. No clinician is on the project, and every audit would stay blocked.
2. **Critic agent only, no Python checks**: rejected. Exact checks belong in tested code, and the agent should spend its judgment where code can't.
3. **Gemini as the judge**: rejected. It is the same model family that wrote the cases.

## Notes

- Research basis: [docs/audit/critic-research.md](../audit/critic-research.md).
- Related: [ADR-0012](0012-rule-evaluation-semantics.md) (day counting under review).
