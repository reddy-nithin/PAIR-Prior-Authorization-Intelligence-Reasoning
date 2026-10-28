# Architecture Decision Records (ADRs)

This directory holds all architecture and scope decisions for PAIR.

## Why ADRs?

The baseline plan documents (`docs/blueprint-v2.md`, `docs/insurance-companion.md`) are **frozen snapshots** of initial thinking. Real projects drift. Rather than edit those docs and lose provenance, every subsequent decision lives here as a numbered ADR.

**Rule:** If baseline and an ADR conflict, the ADR wins. If two ADRs conflict, the higher-numbered one wins (and ideally explicitly supersedes the earlier).

## ADR Lifecycle

- **Proposed** — under discussion
- **Accepted** — active, current truth
- **Superseded by ADR-NNNN** — replaced by a later decision
- **Deprecated** — no longer relevant, kept for history

## Index

| # | Title | Status | Date |
|---|---|---|---|
| 0001 | Solo standalone project, independent of TruPharma | Accepted | 2026-04-21 |
| 0002 | Local-first development with GCP burst for heavy batch | Accepted | 2026-04-21 |
| 0003 | Gemma 4 E4B as primary LLM (over Llama 3.1) | Accepted | 2026-04-21 |
| 0004 | Dual frontend — Streamlit demo + Vercel landing page | Accepted | 2026-04-21 |
| 0005 | Scope FHIR work to CDS Hooks CRD only (not full Da Vinci PAS) | Accepted | 2026-04-21 |
| 0006 | Pivot to patient-side Appeal Copilot (PAIR v2) | Accepted | 2026-10-13 |
| 0007 | Bayes-style strength score with an explanation panel | Accepted | 2026-10-15 |
| 0008 | Rule expression language for policy checklists | Accepted | 2026-10-15 |
| 0009 | Data-layer dependencies for contracts, policies and IMR | Accepted | 2026-10-15 |
| 0010 | Phase 2 dependencies and the Gemini model | Accepted | 2026-10-16 |
| 0011 | LLM placement: Gemma 4 E4B on the lab server, E2B on the laptop | Accepted | 2026-10-16 |
| 0012 | Rule evaluation semantics: three-valued logic and evidence binding | Accepted | 2026-10-16 |
| 0013 | Adversarial critic for audits, with source-backed verdicts | Accepted | 2026-10-22 |
| 0015 | Rule changes from the Step 7 rule review | Accepted | 2026-10-23 |

## Template

Copy `0000-template.md` (or this block) when creating a new ADR:

```markdown
# ADR-NNNN: <Short Title>

**Status:** Proposed | Accepted | Superseded by ADR-XXXX | Deprecated
**Date:** YYYY-MM-DD
**Supersedes:** (none | ADR-XXXX)

## Context
What's the situation? What's changed since baseline or the last ADR?

## Decision
What are we doing, concretely?

## Consequences
What becomes easier? What becomes harder? What's the tradeoff?

## Alternatives Considered
What else did we look at, and why did we reject it?

## Notes
References, links, related ADRs.
```

## Conventions

- Filename: `NNNN-kebab-case-title.md` (4-digit zero-padded number)
- Number monotonically — never reuse numbers
- Keep ADRs short: 1 page preferred, 2 pages maximum
- If an ADR starts running long, split it into multiple smaller ADRs
- Link between ADRs with relative paths: `See [ADR-0003](0003-gemma-4-e4b.md)`
| 0016 | Policy finder for unsupported denials, on Vertex AI Search | Proposed | 2026-10-23 |
