# ADR-0009: Data-layer dependencies for contracts, policies and IMR

**Status:** Accepted
**Date:** 2026-10-15
**Supersedes:** (none)

## Context

Phase 1 adds typed contracts, YAML policy checklists and a typed IMR loader. The spec stack (§7) names Pydantic v2 and "plain Python + YAML", and the exit check asks for a typed DataFrame. Those imply three runtime libraries the project doesn't declare yet. The EDA notebook also needs a kernel and plotting.

## Decision

- **Runtime:** `pydantic>=2` (contracts), `pyyaml` (policy files, loaded with `safe_load` only), `pandas` (IMR DataFrame with explicit dtypes).
- **Dev only:** `jupyter` (kernel + `nbconvert`) and `matplotlib` for `notebooks/`.
- **Dev only, type checking:** `pandas-stubs` and `types-pyyaml`, so `mypy --strict` keeps passing.
- Notebook outputs are stripped with `jupyter nbconvert --clear-output` through `make strip-notebooks`, and a hygiene test fails if a committed notebook has outputs. No `nbstripout` dependency.
- Downloads use the standard library (`urllib`, `zipfile`, `hashlib`). No HTTP client dependency.

## Consequences

**Easier:**
- Every library is mainstream and already in the scikit-learn / LightGBM ecosystem planned for Phase 3.
- Schema checks stay in our code (`IMR_SCHEMA`), so there is no extra validation framework to learn.

**Harder:**
- pandas is heavy for an 8 GB laptop if misused. The loader reads only the needed columns with explicit dtypes.
- Without a DataFrame validation library, schema checks are hand-written and must be tested.

## Alternatives Considered

1. **pandera for typed DataFrames**: rejected for now. It's one more dependency for a single table.
2. **polars**: rejected. scikit-learn and LightGBM examples assume pandas, and polars adds friction for little gain at about 30k rows.
3. **nbstripout**: rejected. The `nbconvert` command plus a test does the same with a dependency we already need.

## Notes

- Related: [ADR-0008](0008-rule-expression-language.md).
