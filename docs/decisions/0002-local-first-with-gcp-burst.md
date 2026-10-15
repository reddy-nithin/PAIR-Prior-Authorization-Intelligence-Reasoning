# ADR-0002: Local-first development with GCP burst for heavy batch work

**Status:** Accepted
**Date:** 2026-04-21
**Supersedes:** (none — refines baseline "local-first" in blueprint-v2 §4.2)

## Context

Baseline blueprint assumes pure local-first execution (Ollama, Docker, no paid APIs). This was drafted before a clear inventory of available cloud credits:

- **GCP Free Trial:** ~$295 remaining, expires **May 28, 2026** (USE OR LOSE)
- **GCP GenAI App Builder:** $1,000 through Mar 2027
- **GCP Developer Program:** $10/mo through Mar 2027
- **GitHub Student Pack:** AWS/Azure/DigitalOcean credits unclaimed

Additionally, the dev laptop is a MacBook Air M2 with **8 GB RAM** — tight for running Neo4j + Qdrant + Ollama + Streamlit + browser concurrently. Pure-local is feasible but painful for batch work (MIMIC-IV embedding, eval sweeps over OIG cases).

## Decision

Adopt a **hybrid execution model**:

- **Local (laptop)** — interactive development, prompt iteration, demos, lightweight inference via Ollama + Gemma 4 E4B.
- **GCP (Vertex AI + Cloud Run)** — batch embedding, large-scale eval sweeps, optional larger-model inference (Gemma 4 26B MoE), hosted FastAPI endpoint for a live demo URL.
- **Colab / HF Spaces** — zero-cost fallback when GCP credits expire.

Explicit priority: **burn the $295 expiring GCP trial before May 28, 2026** on workstreams that genuinely need it (full MIMIC-IV-Note embedding, Gemma 4 26B eval sweep, Cloud Run deployment of the demo backend).

Claim GitHub Student Pack AWS/Azure/DigitalOcean credits before May 28 as insurance.

## Consequences

**Easier:**
- MIMIC-IV embedding isn't bottlenecked by 8 GB RAM
- Can compare local Gemma 4 E4B vs cloud Gemma 4 26B empirically for the eval section
- "Live demo URL" artifact is realistic (Cloud Run scales to zero, cheap after credits)
- Story for recruiters: "local-first for dev and portability, cloud burst for heavy batch" — a pragmatic engineering narrative

**Harder:**
- Have to manage two execution environments and keep parity between them
- GCP costs must be monitored — accidentally leaving a GPU instance running would burn credits fast
- Project README has to explain both paths cleanly

## Alternatives Considered

1. **Pure local, no cloud at all** — rejected: wastes expiring GCP credits, and 8 GB RAM makes large-batch work untenable
2. **Pure cloud (Vertex AI everything)** — rejected: loses the "runnable on a recruiter's laptop" differentiator, and gets expensive after credits expire
3. **AWS SageMaker instead of GCP** — rejected: GCP credits are already in hand; AWS credit from Student Pack is a claimable future option but not ready today

## Notes

- Action: claim AWS/Azure/DigitalOcean student credits this week
- Set GCP billing alerts at $50 and $150 to avoid burning through the trial
- Document every GCP-run workstream in the README with cost/time stats
- See `cloud-credits.md` in vault for the master credit tracker
