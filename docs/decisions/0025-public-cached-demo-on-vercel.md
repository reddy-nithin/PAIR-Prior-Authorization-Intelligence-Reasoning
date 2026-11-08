# ADR-0025: Put the cached demo on Vercel for Hack-a-Roo

**Status:** Accepted (Nithin, 2026-11-08)
**Date:** 2026-11-08
**Supersedes:** (none; moves the "public Vercel deploy" item of [ADR-0023](0023-phase-4-nextjs-demo-and-deps.md) forward from Phase 5)

## Context

The Hack-a-Roo poster is due 2026-11-09. The event asks only for a 48 x 36 inch PDF poster. A QR code on the poster lets judges open a working demo on their phones, which supports the "completeness and technical execution" score. ADR-0023 left the public deploy to Phase 5.

The cached demo is static JSON plus DOCX and PDF files, so it runs on Vercel with no backend. By default the start page also calls the local API at `http://127.0.0.1:8000` to see whether live mode is on. On a public site that call fails, and some browsers ask visitors for permission to reach their local network.

## Decision

- Deploy `web/` to Vercel with `NEXT_PUBLIC_PAIR_API` set to an empty string. When it is empty, the app makes no calls to a local API, and the upload panel says the online copy has demo cases only.
- Deploy from the laptop with the Vercel CLI, after `make demo-verify` and `make demo-publish`. The demo files stay gitignored. Whether to commit them or build them at deploy time is still a Phase 5 question.
- Live mode is unchanged and stays laptop only. Uploads never reach Vercel.

## Consequences

- Judges and readers can try the four synthetic demo cases from a link.
- Each deploy has to be run by hand from a machine that holds a verified demo cache.
- The demo files on the site are public. They are synthetic (Synthea patients, generated notes), and no real records are used.

## Alternatives considered

- **GitHub link only.** Rejected: judges would see code but not the product.
- **Commit the demo JSON and let Vercel build from Git.** Deferred to Phase 5, as ADR-0023 planned.
