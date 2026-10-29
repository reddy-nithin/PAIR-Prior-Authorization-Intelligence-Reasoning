# ADR-0020: Claim labels and the conformal calibration split

**Status:** Accepted (Nithin, 2026-10-28)
**Date:** 2026-10-28
**Supersedes:** Amends [ADR-0013](0013-adversarial-critic-for-audits.md): the critic may run on Gemini Flash (high thinking) once it passes the seeded gate, which reverses ADR-0013's "Gemini as the judge: rejected." Supersedes the spec §6.5 sentence "kept claims are wrong at most α of the time" (a precision-type promise) with the leak-rate guarantee below; the spec sentence is updated to match. Also settles how spec §6.5 splits claims.

## Context

Split conformal filtering (spec §6.5) needs claims labeled as supported or not, split into calibration and test sets that are exchangeable but separate. ADR-0013 makes claim labels a critic job (rubric check S1). It chose a Claude critic and rejected Gemini because Gemini wrote the cases.

Since then the critic moved to Gemini Flash (high thinking) in Antigravity. Flash passed the seeded case gate on 2026-10-28 (critic-only score: 8/8 blockers, 19/20 faults, 0/10 clean-twin false flags), and the v3 case re-audit ran on it. That change was never recorded in an ADR. For claim labels the same-family concern is stronger than for case audits: the claims are worded by Gemma 4 E4B, and the record text they quote was written by Gemini.

Spec §6.5 promised "kept claims are wrong at most α of the time", a precision-type guarantee. Mohri & Hashimoto's "the whole kept letter is supported" is a letter-level guarantee. Both need different calibration units, and neither fits the data available (see Alternatives). ADR-0017 gives disjoint test and dev patients.

**Expected sample size (#30, counted 2026-10-28 from Phase 2 predicted verdicts, `eval-core-20261028-121617` dev and `-121258` test).** Dev `cases-dev-v4`: 102 predicted-met criteria, at most 269 rule variables behind them, so about 100 to 270 claims. Only 2 of the 102 are gold-not-met (5 rule variables). Test `cases-v3`: 101 predicted-met criteria, at most 272 rule variables, 1 gold-not-met. Unsupported claims will come from these few extraction errors plus any wording that goes beyond its quote, so natural negatives are likely scarce on both sides.

## Decision

- **The critic on Gemini Flash is allowed, behind gates.** For case audits, the existing seeded gate stands. For claim labels, the seeded-claim gate below must pass first. ADR-0013's wording rule still applies, with the model named: "source-verified by an adversarial critic (Gemini Flash, N% seeded-fault catch rate), signed off by the author." The v3 case re-audit that Flash ran on Gemini-written cases carries a same-family limit, listed in `docs/audit/case-audit-summary.md`.
- **Claims come from the real pipeline.** Letters are drafted from *predicted* evidence (steps 1 to 4 as run, not gold) by the (gemma4:e4b, bespoke-minicheck) pair (ADR-0018), so extraction mistakes produce real unsupported claims. Only these natural claims go into the conformal sets. Claims the span check or the criterion link dropped (ADR-0018) are left out.
- **Split by patient.** Calibration: claims from `cases-dev-v4` (10 dev patients), plus `cases-dev-p2` when ADR-0021 generates it. Test: claims from `cases-v3` (30 test patients), plus `cases-test-p2` when ADR-0021 generates it. No case or patient is in both. Disjoint is not the same as exchangeable, so before the sets are called exchangeable, the report compares their policy, criterion and claim-type mix and the verifier-score distributions of their unsupported claims.
- **The guarantee.** Claim-level split conformal on unsupported claims. q̂ is the k-th smallest verifier score among the n unsupported calibration claims, with k = ⌈(n+1)(1−α)⌉ and α = 0.1. A claim is KEPT only if its score is strictly above q̂, and FLAGGED otherwise. In plain words: **on average over calibration sets, a new unsupported claim gets through the filter at most 10% of the time.** This is a limit on how many bad claims get through. It doesn't promise that 90% of kept claims are supported, so that number (precision of kept claims) is reported separately as a description, not a guarantee.
- **A bound for the threshold actually fitted.** The average guarantee hides spread: for one fitted q̂, the realized leak rate can be well above 10%. Every report also gives the training-conditional bound P(leak > 0.2) = P(Binomial(n, 0.2) ≤ n − k) for the realized n, which must be at most 0.1. At n = 11, k = 11, it is 0.8^11 ≈ 0.086.
- **Minimum negatives, counted before q̂ is fit.** After the dev claims are labeled, count the strict unsupported ones before fitting q̂. At α = 0.1 a finite q̂ needs n ≥ 9, and the 0.2 bound above needs n ≥ 11. **If n < 11, stop: q̂ is not fit or frozen.** [ADR-0021](0021-pilot-sized-patient-pools.md), written before any Phase 3 claim exists, sizes fresh dev and test pools from a dev-only pilot (ADR-0017's remedy) and says what happens if the needed pools exceed its cap. The first-pass count is always reported. Seeded claims are never added, α is never loosened, existing test cases are never changed or dropped, and no test claim is drafted, scored or labeled before the ADR-0021 pilot and sizing are done.
- **What the patient sees.** FLAGGED claims are removed from the letter text and listed separately, as "statements PAIR couldn't confirm", for the patient or a helper to check. Their criterion loses its templated conclusion sentence (ADR-0018). So the leak guarantee is about the letter that gets sent. A claim from a (drafter, verifier) pair with no fitted threshold is shown as "not evaluated" and is never counted as KEPT (ADR-0018).
- **Labels.** Each claim gets three layers:
  1. Python: the span check and criterion link (ADR-0018), and whether the record quote overlaps a gold span for that criterion. A claim where this disagrees with S1 (gold overlap but `unsupported`, or no overlap but `supported`) goes into Nithin's review queue.
  2. Critic S1 on Gemini Flash (high): `supported`, `partly` or `unsupported`, with quotes, judged against exactly the verifier's premise (the record quote completed to its own sentence, ADR-0018), built by the same function. A verdict without a valid quote is re-run once. If it still has none, the claim is left out of the main numbers and its count is reported. A worst-case leak rate that counts every unlabeled test claim as unsupported (leaked if it was kept) is reported next to the main one, since hard, ambiguous claims are the likeliest to stay unlabeled.
  3. Nithin checks a stratified sample: a random 10%, plus every claim in the disagreement queue, plus extra `unsupported` and `partly` claims until at least 20 of them are checked. He reports percent agreement, per-class agreement, Cohen's kappa with a bootstrap 95% interval, and Gwet's AC1 (which, unlike kappa, stays stable under heavy class imbalance). If kappa is below 0.7, the labels don't count until the rubric is fixed and the claims are relabeled.
  Strict support = S1 `supported`. Lenient = `supported` or `partly`. Conformal uses strict.
- **Labeler gate first.** Before labeling, a seeded-claim set checks the critic: **at least 30 faults** (number swap, overclaim beyond the quote, wrong criterion, negation flip) and **at least 30 clean twins**, plus at least 20 natural dev-pipeline claims that Nithin labels himself. The bar: catch at least 90% of faults and flag at most 10% of clean twins (ADR-0013's), and agree with Nithin on at least 80% of the natural claims. Missing any of the three fails the gate. Even then the gate bounds the critic's errors only for seeded faults; subtle errors a same-family critic shares with the generator aren't sampled by it. If Flash fails, labels move to a Claude critic, and this ADR is amended.
- **Seeded claims never enter the conformal sets.** They are used only for the gate and for a verifier sensitivity table.
- **Always report**, each rate with n, a patient-level cluster-bootstrap 95% interval (resampling all test patients, from `cases-v3` and `cases-test-p2` when generated), and the Clopper-Pearson interval labeled **naive** (it assumes independent claims, which they aren't):
  1. the leak rate: the share of strict-unsupported test claims that were KEPT, against α = 0.1;
  2. the **empty-letter rate**: letters left with no KEPT claim (named so it isn't confused with ADR-0019's strength-score abstention);
  3. the **support rate among non-empty letters**: the share of letters with at least one KEPT claim whose KEPT claims and templated sentences are all strictly supported. A templated sentence counts as supported when its criterion is gold-met for that case;
  4. the precision of KEPT claims (descriptive).
- **Exit rule, pre-registered.** The minimum is **30 strict-unsupported test claims**. The conformal check **passes only if all three hold**:
  1. n ≥ 30 unsupported test claims;
  2. the leak-rate point estimate is at most 0.15;
  3. the upper end of its patient-level cluster-bootstrap 95% interval is at most 0.30.
  Anything else is **"inconclusive"**, never "pass". The report gives n, the point estimate, the bootstrap interval and the naive Clopper-Pearson interval. No ±3-point band is used. When ADR-0021's pools would exceed its cap, its pre-stated terms decide whether "inconclusive" is accepted at T11.

## Consequences

**Easier:**
- Calibration and test differ by patient, without twin leakage, and the exchangeability check is reported rather than assumed.
- The guarantee is stated in one sentence with its unit and its averaging, plus a bound for the threshold actually used.
- The exit rule has power: a 25% leak rate on 20 claims can't pass.
- The critic's model change is now on record, and the labeler's same-family risk is bounded for seeded faults before its labels count.

**Harder:**
- **Negatives are scarce (see Context).** Dev has about 2 criteria with a wrong "met" (5 facts), test about 1. Unless the drafter's wording overclaims often, the dev count is likely to fall below 11 and the test count below 30. ADR-0021 handles both with pilot-sized pools, decided before any numbers exist.
- Claims cluster by patient, so the bootstrap intervals are wide with 30 test patients, and the naive intervals look better than they are. Both are shown.
- The leak-rate guarantee says nothing about how many good claims get flagged. A high empty-letter rate is possible even when the guarantee holds, which is why it is always shown with the leak rate.
- Gemini labels cost a little (logged per batch). Nithin's review grows with the disagreement queue and the stratified sample.
- **The guarantee is relative to the labels.** "At most 10% of unsupported claims get through" is measured against critic S1 labels, not ground truth. Critic mistakes pass straight into the leak rate, so every report says "relative to critic labels" and gives the spot-check kappa and AC1 next to it.
- **The guarantee is approximate under clustering.** Split conformal assumes exchangeable claims. Claims from the same patient share wording and evidence, so they are correlated. A strict fix would calibrate per patient, but 10 dev patients is too few for a threshold. The claim-level guarantee is reported as approximate, and the limitations section says why.

## Alternatives Considered

1. **Letter-level guarantee (Mohri & Hashimoto: the whole kept letter is supported):** rejected for now. The calibration unit becomes the letter, about 30 dev letters, which is too few for a useful threshold. It can be reported as a secondary number.
2. **Controlling the share of kept claims that are wrong (conformal risk control, the spec's original promise):** rejected for now. It needs more labeled claims than the dev set gives. The precision of kept claims is reported descriptively instead.
3. **Mix seeded negatives into calibration:** rejected. It breaks exchangeability with real letters and makes the leak rate meaningless.
4. **Split by claim:** rejected. Claims from one case share wording and evidence, so it leaks.
5. **Pass if the leak rate's interval reaches 0.1:** rejected. At realistic n it passes a 25% leak rate (5 of 20 gives about [0.09, 0.49]).
6. **Claude critic for labels from the start:** kept as the fallback if the gate fails. It is a different family, but it costs Claude usage and needs Opus to be reliable.

## Notes

- **Clarification, 2026-10-29 (Nithin), made after seeing the numbers.** The kappa ≥ 0.7 rule is computed on the binary split calibration uses (supported vs partly or unsupported), not on the three classes. This ADR didn't say which, and the choice was made after the first spot check: three-class kappa 0.55 [0.39, 0.71] failed, binary kappa 0.80 passed (86 claims, 84% three-class and 93% binary agreement, AC1 0.80 and 0.92). Reason: S1 labels enter calibration and every reported rate only as supported or not, and most three-class disagreements were unsupported versus partly, which calibration treats the same. Because the rule was settled after the result, every report gives both kappas and both AC1 values.
- Related: [ADR-0013](0013-adversarial-critic-for-audits.md), [ADR-0017](0017-disjoint-test-dev-patients.md), [ADR-0018](0018-phase-3-verifier-and-dependencies.md), [ADR-0021](0021-pilot-sized-patient-pools.md).
- Gate evidence: `docs/audit/case-audit-summary.md` and the 2026-10-28 tracker log.
- Methods review findings applied: `data/audit/methods-review/adr-0018-0020.jsonl` #19 to #31; #19 and #28 with Nithin's stricter rules (2026-10-28).
- Plan: `.claude/plan/phase-3-trust-layer.md` T5 to T7, T11.
