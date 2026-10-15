# ADR-0001: Solo standalone project, independent of TruPharma

**Status:** Accepted
**Date:** 2026-04-21
**Supersedes:** (none)

## Context

PAIR is being scoped at the same time TruPharma Clinical Intelligence is in active development. The two projects share a domain (healthcare AI) and some technical patterns (hybrid retrieval, Graph-RAG, Streamlit demos). There's a real temptation to build PAIR as a TruPharma module or to share infrastructure.

However:
- TruPharma has co-founders (Amy, Salman); PAIR is solo.
- TruPharma is a capstone pursued beyond school; PAIR is a pure portfolio piece.
- Mixing the repos risks muddying ownership narratives in job interviews.
- The job-market value of "I built X solo" is distinct from "I contributed to Y with a team."

## Decision

PAIR is a solo, standalone project. Separate repo, separate infrastructure, separate narrative.

**Cross-reference is allowed, coupling is not:**
- OK: applying a TruPharma pattern (e.g., hybrid BM25 + dense retrieval) in PAIR
- OK: mentioning TruPharma learnings in PAIR's decision records
- Not OK: importing TruPharma code into PAIR
- Not OK: sharing databases, API keys, or deployed infrastructure

## Consequences

**Easier:**
- Clean "I built this solo" story for interviews
- No coordination overhead with co-founders
- Can experiment with stack choices TruPharma already committed against
- Clear ownership for portfolio purposes

**Harder:**
- Can't reuse TruPharma code directly — patterns must be re-implemented
- Two codebases to maintain in parallel
- Potential for pattern drift between the two projects over time

## Alternatives Considered

1. **PAIR as TruPharma module** — rejected: dilutes solo story, couples release cycles
2. **Shared core library with two frontends** — rejected: over-engineering for two small projects, and it doesn't solve the narrative problem
3. **Fork TruPharma and iterate** — rejected: same narrative issue, plus git history pollution

## Notes

See `CLAUDE.md` "Working rules" section for enforcement.
