# ADR-0026: Restyle the demo in Direction C, "Calm Companion"

**Status:** Accepted (Nithin, 2026-11-08)
**Date:** 2026-11-08
**Supersedes:** (none; amends the look of the Phase 4 demo from [ADR-0023](0023-phase-4-nextjs-demo-and-deps.md))

## Context

The Next.js demo was coded on 2026-10-29 from a plain clickable HTML prototype, because the Figma sign-in failed that day. On 2026-11-05 two full Figma directions were built in file `CBVYYmMQsWXAI6j5vMDrAA`: A, "Evidence Desk", and C, "Calm Companion". Each has 9 screens on desktop and phone. The comparison page recommended C as the base, with A's numbered sentences and side source panel on wide screens. The site was never restyled to match, so the public demo (ADR-0025) still showed the prototype look.

## Decision

- Restyle `web/` to Direction C. The tokens come from the Figma variables: warm paper background `#f7f3ee`, accent `#2f6f62`, and met, not-met and not-sure colours with their own backgrounds. Type is Figtree for headings, Atkinson Hyperlegible Next for reading, Literata for the letter and IBM Plex Mono for record quotes. Layout is one 760 px column, 56 px pill buttons and a path stepper with one dot per step.
- The letter screen widens to 1160 px. On wide screens it keeps A's numbered sentences beside a sticky source panel. On phones the panel stacks under the letter, and choosing a sentence scrolls to it.
- Dark mode gets its own C palette. Every status keeps an icon next to its words.
- The hosted copy lists the demo cases before the upload box, because visitors there can't upload.

## Consequences

- The public demo matches the poster screenshots.
- Data, steps, copy and behaviour are unchanged. The Vitest and Playwright suites pass as before: keyboard-only walkthrough, plus axe with 0 serious problems on desktop, phone and dark.
- Two copy strings were added: the tally labels and the missing-paper banner. Both pass the grade-8 copy test.

## Alternatives considered

- **Direction A only.** Rejected: on phones it reads as dense, and the comparison scored C higher for a stressed patient.
- **Leave the prototype look.** Rejected: it doesn't match the poster, and judges will open the demo.
