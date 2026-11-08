# ADR-0004: Dual frontend — Streamlit demo + Vercel landing page

**Status:** Accepted; the Streamlit demo half is superseded by [ADR-0023](0023-phase-4-nextjs-demo-and-deps.md) (the demo is Next.js + FastAPI)
**Date:** 2026-04-21
**Supersedes:** Refines baseline blueprint-v2 §4.1 (Streamlit only)

## Context

Baseline blueprint-v2 names Streamlit as the sole UI, reusing the pattern from TruPharma. User has noted Streamlit's flexibility limits for production-style UIs and prefers Vercel + Next.js when flexibility matters.

Two distinct UI needs exist for this project:
1. **A working demo** — evidence highlighting, graph traversal visualization, upload flows, decision traces. This favors rapid ML-demo scaffolding over polish.
2. **A first impression for recruiters** — problem framing, architecture explanation, embedded demo GIF, blog post, live demo link. This favors polish and flexibility.

Forcing both into one tool compromises each.

## Decision

Build **two separate frontends**:

- **Streamlit app** (hosted on Streamlit Cloud free tier or Hugging Face Space)
  - The working demo: upload Synthea bundle → PA decision → evidence trail
  - Hits the FastAPI backend for all logic
  - Optimized for showing the *reasoning*, not for beauty

- **Vercel + Next.js landing page**
  - Product-style marketing site
  - Problem statement, architecture diagram, looping demo GIF, blog post
  - Links to: live Streamlit demo, GitHub repo, CDS Hooks endpoint, decision records
  - Optimized for 30-second recruiter scan

Both frontends hit the **same FastAPI backend**, deployed on Cloud Run while GCP credits last (per ADR-0002), then Fly.io or Railway as fallback.

## Consequences

**Easier:**
- Demo and marketing don't compromise each other
- Recruiter experience: land on polished Vercel page → click "Try it" → use working Streamlit demo → view code on GitHub
- Each tool does what it's best at

**Harder:**
- Two deploys instead of one
- Two sets of CSS/UX decisions to maintain
- Slightly more surface area for bugs

## Alternatives Considered

1. **Streamlit only (baseline)** — rejected: landing page would look unpolished, hurts first impression
2. **Next.js only** — rejected: rebuilding the evidence-highlighting demo UI from scratch in React is weeks of work that Streamlit gives for free
3. **Gradio instead of Streamlit** — considered; Streamlit wins on evidence-display patterns already proven in TruPharma
4. **Single Next.js app with embedded Streamlit iframe** — rejected: awkward UX, worst of both worlds

## Notes

- Deploy sequence: FastAPI backend first → Streamlit demo (points to backend) → Vercel landing (links to demo)
- Both frontends pull from the same `/pa-check` and `/denial-analyze` endpoints
- Landing page should embed a 15–30 second auto-playing demo GIF above the fold
- Blog post should live on personal site or Medium, linked from the landing page
