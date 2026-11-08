# PAIR web app

The patient-facing demo (Phase 4, ADR-0023): 7 steps from a Medicare Advantage denial to a cited appeal letter.

- Cached mode reads `public/demo/` (published by `make demo-publish`, or `make demo-fixture` for the synthetic case). It needs no backend.
- Live mode calls the local API (`make api`, `NEXT_PUBLIC_PAIR_API`, default `http://127.0.0.1:8000`). Live results stay in this tab's memory only.

```bash
make demo-fixture          # from the repo root: publish the synthetic demo case
make demo                  # build and serve on http://127.0.0.1:3000
npm test                   # Vitest
npm run test:e2e           # Playwright: keyboard walkthrough + axe (desktop, phone, dark)
npm run check:types        # caseview.ts matches the Python CaseView schema
```

After a `CaseView` change: `uv run python scripts/export_caseview_schema.py && npm run gen:types`.
