# Full case audit (critic plan Step 8)

Run 2026-10-27 on the cases regenerated under the ADR-0015 rules: 30 test cases (`data/cases-v2`, seed 2026) and 30 dev cases (`data/cases-dev-v2`, seed 2027). All 60 are synthetic. The mechanical precheck (`pair audit precheck`) found 0 problems in either set. Each case then got one fresh critic run (Claude Opus, `.claude/agents/pair-critic.md`, rubric [critic-rubric.md](critic-rubric.md)), with the LCD text written by `pair audit policy-text` from the MCD export. `pair.eval.critic.validate_output` checked every quote.

## Counts

| | Result |
|---|---|
| Cases audited | 60 of 60 |
| Verdict lines rejected (quote not verbatim) | 8. All 8 quoted the YAML `rule` expression under a `policy:<id>` doc id, which holds only the clause text |
| Cases with a blocker fail or blocker-level uncertain | 15 (7 test, 8 dev) |
| Distinct root causes behind the blockers | 6 case defects, 1 known limit, 3 near-leaks |

Non-pass verdicts by check and severity, after validation:

| Check | Blocker | Major | Minor |
|---|---|---|---|
| L1 criterion label | 9 | 0 | 0 |
| L2 overall label | 2 | 0 | 0 |
| L3 evidence span | 12 | 3 | 5 |
| K1 planted gap leaks | 7 | 1 | 0 |
| K2 unplanned conflict | 1 | 13 | 0 |
| D1 denial fields | 0 | 0 | 0 |
| D2 denial reason | 1 | 15 | 0 |
| R1 clinical realism | 0 | 26 | 2 |
| R2 internal arithmetic | 0 | 16 | 1 |
| R3 document form | 0 | 4 | 53 |

Several blocker lines come from the same case and root cause (one wrong label fails L1, L2 and L3 together), so the table counts lines, not defects.

## Blockers by root cause

Every claim below was checked against the case text. The affected-case lists come from the planted `states`, so they include cases the critics graded lower.

| # | Root cause | Cases | Gold now | Should be | Proposed outcome |
|---|---|---|---|---|---|
| B1 | Oxygen `ordered_and_evaluated: failing` dates an inpatient ABG that has no result. The value that qualifies comes from a separate, undated outpatient test, so time of need can't be shown to fail | test 07, 08; dev 07, 08 | unmet | insufficient | fixed: the planner puts the date and the qualifying value on the same test |
| B2 | PAP `ahi_threshold: vague` still states a number ("AHI of 18.5", "18 events per hour") | test 10; dev 05 | insufficient | met | fixed: the leak check rejects a numeric AHI or event rate when the state is vague |
| B3 | PAP `ahi_threshold: absent` calls the OSA "severe", which implies AHI 30 or more | test 05 | insufficient | leak | fixed: the leak check also rejects severity grades when the AHI is absent |
| B4 | PAP `ahi_threshold: negated` negates symptoms, but the Synthea profile has essential hypertension, a qualifying condition for AHI 5 to 14 in L33718 | dev 09 | insufficient | met | fixed: the planner checks profile conditions against the LCD's qualifying list |
| B5 | PAP `adherence: failing` uses a download that ends on day 39 or 51, so later 30-day windows in the first 3 months are untested | test 07; dev 07 | unmet | insufficient | fixed: the failing download covers the whole first 90 days |
| B6 | Facet `diagnostic_block_relief: conflicting` evidence span "one diagnostic block helped" is labeled as one block with 80% or more relief, which it doesn't say | dev 09 | span overstates | span states the value | fixed: the planted phrase states the relief percent |
| B7 | PAP face-to-face visit not stated as in person and no practitioner named, while the clause asks for both. The YAML checks dates only | dev 03 (fail); test 01 (uncertain) | met | met | accepted as a known limit: add the in-person face-to-face check to the README limits next to the re-evaluation one |

### Near-leaks (blocker-level uncertain)

| Case | Planted gap | Wording that nearly fills it | Proposed outcome |
|---|---|---|---|
| test home-oxygen-05 | `qualified_tester: absent` | "She was tested during this visit" reads as an in-office test. The test-set rescore scored this criterion met | fixed: the absent-tester prompt forbids saying where or when the test was done |
| test pap-osa-04 | `f2f_visit: absent` | an undated opening line, "presents for evaluation of obstructive sleep apnea" | fixed: the prompt forbids an undated pre-test evaluation line |
| dev facet-joint-05 | `no_untreated_radiculopathy: absent` | "Neurological examination of the lower extremities is completely intact" | fixed: add `neurolog\w* exam\w* .* intact` to the leak regex |

## Systemic major findings

These change no gold status, but they affect metrics or letters:

1. **Denial reason category (D2, 15 lines).** The templates for `criteria_not_met` use "The records do not show ..." wording, which PAIR's own parser prompt (`src/pair/ingest/denial.py`) defines as `insufficient_documentation`. This is the likely cause of the open `reason_category` 70% item. Fix the templates so `criteria_not_met` names the failed value and `insufficient_documentation` names the missing record.
2. **Denial names the wrong criterion.** test home-oxygen-06 is type B but the letter disputes the blood gas, which the record meets through Group II; the real gap is `home_benefit`. dev facet-joint-08 says no pain score is documented, but the record gives 2/10; the real reason is that 2/10 is below the moderate cut-off.
3. **PAP report arithmetic (R2/K2, about 12 cases).** "131 events over 6.2 hours" with "AHI 22.4" recurs across cases (131 / 6.2 = 21.1); "18 events over 6.8 h" with "AHI 3.1" gives 2.6. Two failing-AHI notes also say the test "meets the diagnostic criteria". The planner should derive events from AHI × hours.
4. **Note realism (R1/R3).** Most oxygen reports have no test date or device. The Group II CHF qualifier isn't in the profile in four oxygen cases. Several reports restate coverage wording ("meets the criteria for home oxygen therapy").

## Policy gaps raised (input to the next rule review, no case outcome)

- **home-oxygen:** the LCD NOTE on documenting measurement variation from age or reduced oxygen carrying capacity (anemia), the Group IV angina exclusion, and the "(awake)" qualifier for Group I are not modeled. The LCD has no tie-break between two resting oximetry readings, so the `conflicting` state is stricter than a reviewer might be.
- **pap-osa:** "objective evidence of adherence ... reviewed by the treating practitioner" is not modeled in `reevaluation`.
- **facet-joint:** both diagnostic blocks at the same level, CT or fluoroscopic guidance, a pain score after each block, and the "significant deformity" exclusion are not modeled.

## Method limits

- **Blind labeling was not enforced by file separation.** Each case is one JSON file, so most critics saw the gold fields in the same read as the notes. Every critic said it formed its labels from the notes and denial first, and the seeded-fault gate (2026-10-22) ran under the same conditions. A stricter design would hand the critic a notes-only copy first.
- **Critics grade the same defect differently.** test home-oxygen-07 has the B1 structure but its critic graded it major. Outcomes above are assigned per root cause, not per critic grade.
- **Source access.** Contractor pages were not fetched. Verdicts rest on LCD and NCD text from the MCD export.
- **Same-family critic on the v3 re-audit.** The v3 re-audit below ran on Gemini Flash, and the cases it judged were written by Gemini. ADR-0013 rejected a Gemini judge for exactly this reason; [ADR-0020](../decisions/0020-claim-labels-and-conformal-split.md) now allows it behind the seeded gate. The gate bounds the critic's errors only for the planted fault types, so errors Flash shares with the Gemini generator may go unflagged. Treat the v3 "all pass" result with that limit.

## Effect on the Phase 2 rescore

Some rescore misses were label errors, not extraction errors:

- test pap-osa-10 and dev pap-osa-05 `ahi_threshold`: the model said met, which B2 shows is right.
- test home-oxygen-05 `qualified_tester`: the model said met on the near-leak wording.

After the fixes, the affected cases are regenerated (the generator skips existing files, so only deleted cases are rewritten) and both sets are rescored.

## Re-audit after the fixes (v3 cases, 2026-10-28)

The 15 cases that had a blocker fail or uncertain were regenerated with the fixes (`data/cases-v3`, `data/cases-dev-v3`) and audited again. This run used Gemini Flash (high thinking) in Antigravity, which passed the seeded gate first: blocker faults 8/8, all faults 19/20 (missed one planted age mismatch), clean twins flagged 0/10.

- **Result:** 15/15 outputs valid (no rejected lines, no quote-less passes, every check present). Every verdict was pass.
- **Hand check of 7 cases:** B1 is fixed in test home-oxygen-08 and dev home-oxygen-07/08 (inpatient test 4 days before discharge, so the 2-day rule fails and `unmet` is right). The B2/B3 AHI labels in test pap-osa-10 (no number, "moderate OSA") and dev pap-osa-09 (AHI 8.8, sleepiness denied, snoring is not a qualifying symptom) follow the LCD. B5 is fixed in test pap-osa-05 (download covers the first 76 days and states the 30-consecutive-day result). Age and sex match the profile in all 15.
- **New finding:** test and dev used the same 30 patients slot for slot, so dev was not held out. Fixed by [ADR-0017](../decisions/0017-disjoint-test-dev-patients.md): dev is regenerated from patients the test set never uses (`data/cases-dev-v4`).
