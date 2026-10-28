# ADR-0016: Policy finder for unsupported denials, on Vertex AI Search

**Status:** Proposed
**Date:** 2026-10-23
**Supersedes:** (none; extends the "unsupported" branch of policy selection)

## Context

Policy selection is deterministic (`src/pair/policies/select.py`). It uses the denial's `policy_ref`, then the service-code table, and answers "unsupported" when neither gives exactly one of the three modeled policies (PAP for OSA, home oxygen, facet joint). That is the right call for the verdict, because PAIR never guesses a checklist. For the patient, though, "unsupported" is a dead end. Most real Medicare Advantage denials will fall outside three policies, and the patient doesn't learn which NCD or LCD their denial is probably about.

The project has a $1,000 GenAI App Builder trial credit (valid to March 2027) that Google support says covers Vertex AI Search only, not Gemini calls. Vertex AI Search is a managed index over your own documents. The MCD export that `make data` already downloads holds every NCD and LCD with its text, version and URL.

## Decision

**When selection says "unsupported", PAIR shows up to three policies that might apply, found by search. It never checks them.**

- **Index:** one Vertex AI Search data store built from the MCD export (NCDs and LCDs: id, title, version, contractor, URL, and the indications and coverage text). A script under `scripts/` builds it. No case data, notes or IMR rows go into it.
- **Query:** built only from denial fields: service codes, `policy_ref` if any, and the denial reason text, with names, dates, member ids and other identifiers stripped first. Clinical notes are never sent.
- **Output:** the top three hits with id, title, version, URL and the matched snippet, shown as "Policies that may apply. PAIR can't check these yet." The selection result stays `None`, so no checklist runs, no verdict is produced, and the strength score is not shown.
- **Search only, no generated answers.** No summarization or answer-generation add-on is turned on. This keeps the LLM out of the path (the LLM reads, it never decides), and it keeps billing on Search SKUs.
- **Optional and off by default:** a config switch, like the LLM backend switch. Cached results for the demo cases, so the demo runs with no network.
- **Phase:** Phase 4 (Product). Not on the critical path for Phase 3.

**Evaluation.** About 20 denials whose correct policy is known (the 3 modeled policies plus hand-picked others from the MCD), scored by recall@3: is the right policy in the top three? Reported in `RESULTS.md` with the data store build date.

**Wording rule.** "Policies that may apply," never "your policy" or "the policy that applies."

## Consequences

**Easier:**
- An unsupported denial still gives the patient a concrete next step: a named policy, its link, and the matching text.
- The finder also ranks which policy to model next, by how often it comes up.
- It uses a credit that would otherwise go unused.

**Harder:**
- A cloud dependency in a local-first project (ADR-0002). The switch and the cache keep the core pipeline offline.
- Denial text leaves the machine. Stripping identifiers is required, and real users would need a clear notice before this is turned on.
- The data store goes stale when the MCD changes. It needs a rebuild step and a recorded build date.
- Billing is unconfirmed. Before building, a small test data store and about 10 queries must show a charge against the $1,000 credit in Billing > Reports. If it doesn't, this ADR moves to the local alternative below.

## Alternatives Considered

1. **Local BM25 or FAISS over the MCD export:** free, offline and in line with ADR-0002. Not rejected: it is the fallback if the credit test fails, and the finder sits behind one interface so either backend fits. Vertex AI Search is preferred for now because it gives managed semantic ranking at no cost under the credit.
2. **Ask the LLM which policy applies:** rejected. It breaks the core rule, and a confident wrong policy is worse than "unsupported".
3. **Map the finder's top hit to a checklist automatically:** rejected. Only hand-built, source-verified checklists produce verdicts.
4. **Model more policies instead:** not an alternative but the real fix, one YAML at a time. The finder shows which ones to do first.

## Notes

- Related: ADR-0002 (local-first), ADR-0006 (patient-side scope), ADR-0012 (rule semantics).
- Number: 0014 and 0015 are taken by the real-data and critic tracks. Renumber on rebase if needed.
- Action items: (1) credit test with a small data store; (2) spec §3 and §5 updates if accepted; (3) 20-denial recall@3 set.
