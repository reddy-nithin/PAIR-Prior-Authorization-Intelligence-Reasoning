# ADR-0024: Quote the record sentence when a paraphrase of a met requirement is flagged

**Status:** Accepted (Nithin, 2026-10-29)
**Date:** 2026-10-29
**Supersedes:** (none; amends the letter rules in [ADR-0018](0018-phase-3-verifier-and-dependencies.md) and the `ClaimDecision` contract)

## Context

The Phase 4 demo cache (T9, lab E4B + MiniCheck, q̂ 0.5537) produced thin letters for sleep apnea. In pap-osa-01, 4 sentences were kept and 10 were flagged. The live run on the held-out pap-osa-02 kept 3 and flagged 11. The flagged ones include the facts the rule turns on:

| Letter sentence | MiniCheck P(Yes) |
|---|---|
| My record states an AHI of 21.1 events/hour. | 0.51 |
| My record shows 131 total respiratory events. | 0.53 |
| I used 4 hours or more on 78% of nights. | 0.20 |

These are true. The rule engine already marked these criteria met from the same record spans. A probe on the same premises shows the cause is the letter's first-person voice, not the facts. The record's own words score high: "used 4 hours or more on 78% of nights" scores 0.80, and "total recording time 6.2 hours" scores 0.93 (the first-person version scored 0.30).

A dev-only experiment rescored all 284 calibration claims in third person ("the patient used…") and refit q̂ (scratch run, 2026-10-29). Supported claims kept rose from 143/230 (62.2%) to 171/230 (74.3%), with partly or unsupported claims kept unchanged (4/54 in sample). But q̂ rose to 0.830 and the result was mixed by policy:

- **Facet joint:** better (pain_and_function 16 → 30, duration_and_conservative_care 0 → 7).
- **Home oxygen:** worse (ordered_and_evaluated 13 → 9, qualified_tester 7 → 4).
- **Sleep apnea:** AHI 21.1 still fell just short (0.82 vs 0.830).

Adopting it would also mean a second test-set evaluation of the trust layer. So it doesn't fix the problem here. It goes to Phase 6 as a research note.

## Decision

- **Quote sentences.** After step 6, take each FLAGGED claim whose criterion the rule engine marked **met**. Replace it with a quote sentence, `My records state: "<premise>".`, where `<premise>` is exactly `build_premise` of the claim's evidence span (ADR-0022). That is one contiguous slice of the record, so it is a whole sentence, never a fragment.
- **New decision `quote`.** `ClaimDecision.QUOTE` marks these sentences. They are checked by an exact match (the quoted text must equal the record slice at the cited offsets), not by the verifier, because a verbatim quote of a record says only what the record says.
- **Limits.**
  - Only criteria with status met qualify. Unmet or insufficient criteria keep today's behavior.
  - DROPPED claims (failed citation checks) are never quoted.
  - Two flagged claims with the same premise produce one quote.
  - A premise that already backs a KEPT sentence in the same paragraph isn't quoted again.
- **Shown honestly.** The letter screen labels these "Quoted word for word from your records" (not "Checked against your records"). The replaced paraphrase is recorded in the run metadata, and the letter keeps no second copy of the same fact.
- **Metrics unchanged.** The conformal leak rate, CCR and the Phase 3 exit numbers are about generated claims and are computed before this step. Runs also report the number of quote sentences per letter.

## Consequences

- Letters for met requirements always carry their key evidence, in the record's own words. The trust promise holds: every sentence is either checked by the verifier, or a word-for-word quote checked by string match.
- Quotes read less smoothly than paraphrases ("My records state: \"During this monitoring period, there were 131 total respiratory events, yielding an overall AHI 21.1 events/hour.\""). The patient can still edit before sending.
- A quote can repeat a wrong extraction: if extraction grounded the wrong span, the quote shows it. The same error already shows on the "Where you stand" screen, and Phase 2 grounding was 99.3%.
- Contract changes:
  - `ClaimDecision` gains `quote`.
  - `CaseView.Decision` gains `quoted`, so the schema and the generated TypeScript types change, and `schema_version` stays 1 because the field is additive.
  - `render_letter` treats `quote` like `keep`.
- The demo cache is rebuilt on the lab (one GPU pick).

## Alternatives

- **Third-person scoring** (above): mixed by policy and needs a new test evaluation. Phase 6 research note.
- **Lower q̂ for numeric claims:** breaks the conformal guarantee, rejected.
- **Computed sentences from a template** ("My sleep test shows an AHI of 21.1; the rule needs 15 or more"): reads better, but writing a value into new words needs its own check per evidence type. Possible later on top of this.
- **Do nothing:** demo letters for met requirements leave out the main evidence. Rejected.
