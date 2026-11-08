# ADR-0023: Phase 4 demo in Next.js with a FastAPI backend, and its dependencies

**Status:** Accepted (Nithin, 2026-10-29)
**Date:** 2026-10-29
**Supersedes:** the "Streamlit demo" half of [ADR-0004](0004-dual-frontend-streamlit-and-vercel.md); amends spec §7 (UI, Export, Privacy rows) and §11 (layout)

## Context

ADR-0004 split the UI into a Streamlit demo and a Next.js landing page. The Phase 4 plan said "Figma first, then Streamlit". While planning Phase 4, Nithin chose Next.js for the demo as well, because it gives more control over design (2026-10-29). The demo needs a letter/source split view, sentence-level highlighting from character offsets, and keyboard navigation on every screen. Those are easier to get right with plain HTML buttons and Radix primitives than with Streamlit widgets.

Three more choices came up and were settled with Nithin on the same day:
- **Live mode** uses the calibrated pair, lab E4B + MiniCheck-7B, over the SSH tunnel. Neither runs on the 8 GB M2 (ADR-0011), and the fitted threshold only covers that pair (ADR-0020). The M2 runs the UI and the API.
- **Privacy** uses Presidio with spaCy `en_core_web_lg`.
- **Figma**: Claude drafts the 7 frames through the Figma connector and Nithin reviews them.

## Decision

**Shape**
- `web/`: a Next.js app (App Router, TypeScript, Tailwind, Radix UI primitives), npm, Node 24. It deploys to Vercel unchanged.
- `src/pair/api/`: a FastAPI app on localhost, run with uvicorn. Routes: `/health`, `/cases`, `/cases/{id}`, `/run`, `/export/{docx|pdf}`.
- One UI contract: `CaseView` (pydantic, `src/pair/ui/view.py`), built from `CoreRun` + `TrustRun`. Its JSON Schema generates `web/src/types/caseview.ts`; a test fails when the file is stale. Existing contracts (`Denial`, `Checklist`, `Evidence`, `Verdict`, `Claim`/`Letter`, `Strength`) are unchanged. A letter-facing criterion heading (Phase 4 T1) is used by the letter template only, never by the drafter, so q̂ stays valid.

**Modes**
- **Cached:** each demo case is a verified `CaseView` JSON + pre-rendered DOCX and PDF in `data/demo-cache/` (manifest with schema version, git commit, models, threshold key, premise rule, SHA-256 per file; the offline generation cache pattern). A publish script copies a verified cache into `web/public/demo/` (gitignored). It works with Ollama and the API both stopped.
- **Live:** laptop only. The browser posts uploads to the local API, which runs `run_core` + `run_trust` against the lab tunnel. Uploads never pass through Vercel.

**Privacy**
- The API reads uploads as size-capped raw request bodies (`await request.body()`), not `UploadFile`, which spools files over 1 MB to disk. `read_upload(name, data)` reads bytes, using Docling's `DocumentStream` for PDFs and photos.
- Upload text is never logged. In addition, a logging filter on the API process runs Presidio (`presidio-analyzer`, `presidio-anonymizer`, spaCy `en_core_web_lg`, loaded lazily and once) and replaces detected PII with entity tags.

**Dependencies** (exact versions pinned in `uv.lock` / `web/package-lock.json` at install and listed in the tracker)
- Python runtime: `fastapi`, `uvicorn`, `python-docx`, `fpdf2`, `presidio-analyzer`, `presidio-anonymizer`, `en_core_web_lg` (pinned wheel URL from the spaCy models release).
- Python dev: `textstat` (grade-level test only), `httpx` (FastAPI `TestClient`), `pypdf` (reads exported PDFs in tests; BSD-3).
- Web: `next`, `react`, `react-dom`, `tailwindcss`, `@radix-ui/*` (only the primitives used), `vitest`, `@testing-library/react`, `@playwright/test`, `@axe-core/playwright`, `json-schema-to-typescript`.

**Tests and checks:** pytest for `ui/` and `api/`, Vitest for components, and Playwright for a keyboard-only walkthrough of all 7 screens plus an axe scan (0 serious or critical violations). The Playwright walkthrough is the reproducible evidence for the "keyboard-only navigation" exit check, next to Nithin's hand check.

**Out of scope here:** public Vercel deploy, and whether synthetic demo JSON is committed or built at deploy time. Both move to Phase 5.

## Consequences

**Easier:**
- Full control of layout, focus order and highlighting; accessible widgets from Radix.
- The cached demo is static files, so it works offline and can go on Vercel later with no backend.
- The same `CaseView` feeds live and cached mode, so one test set covers both.

**Harder:**
- A second toolchain (Node, npm, Playwright browsers) and a second test runner.
- Two processes in live mode (API + Next.js). On the 8 GB M2 this is fine only because Ollama runs on the lab server; the "one heavy service at a time" rule still holds.
- Presidio with `en_core_web_lg` adds about 600 MB on disk and about 1 GB of RAM in the API process.
- The frontend can't import Python types, so the generated TypeScript file must be kept in sync (enforced by a test).

## Alternatives Considered

1. **Streamlit (ADR-0004, earlier plan)**: rejected by Nithin for limited design control.
2. **Next.js API routes calling Python through a subprocess**: rejected. FastAPI keeps the pipeline in-process and testable with `TestClient`.
3. **WeasyPrint for PDF (spec §7)**: rejected. It needs pango and cairo system libraries; `fpdf2` is pure Python.
4. **No Presidio, never log upload text**: offered; Nithin chose Presidio as a second guard.
5. **Mac E2B live mode**: rejected. No calibrated verifier on the laptop, so every sentence would show as "not evaluated".

## Notes

- Related: [ADR-0004](0004-dual-frontend-streamlit-and-vercel.md), [ADR-0011](0011-llm-placement-lab-e4b-mac-e2b.md), [ADR-0018](0018-phase-3-verifier-and-dependencies.md), [ADR-0020](0020-claim-labels-and-conformal-split.md).
- On acceptance: update spec §7 and §11, the Phase 4 section of the build plan, and ADR-0004's status.
- Licenses: Next.js MIT, FastAPI MIT, Presidio MIT, spaCy models MIT, fpdf2 LGPL-3.0 (used as a library, unmodified), python-docx MIT.
