# ADR-0006: Pivot to patient-side Appeal Copilot (PAIR v2)

**Status:** Accepted
**Date:** 2026-10-13
**Supersedes:** Payer-side framing of baseline blueprint-v2 and insurance-companion; ADR-0005 (CDS Hooks scope) deferred

## Context

PAIR v1 automated the payer's PA decision (approve / deny / need info). In 2026 that framing became hard to defend. CMS's WISeR model pays AI vendors in a way critics tie to denials, and the House moved to defund it in June 2026. Meanwhile, appeals of MA PA denials succeed most of the time (81.7% overturned, 2023 KFF data), yet only 11.7% of denials get appealed. CMS-4201-F requires MA plans to follow NCD/LCD criteria, which makes LCD-cited appeals legally grounded. PAIR is also the Hack-a-Roo Fall 2026 Build Track entry (~40 h, submission 2026-11-09).

## Decision

- PAIR v2 is a patient-facing appeal copilot: denial in, then a per-criterion verdict, a gap list, a cited appeal letter, and a calibrated strength score with "get a human" abstention.
- Scope is MA denials judged against NCD/LCD. Phase 1 covers 3 policies (PAP for OSA, home oxygen, facet joint). Commercial plans and the clinic view are future work.
- Coverage logic is deterministic YAML + Python checklists. The LLM only extracts grounded evidence.
- Stack changes:
  - **Add:** LangExtract (grounded extraction), Docling (denial PDFs), Bespoke-MiniCheck (NLI verifier), split/Mondrian conformal + Venn-Abers (MAPIE/crepes), LightGBM.
  - **Add data:** CA DMHC IMR determinations as real appeal outcomes for the strength score.
  - **Keep:** Gemma 4 E4B via Ollama, Vertex Gemini burst (thinking budget 0), Streamlit, Presidio, Synthea.
  - **Drop for v2:** Neo4j, Qdrant, CDS Hooks.
- Full spec: `~/PAIR/docs/PAIR-v2-requirements.md`.

## Consequences

**Easier:**
- A defensible impact story, and a fit with judging criteria and the clinical-XAI thesis lane.
- A smaller stack fits the 8 GB laptop and the 40 h budget.
- Real outcome labels (IMR) give an honest calibration story.

**Harder:**
- IMR covers California commercial plans, not Medicare. The strength score must be framed as a historical base rate.
- Close prior art (AGVF, arXiv 2609.27844) means PAIR must win on real-LLM evaluation and guarantees, not on the idea alone.
- License limits: IMR is noncommercial with no altered redistribution, and MiniCheck is CC BY-NC.

## Alternatives Considered

1. **Keep payer-side v1** was rejected: controversial in 2026, weaker impact story, larger stack.
2. **Provider pre-submission tool (PAVE-1 style)** was rejected for Phase 1: it needs EHR access and clinic users. It may return as the clinic view.
3. **Pure LLM appeal writer** was rejected: published evidence shows unsupported citations, and it doesn't differentiate from Counterforce, Claimable or Fight Health Insurance.

## Notes

- Requirements doc: `~/PAIR/docs/PAIR-v2-requirements.md`
- Hackathon memo: `~/ClaudeVault/projects/hackaroo-fall-2026/decision-memo.md` (its 67% stat is superseded by the KFF 2023 figures)
- Action items: verify LCD IDs in MCD; read the IMR data dictionary; check the Fight Health Insurance license; confirm dataset rules at the 2026-10-16 Q&A.
