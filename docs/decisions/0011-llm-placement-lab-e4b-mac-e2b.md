# ADR-0011: LLM placement: Gemma 4 E4B on the lab server, E2B on the laptop

**Status:** Accepted
**Date:** 2026-10-16
**Supersedes:** (none; amends ADR-0003's size estimate)

## Context

ADR-0003 chose Gemma 4 E4B via Ollama and estimated it at "~3–4 GB Q4", small enough for the 8 GB M2. The Ollama library (checked 2026-10-16) lists `gemma4:e4b` at 6.6 GB (q4_K_M) and `gemma4:e4b-it-qat` at 6.1 GB. macOS gives the GPU roughly two-thirds of unified memory (about 5.3 GB on 8 GB), so E4B would spill to the CPU and swap. `gemma4:e2b-it-qat` is 4.3 GB.

## Decision

- **Batch extraction for evaluation** (the Phase 2 exit check and later sweeps) uses `gemma4:e4b` on the lab GPU server's Ollama (A4000, 16 GB), reached from the laptop through an SSH tunnel (`ssh -L 11434:localhost:11434 <server>`). The pipeline code is unchanged; only `model_url` differs.
- **Laptop dev and the live demo** use `gemma4:e2b-it-qat` on local Ollama.
- **Fallback:** Gemini on Vertex (ADR-0010), selected by the same backend switch.
- Every logged run records the backend, model tag and host, so metrics from different models are never mixed.

## Consequences

**Easier:**
- The evaluated model is the one ADR-0003 chose, without fighting the laptop's memory.

**Harder:**
- Demo (E2B) and eval (E4B) models differ. The demo is not the measured system unless E2B is evaluated too (a Phase 6 A4 ablation row).
- Eval runs depend on the server and the tunnel being up.

## Alternatives Considered

1. **E4B-QAT on the laptop**: rejected without a test. 6.1 GB exceeds the GPU share, and swapping would break the 60 s demo budget.
2. **Gemini only for Phase 2**: rejected. It would make the headline numbers come from a cloud model, against ADR-0003's local-first story.

## Notes

- Related: [ADR-0003](0003-gemma-4-e4b-as-primary-llm.md), [ADR-0010](0010-phase-2-dependencies-and-gemini-model.md).
