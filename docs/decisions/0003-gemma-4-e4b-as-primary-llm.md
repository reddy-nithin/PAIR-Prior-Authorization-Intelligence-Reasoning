# ADR-0003: Gemma 4 E4B as primary LLM (supersedes baseline's Llama 3.1)

**Status:** Accepted
**Date:** 2026-04-21
**Supersedes:** Baseline blueprint-v2 §4.1 LLM picks

## Context

Baseline blueprint-v2 §4.1 named Llama 3.1 8B as the primary local LLM. At the time, Gemma 2 9B was the other serious contender; it was rejected due to an 8K context window that was too small for a RAG-heavy pipeline.

**Gemma 4 released April 2, 2026** and changes the calculus:
- Context window: 128K on E2B/E4B, 256K on 26B MoE and 31B dense
- Built from same research as Gemini 3
- Native multimodality (text + image; audio on small models)
- Native function-calling and system-prompt support
- Configurable reasoning/thinking modes
- Apache 2.0 license (cleaner than Llama's community license for a public portfolio repo)

For an 8 GB RAM MacBook Air, Gemma 4 E4B (~3–4 GB Q4) fits comfortably.

## Decision

Adopt **Gemma 4 E4B via Ollama (Q4 quantization)** as the primary LLM for PAIR.

Role assignments:
- **Entity extraction** (NER-like structured output over clinical notes) — Gemma 4 E4B
- **Per-criterion verdict reasoning** (Graph-RAG citation contract) — Gemma 4 E4B
- **Appeal letter drafting** (Feature 2) — Gemma 4 E4B
- **Multimodal fax/PDF ingest** (stretch) — Gemma 4 E4B native vision, reducing reliance on Tesseract OCR
- **Eval sweeps / larger-model comparison** — Gemma 4 26B MoE on Vertex AI (per ADR-0002)

Fallback: if Gemma 4 E4B underperforms on a specific task, Llama 3.1 8B via Ollama is a drop-in swap.

## Consequences

**Easier:**
- 128K context removes almost all truncation concerns for multi-chunk RAG prompts
- Native vision simplifies the multimodal pipeline (fewer moving parts than Tesseract + separate vision model)
- Apache 2.0 license — no ambiguity for public repo distribution
- Recruiter framing: "I built on Gemma 4, Google's latest open model derived from Gemini 3 research" reads as current and deliberate

**Harder:**
- Gemma 4 is brand new — ecosystem tutorials and LangGraph/LlamaIndex examples are thinner than Llama's
- Some prompt patterns that work well on Llama may need re-tuning for Gemma's instruction format
- Less community data on medical/clinical performance specifically

## Alternatives Considered

1. **Llama 3.1 8B (baseline pick)** — rejected: similar context (128K) and size, but less current, community-licensed, and no native multimodality
2. **Qwen 2.5 7B** — rejected: solid for extraction but weaker reasoning story and no multimodality
3. **Medical-domain models (Meditron 3, BioMistral)** — rejected for v1: too specialized, harder to justify for the verdict step's citation contract; reconsider as a fine-tuning stretch goal later
4. **Hybrid Gemma + Llama** — rejected: unnecessary complexity for a solo project; start with one model, add second only if a specific task demands it

## Notes

- Ollama model tag: verify exact name at `ollama.com/library/gemma4` before pulling
- Prompt templates from TruPharma may need Gemma-specific tweaks for format compliance
- Benchmark local E4B vs cloud 26B MoE on the OIG-extracted eval set during Phase 6b — that comparison is a blog-post-worthy artifact
