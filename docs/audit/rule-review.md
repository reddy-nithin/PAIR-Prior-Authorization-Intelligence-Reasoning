# Rule review (critic plan Step 7)

Run 2026-10-23. The audit critic ([ADR-0013](../decisions/0013-adversarial-critic-for-audits.md)) reviewed five rule questions in rule mode, one fresh Claude Opus subagent per question, using [critic-agent.md](critic-agent.md) and the P1 to P3 checks in [critic-rubric.md](critic-rubric.md). Each critic quoted the LCD text written by `pair audit policy-text` from the MCD export of 2026-10-23. `pair.eval.critic.validate_output` accepted all 28 verdict lines: 0 non-verbatim quotes, 0 quote-less passes. The rule changes are in [ADR-0015](../decisions/0015-rule-review-changes.md).

| # | Question | Criterion | Critic verdict | Applied |
|---|---|---|---|---|
| 1 | PAP event counts | `pap-osa.ahi_threshold` | change | change |
| 2 | PAP re-evaluation window | `pap-osa.reevaluation` | keep (day 1) | keep, documented |
| 3 | Facet "moderate" pain | `facet-joint.pain_and_function` | change | change |
| 4 | Oxygen time of need | `home-oxygen.ordered_and_evaluated` | change | change |
| 5a | Neurogenic claudication | `facet-joint.no_untreated_radiculopathy` | change | change |
| 5b | Sustained relief | `facet-joint.diagnostic_block_relief` | change | change |
| 5c | Same pain scale, baseline disability scale | `facet-joint.pain_and_function` | split: limit + change | limit + **uncertain** (open question) |

**Source limits in this run.** The critics' direct fetches of contractor pages failed: Noridian and CGS were blocked or failed DNS from the subagents. Contractor guidance below is cited from [critic-research.md](critic-research.md) §1 and §2, or from search summaries, and is marked as such. Every verdict rests on the LCD or NCD text, which was read from the MCD export.

## 1. PAP event counts: change

- **LCD L33718 v52** (https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid=33718&ver=52), definitions: "If the AHI or RDI is calculated based on less than 2 hours of sleep or recording time, the total number of recorded events used to calculate the AHI or RDI (respectively) must be at least the number of events that would have been required in a 2 hour period (i.e., must reach ≥30 events without symptoms or ≥10 events with symptoms)."
- **NCD 240.4 v3** (https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid=226&ncdver=3) says the same in terms of "less than 2 hours of continuous recorded sleep".
- **Contractor:** Noridian's PAP documentation checklist lists the minimum counts alongside the AHI (critic-research.md §1; not re-fetched).
- **Finding (P2 blocker, P1 major):** the old rule demanded `event_count` on every test, so a full-night study reporting only its AHI came out insufficient. Over 2 hours or more, an AHI at the threshold already implies the count (15 × 2 = 30, 5 × 2 = 10). The qualifier sits in the definitions, outside the YAML clause.
- **New rule:** `(ahi >= 15 and (sleep_or_recording_hours >= 2 or event_count >= 30)) or (5 <= ahi <= 14 and (sleep_or_recording_hours >= 2 or event_count >= 10) and len(symptoms_or_conditions) > 0)`
- **Boundary tests:** `tests/policies/test_real_policies.py::test_pap_event_minimum_applies_only_under_two_hours` covers 2.0 hours, 1.5 hours with 29/30 and 9/10 events, missing hours, and AHI 14.5.

## 2. PAP re-evaluation window: keep (day 1), now documented

- **LCD L33718 v52** (URL above): "no sooner than the 31st day but no later than the 91st day after initiating therapy"
- **Contractors:** Noridian's checklist and its 2016 policy reminder, and the CGS physician guide, repeat "31st to 91st day" without a counting rule (critic-research.md §2b; search summaries). The critic found no Medicare manual rule on counting days.
- **Finding (P2 uncertain, P3 major):** the text doesn't settle day 0 versus day 1. The old rule read the start as day 1, but neither `text` nor an ADR said so, and gaps 31 and 92 were untested.
- **Ruling:** keep day 1, so the window is a gap of 30 to 90 days. The ordinal "31st day" and the 30-day adherence window inside "the first three (3) months" favor it. The readings differ only at gaps of exactly 30 (met here) and 91 (unmet here). The `text` field now states the convention.
- **Boundary tests:** `test_pap_reevaluation_counts_start_as_day_one` (gaps 29, 30, 31, 90, 91, 92).
- **Raised (P1 major), listed as a known limit:** "If the treating practitioner re-evaluation does not occur until after the 91st day but the evaluation demonstrates that the beneficiary is benefiting from PAP therapy as defined in criteria 1 and 2 above, continued coverage of the PAP device will commence with the date of that re-evaluation." PAIR still reports a late visit as outside the window.

## 3. Facet "moderate" pain: change

- **LCD L38841 v20** (https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid=38841&ver=20): "Moderate to severe chronic neck or low back pain, predominantly axial, that causes functional deficit measured on pain or disability scale*". Its note: "Acceptable scales include but are not limited to: verbal rating scales, Numerical Rating Scale (NRS) and Visual Analog Scale (VAS) for pain assessment". The LCD gives no numeric cut-off. The critic found none from WPS, and couldn't retrieve billing article A58477.
- **Literature:** Boonstra et al. 2014, *Pain* 155:2545, chronic musculoskeletal pain, VAS moderate from 3.5 (https://doi.org/10.1016/j.pain.2014.09.014; cited by the critic from search, not re-fetched). Boonstra et al. 2016, low-catastrophizing subgroup 4 to 6 (https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5043012/). Serlin 1995 (5 to 6) is a cancer population.
- **Finding (P2 blocker):** the rule read only a 0 to 10 number, so a verbal "moderate" or "severe" rating, which the LCD accepts, came out insufficient. **P3 major:** the cut-off of 4 had no citation, and 4 was never tested as met.
- **New rule:** `((pain_score is not None and pain_score >= 4) or (pain_score is None and pain_severity_verbal in ['moderate', 'severe'])) and pain_is_axial and functional_deficit_documented`. The `is None` pair keeps a record with neither rating Unknown (ADR-0012).
- **Disability scale only:** stays insufficient. "Moderate to severe" grades pain intensity, and no source maps ODI or Roland-Morris to it.
- **Boundary tests:** `test_facet_moderate_pain_numeric_or_verbal` (3, 4, verbal moderate/severe/mild, neither, number plus verbal), `tests/rules/test_engine.py::test_pain_score_four_is_moderate` (3 unmet, 4 met).

## 4. Oxygen time of need: change

- **LCD L33797 v50** (https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid=33797&ver=50): "For an inpatient hospital patient anticipated to require oxygen upon going home, the time of need would be within 2 days of discharge."
- **NCD 240.2 v2** (https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid=169&ncdver=2), which L33797 incorporates: "For those patients whose initial oxygen prescription does not originate during an inpatient hospital stay, the time of need is during the period when the treating practitioner notes signs and symptoms of illness that can be relieved by oxygen in the patient who is to be treated at home." **Correction to the handoff:** this outpatient definition is in the NCD, not in L33797.
- **Contractors:** Noridian and CGS read "within 2 days of discharge" as the 2 days before discharge home (search summaries; direct fetches failed).
- **Finding (P2 blocker):** `tested_at_time_of_need` was one opaque bool that never checked the inpatient day count and left the outpatient meaning undefined. The planner's "failing" phrase ("6 weeks after recovery, when stable") doesn't fail either definition (seeded-test.md, seed-06).
- **New rule:** `practitioner_ordered_and_reviewed and (not rx_from_inpatient_stay or within_days(test_date, discharge_date, 2)) and (rx_from_inpatient_stay or symptoms_noted_at_test)`
- **Records that fail:** an inpatient test 3 or more days before discharge, a test after discharge, an outpatient test with no symptoms noted. Neither document has a "within 30 days" test window, so the planner must not use one.
- **Boundary tests:** `test_oxygen_time_of_need_by_setting` (inpatient 0, −2, −3, +1 days; outpatient with symptoms present, absent, unknown; setting unknown).

## 5. Facet scope gaps

**LCD L38841 v20** (URL above) for all three.

**5a. Neurogenic claudication: change.** "Absence of untreated radiculopathy or neurogenic claudication (except for radiculopathy caused by facet joint synovial cyst)". The rule checked only radiculopathy, so a stenosis patient with untreated claudication came out met (P2 blocker). New rule: `not untreated_radiculopathy and not untreated_neurogenic_claudication`. Tests: `test_facet_neurogenic_claudication_counts`.

**5b. Sustained relief: change.** "Initial thermal RFA: after the patient has had at least 2 medically reasonable and necessary diagnostic MBBs, with each one providing a consistent minimum of 80% sustained relief of primary (index) pain (with the duration of relief being consistent with the agent used)." The rule counted blocks only (P2 blocker). New rule: `blocks_with_80pct_relief >= 2 and relief_duration_consistent_with_agent`. The new variable is bound only when the record states it; PAIR keeps no drug-duration table. Tests: `test_facet_block_relief_must_last_as_expected`.

**5c. Same pain scale and baseline disability scale: known limit, plus one open question.** "*Pain assessment must be performed and documented at baseline, after each diagnostic procedure and at each follow-up using the same pain scale for each assessment. A disability scale must also be obtained at baseline to be used for functional assessment (if patient qualifies for treatment)."
- **Same scale:** listed as a known limit in the README. It is a cross-document check, and notes rarely name the scale.
- **Baseline disability scale: uncertain.** The Q5 critic proposed adding `disability_scale_at_baseline` to `pain_and_function`. The Q3 critic read "(if patient qualifies for treatment)" as making it a documentation duty after qualifying, not an entry criterion. The rule isn't changed, and the item is listed as a known limit until Nithin rules.

## Open questions for Nithin (Step 9)

1. **AHI between 14 and 15** (for example 14.5) fits neither LCD band, so it comes out unmet. Keep, or round?
2. **Baseline disability scale (5c):** add it as a requirement of `pain_and_function`, or keep it as a known limit?
3. **Late PAP re-evaluation:** model "coverage commences with the date of that re-evaluation" (for example, report insufficient instead of unmet when a later visit shows benefit), or keep it as a known limit?
4. **Two LCD items outside the five questions:** the 2-week minimum between diagnostic blocks and the synovial-cyst exception. Both are listed as known limits.
5. **VAS on 0 to 100 mm:** the rule assumes 0 to 10. Extraction must normalize a 35 mm VAS to 3.5, or it would pass at 35.
6. **Proposed L33797 revision:** the MCD export lists a proposed "Oxygen and Oxygen Equipment" LCD (status P, export `lcd_id` 40403, display id 33797, v11, updated 2026-07-16). If it becomes final, re-run this question.

## Raw verdicts

The JSONL verdicts are under `data/audit/rule-review/` (gitignored): `q1-ahi_threshold.jsonl`, `q2-reevaluation.jsonl`, `q3-pain_and_function.jsonl`, `q4-ordered_and_evaluated.jsonl`, `q5-facet-scope.jsonl`.
