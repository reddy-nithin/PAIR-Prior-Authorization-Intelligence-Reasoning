# ADR-0021: Pilot-sized patient pools for the conformal claim sets

**Status:** Accepted (Nithin, 2026-10-28)
**Date:** 2026-10-28
**Supersedes:** (none; adds the data source that [ADR-0017](0017-disjoint-test-dev-patients.md) says needs its own ADR, and pre-registers how [ADR-0020](0020-claim-labels-and-conformal-split.md)'s minimum counts are met)

## Context

ADR-0020 needs at least 11 strict-unsupported dev claims to fit q̂ and at least 30 strict-unsupported test claims for the exit rule to say "pass". Its own count from the Phase 2 predicted verdicts shows about 2 wrong "met" criteria on `cases-dev-v4` and about 1 on `cases-v3`. Unless the letter wording often goes beyond its quote, both counts will fall short, and Phase 3 could never reach ✅.

ADR-0017 names the remedy: more Synthea patients in separate pools, through a new ADR because it changes the data source. This ADR is written before any Phase 3 claim is drafted, scored or labeled, so the sizing rule and the fallback can't be bent to fit the result.

## Decision

**Order of work.**
1. The labeler gate (ADR-0020) passes.
2. **Pilot, dev only.** Draft letters for the 30 `cases-dev-v4` cases with the (gemma4:e4b, bespoke-minicheck) pair, label every claim with S1, and measure:
   - C = claims (after span and criterion-link drops), U = strict-unsupported claims;
   - r̂ = U / C, the unsupported share per claim, with a 95% patient-level cluster-bootstrap interval over the 10 dev patients;
   - m = C / 30, claims per case (and C / 10, claims per patient).
3. Apply the sizing rule below and record every number in the tracker before anything else runs.
4. No test case (`cases-v3` or a new test pool) is drafted, scored or labeled before step 3 is done.

**Sizing rule.**
- Cautious rate: r_c = 0.75 × r̂. The interval's lower end isn't used for sizing: with few negatives spread over 10 patients it is usually 0, which would push every run over the cap. r̂'s cluster-bootstrap interval is still reported.
- Expected negatives per case: e = r_c × m. If U = 0, then e = 0 and the needed counts are infinite (over the cap).
- New dev cases: N_dev = ⌈max(0, 11 − U) / e⌉, at about 3 cases per new patient.
- New test cases: N_test = max(0, ⌈30 / e⌉ − 30), one case per new patient. The 30 existing `cases-v3` cases stay in the test side unchanged; new test cases are added to them.
- Cap: N_dev ≤ 60 (about 20 new patients) and N_test ≤ 120 (120 new patients).

**Within the cap: generate fresh pools.**
- One new Synthea run with a new seed, aged 65 or over, split into a new dev pool and a new test pool sorted by Synthea id. Both pools are disjoint from each other and from the existing 40 patients; a test fails on any shared Synthea id.
- New dev cases go to `data/cases-dev-p2`, new test cases to `data/cases-test-p2`, with the same generator, policy mix and A to D balance as the existing sets.
- Every new case gets the Python precheck (`pair audit precheck`). A random 20% (seeded, recorded) gets the critic case audit (ADR-0013, ADR-0020 gate). Blockers are fixed or the case is regenerated before the case enters a claim set.
- Then the dev side (`cases-dev-v4` + `cases-dev-p2`) is drafted and labeled, U is recounted, and q̂ is fit only if U ≥ 11 (ADR-0020). After that, the test side (`cases-v3` + `cases-test-p2`) is drafted, scored and labeled once.
- There is one expansion only. If a count still falls short after it, the ADR-0020 rule stands: the conformal row is "inconclusive" (or q̂ is not fit), and Phase 3 stays 🟡 on that row.

**Over the cap: accept "inconclusive" on stated terms.**
- If N_test > 120, no new test pool is generated. T11 accepts "inconclusive" on the conformal row as ✅ only with n, the leak-rate point estimate, the cluster-bootstrap interval and P(leak > 0.2) written up in `RESULTS.md`, plus a limitations paragraph saying the test set was too small to confirm the filter. Stating this now, before the pilot, is what makes that acceptance honest.
- If N_dev ≤ 60 but N_test > 120, the dev pool is still generated, because q̂ can't be fit without 11 dev negatives and the write-up above needs a fitted q̂.
- If N_dev > 60, no pools are generated and q̂ can't be fit. Phase 3 can be ✅ on the conformal row only if the upper end of r̂'s 95% patient-level cluster-bootstrap interval is at most 0.05. The write-up in `RESULTS.md` must then give U, C, and r̂ with its interval; state that the filter could not be calibrated because natural unsupported claims were too rare; and include a limitations paragraph. Claims ship as "not evaluated" (ADR-0018), with the measured support rate shown next to them. If the upper end is above 0.05, the conformal row stays 🟡.

## Consequences

**Easier:**
- Phase 3 has a pre-registered route to ✅ that doesn't depend on how many errors the drafter happens to make.
- The test set is sized from dev data only, so the test claims stay unseen until the threshold is frozen.

**Harder:**
- Up to 180 new cases: about $0.80 of Gemini generation at the Phase 2 rate, about 20 minutes of lab-GPU extraction, and about 36 critic case audits on Gemini Flash.
- The dev side mixes the 10 original dev patients (about 3 cases each) with new dev patients, and both sides cluster claims by patient. The cluster bootstrap resamples patients, which handles this, and the report gives patients and cases per side. The test side stays one case per patient (`cases-v3` and the new pool alike).
- A pilot r̂ from 10 patients is noisy. The cautious r_c makes the new pools larger than the point estimate suggests, on purpose.

## Alternatives Considered

1. **Add seeded unsupported claims:** rejected in ADR-0020. It breaks exchangeability.
2. **Loosen α or the exit rule after seeing the counts:** rejected. That is the result-driven change this ADR exists to prevent.
3. **Plan the pool sizes now from the Phase 2 counts:** rejected. Those count wrong verdicts, not unsupported claims; the drafter's own overclaims are unknown until the pilot.
4. **Grow `cases-v3` by more cases per existing test patient:** rejected. More claims per patient adds correlation, not independent patients.

## Notes

- Related: [ADR-0017](0017-disjoint-test-dev-patients.md), [ADR-0020](0020-claim-labels-and-conformal-split.md), [ADR-0013](0013-adversarial-critic-for-audits.md).
- Code touched when applied: `eval/synth/profiles.py` (`profile_pool` gains the new pools), `scripts/generate_cases.py`, `scripts/download_synthea.py` (seed and count).
- Plan: `.claude/plan/phase-3-trust-layer.md` T7b.
