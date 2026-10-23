# ADR-0015: Rule changes from the Step 7 rule review

**Status:** Accepted (pending Nithin's sign-off of the verdicts, critic plan Step 9)
**Date:** 2026-10-23
**Supersedes:** (none; refines ADR-0008 rules and documents the ADR-0012 day count)

## Context

The audit critic ([ADR-0013](0013-adversarial-critic-for-audits.md)) reviewed five rule questions in rule mode against the MCD export (L33718 v52, L33797 v50, NCD 240.2 v2, L38841 v20). Four found the rule looser or stricter than the policy text for a realistic record. One found a real ambiguity that the rule resolves but never documented. Verdicts, quotes and URLs are in [docs/audit/rule-review.md](../audit/rule-review.md).

## Decision

**PAP `ahi_threshold` (change).** The 30-event and 10-event minimums apply only when the AHI or RDI "is calculated based on less than 2 hours of sleep or recording time" (L33718 definitions). New variable `sleep_or_recording_hours`. Exactly 2.0 hours needs no count. AHI with neither the hours nor the count stays insufficient, because the record must state the fact (PIM ch. 3).

**PAP `reevaluation` (keep, now documented).** The therapy start date is day 1, so "the 31st day" to "the 91st day" is a gap of 30 to 90 days. No CMS, DME MAC or manual source settles the count. The ordinal wording and the 30-day adherence window inside the first three months favor day 1. The two readings differ only at gaps of exactly 30 and 91 days.

**Oxygen `ordered_and_evaluated` (change).** Time of need is split by setting. Inpatient: the test is within 2 days before discharge (L33797: "within 2 days of discharge"; DME MAC guidance reads it as before discharge). Outpatient: the practitioner notes symptoms oxygen can relieve (NCD 240.2 v2, which L33797 incorporates). `tested_at_time_of_need` is replaced by `rx_from_inpatient_stay`, `test_date`, `discharge_date` and `symptoms_noted_at_test`. An outpatient record never needs a discharge date.

**Facet `pain_and_function` (change).** "Moderate" is 4 or more on a 0 to 10 scale, or a verbal rating of "moderate" or "severe" (the LCD accepts verbal rating scales). The cut-off of 4 is the most lenient published band that fits chronic musculoskeletal pain (Boonstra et al. 2014, VAS moderate from 3.5; Boonstra 2016 subgroup 4 to 6). The LCD sets no number, so PAIR doesn't add a stricter one. A numeric score decides when both are recorded. A disability scale alone stays insufficient: "moderate to severe" grades pain. The rule's `is None` pair only routes to the verbal rating when no number exists; with neither, it stays Unknown, as ADR-0012 requires.

**Facet `no_untreated_radiculopathy` (change).** Adds `untreated_neurogenic_claudication`, which the clause already names.

**Facet `diagnostic_block_relief` (change).** Adds `relief_duration_consistent_with_agent`, bound only when the record says so. PAIR has no drug-duration table, and the LCD gives none.

**Not modeled; listed as known limits in the README:** the same-pain-scale footnote, the baseline disability scale (its "(if patient qualifies for treatment)" makes it ambiguous as an entry criterion), the 2-week spacing between diagnostic blocks, the synovial-cyst exception, and late PAP re-evaluations that restart coverage from that date.

## Consequences

**Easier:**
- Full-night sleep studies, verbal pain ratings and outpatient oxygen tests are judged the way the policy text reads.
- Each boundary (2.0 hours, gaps 29 to 92 days, 2 days before discharge, pain 3 versus 4) has a test.

**Harder:**
- Seven new variables for the extractor. Facet records that don't state the relief duration or claudication status now come out insufficient.
- Cases in `data/cases/` and `data/cases-dev/` were labeled under the old rules. They stay as the audited Phase 2 sets; the real-data track regenerates the v2 sets after the planner fixes merge.

## Alternatives Considered

1. **Day 0 for the re-evaluation window**: rejected. No source requires it, and day 1 matches the ordinal wording.
2. **Derive relief duration from the agent (lidocaine versus bupivacaine)**: rejected. The LCD gives no durations, so PAIR would be inventing a table.
3. **A disability-scale route for "moderate"**: rejected. The phrase grades pain intensity, and no source maps ODI or Roland-Morris to it.
4. **Model the baseline disability scale now**: deferred to Nithin (open question in rule-review.md).

## Notes

- Verdicts and sources: [docs/audit/rule-review.md](../audit/rule-review.md).
- Related: [ADR-0008](0008-rule-expression-language.md), [ADR-0012](0012-rule-evaluation-semantics.md), [ADR-0013](0013-adversarial-critic-for-audits.md).
- Boonstra AM, Schiphorst Preuper HR, Balk GA, Stewart RE. Cut-off points for mild, moderate, and severe pain on the visual analogue scale for pain in patients with chronic musculoskeletal pain. *Pain* 2014;155(12):2545–50. https://doi.org/10.1016/j.pain.2014.09.014
