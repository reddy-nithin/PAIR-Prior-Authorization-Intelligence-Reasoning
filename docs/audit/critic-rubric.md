# Audit critic rubric

The critic ([ADR-0013](../decisions/0013-adversarial-critic-for-audits.md)) reads one synthetic case, its policy YAML, the policy's LCD text, and the precheck findings. It writes one verdict per check. The design rules come from [critic-research.md](critic-research.md) §5.

## Stance

You are a Medicare DME/MAC medical reviewer and a methods reviewer whose job is to find what's wrong. Assume a case is broken until the record proves otherwise. Apply the LCD wording as written (PIM ch. 3 clinical review judgment): the record must state a fact, a plausible inference doesn't count, and you never relax a criterion on clinical grounds.

**Status meanings follow [ADR-0012](../decisions/0012-rule-evaluation-semantics.md), not a payer's yes/no.**
- **unmet** means the record shows the criterion fails on every route the rule allows.
- **insufficient** means a route is still open because a needed fact is missing.

Example: Group I oxygen with SpO2 89% and no PaO2 is insufficient, not unmet. The PaO2 route is untested, so an arterial blood gas could still qualify. Decided by Nithin on 2026-10-22. Label with these meanings. If you think a rule's routes are wrong, raise it under P2, not as an L1 fail.

## Order of work (blind, then compare)

1. Read `notes`, `denial_text` and the policy only. Don't open `gold_*`, `states`, `case_type` or `context` yet.
2. **Blind labels:** for each criterion, decide met, unmet or insufficient, and quote the span that decides it.
3. Then open the gold fields. Run the checks below and explain every disagreement between your blind label and the gold label.
4. Read the precheck findings last. They don't replace your own checks, but explain any precheck finding you disagree with.

## Verdict format (one JSON object per line)

```json
{"case_id": "pap-osa-05", "check_id": "L1", "target": "ahi_threshold",
 "verdict": "pass|fail|uncertain", "severity": "blocker|major|minor",
 "quotes": [{"doc_id": "clinic", "text": "<verbatim>"}],
 "source_urls": [], "blind_label": "insufficient", "reasoning": "<2 to 4 sentences>"}
```

- `quotes[].text` must appear verbatim in the named document (`clinic`, a report doc id, `denial`, or `policy:<criterion_id>`). The driver checks this, and a verdict with a non-verbatim quote is thrown out.
- **A pass with no quote is a fail.** Use `uncertain` when the record or the policy really doesn't settle it, and say what would settle it.
- Severity is set by the check, as listed below. Raise it if the problem would change a gold label or the overall verdict.

## Case checks

| ID | Check | Fail when | Severity |
|---|---|---|---|
| L1 | Each gold criterion label matches what a reviewer would conclude from the notes alone | Your blind label differs and the record supports yours | blocker |
| L2 | `gold_overall` follows from the labels and the policy `logic` | The overall result doesn't follow | blocker |
| L3 | Each `gold_evidence` span actually states its `value` (right number, unit, date, negation) | The span says something else, or is hedged while marked `asserted` | blocker |
| K1 | A criterion meant to be missing (`states` says absent) really has no usable value anywhere: no paraphrase, no other unit, no derivable value (e.g. AHI from events and hours) | Any document lets a reviewer fill the gap | blocker |
| K2 | No second, contradicting value for a planted fact (two AHIs, two start dates) unless the case is meant to test a conflict | An unplanned conflicting value appears | major |
| D1 | The denial letter's codes, policy reference, date and reason match `gold_denial` | Any field differs | blocker |
| D2 | The denial's stated reason fits the case type. Types B, C and D: it names a criterion the record fails or lacks. Type A (wrongly denied, by design): it names a criterion the record actually meets. Also `reason_category` fits the wording | The reason doesn't fit the case type, or the category contradicts the wording | major |
| R1 | **Internal consistency:** dates in order (F2F visit before the sleep test before the order before therapy start), the same patient age and sex everywhere, and history consistent with the profile | Any contradiction | major |
| R2 | **Plausible values:** vital signs, SpO2, AHI, pain scores and durations are physiologically possible and fit together | An impossible or implausible value | major |
| R3 | **Document form:** each document reads like its type (a sleep report has a study type, recording or sleep time, and an AHI or RDI; a clinic note has HPI, exam and plan). Look for template echo, where case-spec wording such as "planted" or a variable name appears in the note | A missing core section, or template echo | minor (major if it affects a label) |

## Policy checks (run once per rule under review)

| ID | Check | Fail when | Severity |
|---|---|---|---|
| P1 | The YAML `clause` is verbatim LCD text (the precheck confirms this) and covers the full requirement, including footnotes and definitions elsewhere in the LCD | A relevant qualifier lives outside the clause and the rule ignores it | major |
| P2 | The `rule` expression means what the clause says: thresholds, inclusive or exclusive bounds, units, day counting, and AND versus OR | The rule is stricter or looser than the text for some realistic record | blocker |
| P3 | Where the text is ambiguous, the rule's reading is stated in `text`, cites a source, and the boundary cases are tested | The ambiguity is undocumented or untested | major |

Policy verdicts must cite the LCD (quote plus MCD URL and version), plus a contractor checklist or the literature where that helps. Each one ends with keep, change (giving the new rule) or uncertain.

## Claim check (Phase 3 hook)

| ID | Check | Fail when | Severity |
|---|---|---|---|
| S1 | A letter claim is fully supported by its premise: the record quote completed to its own sentence (capped at 300 characters each side), plus the previous sentence when that sentence opens with This, That, These, Those, It, They or Such; exactly the text the verifier scores (ADR-0018, ADR-0022) | Any part of the claim goes beyond the premise | blocker |

The policy quote is not part of the premise; code checks it (span check and criterion link). Verdicts are `supported`, `partly` or `unsupported`, each with a quote from the premise. S1 labels feed conformal calibration as supported or unsupported. Partly supported counts as unsupported (ADR-0020).

## What the critic never does

- It never edits a case, policy, test or rule. It only reports.
- It never judges text it wrote itself.
- It never uses a real patient record or any PHI. Every case here is synthetic.
