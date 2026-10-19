# ADR-0010: Phase 2 dependencies and the Gemini model

**Status:** Accepted
**Date:** 2026-10-16
**Supersedes:** (none)

## Context

Phase 2 builds the denial parser, evidence extraction and the synthetic case generator (spec §5.3, §6.2, §7). Those need an extraction library, a Gemini client, PDF/photo parsing and synthetic patients. The spec names LangExtract, Gemini Flash on Vertex, Docling and Synthea, but the project doesn't declare them yet.

Two facts found on 2026-10-16 change the details:
- `gemini-2.5-flash` and `gemini-2.5-flash-lite` retire on Vertex on **2026-10-20** (Vertex "Model versions" page).
- Gemini 3 and later models don't accept `thinking_budget` (deprecated, can return 400). They use `thinking_level`, whose lowest value is `MINIMAL`. Google says `MINIMAL` doesn't guarantee zero thinking. The project rule "thinking budget 0" can't be applied literally to any current Flash model.

## Decision

- **Runtime:** `langextract` (Apache-2.0, pinned) for grounded extraction; `google-genai` (Apache-2.0) for Gemini on Vertex AI.
- **Optional extra `ocr`:** `docling` (MIT) + `ocrmac` (MIT, Apple Vision OCR). The import is lazy, and the text path works without the extra. Install size and peak RAM are measured on the M2 before the extra is added; if they're too heavy, the fallback is `docling-serve` on the lab server.
- **Synthea:** the release jar is downloaded by `scripts/download_synthea.py` (pinned URL + SHA-256) into `data/raw/synthea/`, never committed, and run with Java 17 and a fixed seed.
- **Gemini model:** `gemini-3.5-flash` (retirement "May 19, 2027 or later") with `thinking_level=MINIMAL` for note generation and denial parsing. That's the closest equivalent of "thinking budget 0". The model id and thinking level live in config, so a later Flash model is a one-line change.
- **Billing:** a dedicated `pair` GCP project on the billing account that holds the $1,000 GenAI App Builder trial credit, with a $5 budget alert. Whether that credit pays for Gemini SKUs is unconfirmed (support said "search only"; the linked SKU group lists Gemini SKUs), so a sub-cent test call is checked in Billing > Reports before relying on it.

## Consequences

**Easier:**
- One SDK (`google-genai`) serves both LangExtract's Gemini path and our own JSON calls.
- The heavy OCR stack stays off machines that don't need it.

**Harder:**
- `MINIMAL` thinking still bills some thinking tokens. Phase 2 spend is estimated under $2, so the effect is small.
- Model ids churn every few months; the config value must be checked against the lifecycle page each phase.

## Alternatives Considered

1. **`gemini-2.5-flash` with `thinking_budget=0`**: rejected, retires 2026-10-20.
2. **`gemini-3.5-flash-lite`**: cheaper and defaults to `MINIMAL`, but weaker for realistic clinical notes. Kept as a config option for the denial parser.
3. **Docling as a core dependency**: rejected. It's 1 GB or more of PyTorch and models for a path Phase 2 doesn't need.

## Notes

- Docling measurement (2026-10-19, M2 8 GB, throwaway venv): docling 2.140.0 + ocrmac install to 1.1 GB; a one-page synthetic PDF converts in 33 s cold (76 s including the first model download) and 10 s warm, with a 2.1 GB peak memory footprint (730 MB resident). Judged acceptable for an optional extra that is never imported on the text path; the `ocr` extra was added. Keep Ollama stopped while it runs.
- Related: [ADR-0002](0002-local-first-with-gcp-burst.md), [ADR-0011](0011-llm-placement-lab-e4b-mac-e2b.md).
