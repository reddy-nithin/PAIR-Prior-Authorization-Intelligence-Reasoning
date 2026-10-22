# Seeded-fault test of the audit critic (ADR-0013, critic plan Step 6)

Run 2026-10-22. Seed 2026: 20 faults planted in copies of the 30 synthetic test cases, plus 10 clean twins (unmodified copies of faulted bases), shuffled and renamed `seed-01` to `seed-30`. The key is stored apart from the cases, and the critic never read it. There was one critic run per case, each in a fresh context, with Claude Opus as the critic (`.claude/agents/pair-critic.md`). Scores are from `pair audit score`. The raw table is in `RESULTS.md` (section `audit-critic`).

## Raw score (automatic)

| Metric | Target | Result |
|---|---|---|
| Blocker faults caught | ≥90% | 8/8 (100%) |
| All faults caught | report | 20/20 (100%) |
| Clean twins with a blocker flag | ≤10% | 4/10 (40%) ❌ |
| Critic lines rejected (non-verbatim quote, bad JSON) | report | 0 |
| Quote-less passes | report | 0 |

**Catches were for the right reason.** For every faulted case, the matching fail verdict's reasoning names the planted change: the 45% and 35% relief spans, the L2 compression deformity, the "[plan: ...]" echo, the 106% SpO2, the 56-vs-67 age, and so on. No catch depended on an unrelated failure that happened to share a check id.

## Adjudication of the 4 flagged clean twins

The clean twins are unmodified copies of real test cases, so a blocker on one is either a critic error or a real defect in that case. Each claim was checked against the case text and the LCD.

| Seed | Base case | Critic's blocker | Check | Ruling |
|---|---|---|---|---|
| seed-10 | facet-joint-04 | Radiculopathy unit is `absent`, but the note says "There is no associated weakness or numbness" and "Neurological exam is grossly intact" | Text confirmed in the case | **Real defect** (leak the generator's regex missed) |
| seed-06 | home-oxygen-07 | The planted `failing` time-of-need phrase ("this test was done 6 weeks after recovery, when stable") doesn't fail L33797. For a prescription not from an inpatient stay, "the time of need is during the period when the treating practitioner notes signs and symptoms of illness that can be relieved by oxygen" | LCD text confirmed in `data/audit/lcd/home-oxygen.txt` | **Real defect** (the planner state means the opposite of its label) |
| seed-02 | home-oxygen-10 | The planted blood-gas `conflicting` state pairs "93% on room air" taken "while short of breath" with "SpO2 87%" taken "at rest on room air". These are different conditions, so the at-rest value stands and the conflict is weak | Text confirmed in the case | **Real defect** (the planner's conflict isn't a true conflict) |
| seed-18 | home-oxygen-03 | Group I with SpO2 89% and no PaO2: the critic says unmet, but ADR-0012's three-valued logic says insufficient (the PaO2 route is untested) | Rule-meaning disagreement | **Critic disagrees with the documented semantics.** Counted as a false alarm. Goes to the Step 7 rule review |

**Adjudicated false-blocker rate: 1/10 (10%), which meets the ≤10% target.** Nithin signs off on this adjudication.

## What the test already found in the real cases
These go into the full audit (Step 8) and the rule review (Step 7).

1. **home-oxygen planner, `ordered_and_evaluated: failing`:** the phrase doesn't violate L33797 (seed-06, seed-13, seed-19). Every case built with this state probably has a wrong gold label.
2. **home-oxygen planner, `blood_gas: conflicting`:** the two readings are taken under different conditions (seed-02, seed-08).
3. **Group I semantics:** SpO2 89% with no PaO2 comes out insufficient (ours) or unmet (reviewer view). Six critic runs raised it.
4. **facet-joint radiculopathy `absent`:** the note negates radiculopathy in words the leak regex doesn't catch (facet-joint-04).
5. **pap-osa-08:** the gold `ahi` span "AHI 3.1 events/hour" sits in the CPAP-download context, where it reads as a residual on-therapy AHI. The LCD defines AHI as measured "without the use of a positive airway pressure device" (seed-27).
6. **Realism (R1/R3, major and minor):**
   - facet notes carry no dates
   - several facet reports describe the RFA as already done while the letter denies a prior authorization for it
   - several sleep reports have no recording or sleep time
   - one note describes a female patient as "He" (pap-osa-04)
   - Synthea condition lists name several CKD stages at once
7. **Policy scope gaps raised in rule mode:**
   - neurogenic claudication isn't modeled (facet)
   - the LCD's "sustained" relief and "duration consistent with the agent used" aren't modeled
   - the "same pain scale" footnote isn't modeled
