# PAIR results

All numbers come from logged runs.

<!-- phase2-core:start -->
## Phase 2: core engine (steps 1 to 4)

Run: backend `ollama`, model `gemma4:e4b`, host `http://localhost:11435`, config_hash `7fb3eaf148e6`, date `2026-10-19`, log `data/runs/eval-core-20261019-163452-7fb3eaf148e6.jsonl`. Cases: 30 synthetic (0 with errors).

| Metric | Target | Result | Pass |
|---|---|---|---|
| Denial-field accuracy | ≥90% | 95.7% | ✅ |
| Checklist macro-F1 | ≥0.85 | 0.93 | ✅ |
| Grounding (valid char interval) | ≥95% | 98.0% | ✅ |

- Per field: service 100.0%, codes 100.0%, reason_category 70.0%, policy_ref 100.0%, plan_type 100.0%, date 100.0%, selected_policy 100.0%.
- F1 per status: met 0.97, unmet 0.92, insufficient 0.91. Macro-F1 by case type: A 0.92, B 0.92, C 0.89, D 1.00.
- Overall verdict accuracy 90.0%; gold-span recall 98.3%.
- Extractions: 302 non-empty, 6 ungrounded (dropped), 28 blank placeholders (excluded); 0 documents failed to parse. Mean time per case 5.94 s.
- Definitions: denial accuracy pools 6 `Denial` fields + selected policy over all cases; macro-F1 is over met/unmet/insufficient for every criterion, scored on the case's own checklist; grounding excludes blank placeholders the model emits for facts it didn't find.
<!-- phase2-core:end -->

### Phase 2 run history
- Run 1 (`data/runs/eval-core-20261019-153848-7fb3eaf148e6.jsonl`, same 30 cases, before fixes): denial accuracy 95.7%, macro-F1 0.81, grounding 98.9%. LangExtract silently dropped unparseable chunks, the extractor turned "moderate pain" into 4, and one case (facet-joint-04) had a wrong gold label because the note writer leaked an "absent" fact.
- Fixes before run 2: parse errors now raise, are retried once and are counted as failed documents; the prompt forbids turning words into numbers; leak patterns added for 6 absent units and facet-joint-04 regenerated.
- Run 2 (`data/runs/eval-core-20261019-154509-7fb3eaf148e6.jsonl`): denial 95.7%, macro-F1 0.81, grounding 99.3%. Failures were now visible: 6 home-oxygen clinic notes failed to parse (E4B wrote lists or null where LangExtract expects a quoted phrase, and LangExtract rejects the whole chunk).
- Fix before run 3: a tolerant format handler drops only the malformed item (counted as ungrounded) and treats null as "not found", instead of losing the whole note.
- The fix was first checked on a held-out dev set (30 new cases, seed 2027, `data/cases-dev/`, never used for debugging; log `data/runs/dev/eval-core-20261019-163144-7fb3eaf148e6.jsonl`): denial 96.2%, macro-F1 0.90, grounding 97.6%, 0 failed documents.
- Run 3 (the table above) is the official Phase 2 result on the original 30 test cases.
- Caveat: the 30 test cases were also used to find the run 1 and run 2 failures, so they are not fully blind. The dev-set numbers are the cleaner estimate. Both sets share the same 40 Synthea profiles.

