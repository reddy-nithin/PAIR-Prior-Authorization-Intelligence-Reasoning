# ADR-0005: Scope FHIR work to CDS Hooks CRD only (not full Da Vinci PAS)

**Status:** Accepted
**Date:** 2026-04-21
**Supersedes:** Clarifies baseline blueprint-v2 §7 (FHIR Primer) and §8 Phase 4

## Context

Baseline blueprint-v2 mentions the Da Vinci PA ecosystem broadly: Coverage Requirements Discovery (CRD), Documentation Templates and Rules (DTR), and Prior Authorization Support (PAS). The user has no prior FHIR experience, and the full Da Vinci PAS implementation guide requires real payer-side infrastructure and partner integration — not feasible for a solo portfolio project.

The real portfolio value is demonstrating **FHIR literacy + CDS Hooks integration**, not achieving full Da Vinci compliance.

## Decision

Scope FHIR work for v1 to:

1. **Read FHIR R4 bundles** (Synthea → MIMIC) using the `fhir.resources` Python library
2. **Implement one CDS Hook:** `medication-prescribe` via Da Vinci CRD pattern
   - Expose `POST /cds-services/pa-check` endpoint
   - Accept a FHIR bundle, return a CDS Hooks Card JSON response
   - Response includes decision + evidence links
3. **Simulate the EHR side** with a Streamlit "fake EHR" page that triggers the hook

Explicitly **out of scope** for v1:
- Da Vinci DTR (form-filling workflows)
- Da Vinci PAS (end-to-end payer submission)
- Real EHR integration (Epic App Orchard, Cerner, etc.)
- FHIR R5 — stay on R4 where the IGs and tooling are mature

## Consequences

**Easier:**
- Scoped FHIR work fits in a single 2–3 week phase
- One weekend of learning (FHIR quickstart + CDS Hooks spec) is enough to start
- Clear, demonstrable artifact: "here's a CDS Hook endpoint, here's a fake EHR calling it"
- Honest framing in README: "CDS Hooks CRD implementation; full PAS integration is future work"

**Harder:**
- Can't truthfully claim "CMS-0057-F compliant" (full compliance needs PAS)
- Must be explicit in README about what is and isn't implemented
- Closes off a specific interview talking point (full Da Vinci PAS) unless expanded later

## Alternatives Considered

1. **Implement full Da Vinci PAS** — rejected: requires payer partner, weeks of IG reading, not solo-feasible
2. **Skip FHIR entirely, use proprietary JSON schemas** — rejected: loses the interoperability credibility that makes this project stand out
3. **FHIR R5 instead of R4** — rejected: R5 tooling still thin, R4 is what production systems use
4. **CDS Hooks without Da Vinci alignment** — rejected: aligning to CRD takes minimal extra work and gives a real standards story

## Notes

- Learning path (one weekend): HL7 FHIR Overview for Developers → CDS Hooks quickstart (cds-hooks.org) → Da Vinci CRD IG homepage skim
- Use HAPI FHIR public sandbox (`https://hapi.fhir.org/baseR4`) for ad-hoc queries during dev
- README disclaimer template: "PAIR implements the CDS Hooks CRD pattern for prior authorization. Full Da Vinci PAS implementation requires payer partner integration and is not included in this portfolio project."
