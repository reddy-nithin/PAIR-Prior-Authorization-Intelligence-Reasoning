# ADR-0022: The verifier premise includes the previous sentence after a referring opener

**Status:** Accepted (Nithin, 2026-10-29)
**Date:** 2026-10-29
**Supersedes:** (none; amends the premise definition in [ADR-0018](0018-phase-3-verifier-and-dependencies.md) "Verifier interface" and check S1 in `docs/audit/critic-rubric.md`)

## Context

ADR-0018 defines the premise as the record quote completed to its own sentence, with no neighboring sentences. The verifier scores a claim against this premise and the S1 labeler (ADR-0020) judges the claim against the same text.

The labeler gate on 2026-10-29 showed a gap. Claim g-053 ("My records show I used PAP for 30 consecutive days within the first 3 months of starting therapy") had the premise "This usage pattern was sustained over 30 consecutive days within the first 3 months of starting therapy." The premise never says what "this usage pattern" is. Nithin labeled the claim partly; the critic labeled it supported, filling in the missing referent from common sense. MiniCheck cannot do that, so the verifier and its labels judge different things exactly where a sentence leans on the one before it.

A dry run of `build_premise` on the 284 dev claims (`data/runs/claims-dev.jsonl`):

- 35 premises (12%) open with This, That, These, Those, It, They or Such, and every one has a previous sentence in its document.
- About 25 are "This 83-year-old female patient presents…", where the previous sentence is a date line ("Date of Visit: 03/04/2026."). Adding it changes nothing a claim relies on.
- About 10 are true references, such as "This resulted in…", "This yields an…", "This pain…" and "This usage pattern…". Their previous sentence holds the fact being referred to (event counts, the pain rating, the nights-used figure).
- 60 more premises open with He, She, His or Her. Those words refer to the patient, whom the letter already calls "I", so the previous sentence adds nothing a claim needs.

## Decision

- **Rule.** `build_premise` first builds the own-sentence premise as today. If that text begins with one of the referring words This, That, These, Those, It, They or Such (case-sensitive, whole word), the previous sentence in the same document is added in front. The sentence boundary is the same as in ADR-0018: `.`, `!` or `?` followed by whitespace, or a line break.
- **Only one sentence back.** If the previous sentence itself opens with a referring word, nothing more is added. The premise stays short and the rule stays predictable.
- **Cap.** The previous sentence has its own 300-character cap, measured back from its end, in addition to the existing 300-character caps around the quote. The premise is always one contiguous slice of the document, so a quote from it can still be checked verbatim.
- **Patient pronouns are excluded.** He, She, His, Her, Him and Their-as-patient openers don't trigger the rule (see Alternatives).
- **S1 follows the premise.** The rubric's S1 row and the critic's claims mode keep judging against "the premise", now defined by this rule. The S1 labeler still uses only the premise and nothing outside it.
- **Re-run before labeling.** The 284 dev claims are re-drafted and re-scored with the new premise on the lab GPU before any S1 labeling export, so labels and scores are fit to the same text. Test claims are drafted only with the new rule.

## Consequences

**Easier:**
- Claims about "this result" or "this pain" are scored and labeled against the sentence that states the fact, so the verifier and the critic see the same evidence.
- The rule is deterministic, takes a few lines of code, and touches about 12% of dev premises.

**Harder:**
- It does not fix g-053 itself. That claim's previous sentence says "the patient used 4 hours or more on 78% of nights" and still never names PAP; the drafter took "PAP" from the policy text. Under this rule g-053 stays partly, which is the correct S1 label: the claim adds the device name. Claims like it will still be FLAGGED or labeled unsupported until the wording step stops importing words from the criterion text (a Phase 3 wording question, not a premise question).
- About 25 premises gain a date line they don't need. The verifier sees a little more text; nothing in a claim depends on it.
- The dev run from 2026-10-28 (`data/runs/claims-dev.jsonl`, config hash `7fb3eaf148e6`) is superseded and needs one more lab GPU run. The labeler gate result stands: it tested the critic's skill at S1, and the gate claims' premises are unaffected except g-053, whose label doesn't change.

## Alternatives Considered

1. **Keep own-sentence premises (ADR-0018 as written):** rejected. The critic and the verifier would keep disagreeing on referring sentences, and S1 labels on those claims would depend on how much the labeler guesses.
2. **Always add the previous sentence:** rejected. It changes every premise for about 10 that need it, and doubles the text the verifier reads.
3. **Also trigger on He, She, His, Her:** rejected. These refer to the patient, and the claim already speaks as the patient. 60 more premises would change for no gain.
4. **Add the whole paragraph or a fixed character window:** rejected. Long premises make MiniCheck more likely to find support somewhere in unrelated text, and labels get harder to check.
5. **Resolve the reference with an LLM:** rejected. The premise must be plain record text that code builds the same way every time.

## Notes

- Raised by Nithin while labeling the gate's natural claims (g-053), 2026-10-29.
- Related: [ADR-0018](0018-phase-3-verifier-and-dependencies.md), [ADR-0020](0020-claim-labels-and-conformal-split.md).
- Code: `src/pair/verify/nli.py` `build_premise`; tests in `tests/verify/test_nli.py`.
- If accepted: ADR-0018's status line gains "amended by ADR-0022", the S1 row in `docs/audit/critic-rubric.md` names this rule, and the plan's T4 line is updated.
