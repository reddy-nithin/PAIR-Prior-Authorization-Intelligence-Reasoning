# ADR-0017: Test and dev case sets use different patients

**Status:** Accepted
**Date:** 2026-10-28
**Supersedes:** (none; changes how `scripts/generate_cases.py` picks patient profiles)

## Context

The dev set (`--seed 2027`) was meant to be held out from the test set (`--seed 2026`). The case audit on 2026-10-28 found it isn't. `generate_suite` gives case *i* the profile `profiles[i % len(profiles)]`, and the seed only changes planned values and note wording. So `cases-v3` and `cases-dev-v3` use the same 30 Synthea patients in the same slots, and 17 of 30 cases also have the same planned states. The dev set is a reworded copy of the test set.

This matters most in Phase 3. Conformal calibration needs calibration examples that are exchangeable with, but separate from, the test examples. A twin dev set would make the threshold look better than it is.

Synthea gives 40 living patients aged 65 or over (seed 2026, 40 generated).

## Decision

- Profiles stay sorted by Synthea id. The **test pool** is the first 30. The **dev pool** is the other 10.
- `generate_cases.py --split test|dev` picks the pool (`profile_pool` in `src/pair/eval/synth/profiles.py`). The default is `test`, which is exactly what the test set was built from, so `cases-v3` is unchanged and its audit and scores stay valid.
- An empty dev pool or an unknown split is an error, never a silent fallback to test patients.
- The dev set is regenerated as `data/cases-dev-v4` (`--seed 2027 --split dev`). Each dev patient appears in about 3 cases, across policies.

## Consequences

**Easier:** dev scores now say something about new patients. Phase 3 can split calibration and test by patient, not only by case.

**Harder:** 10 dev patients is a small pool, so dev results lean on those patients' histories. If that limits Phase 3, generate more Synthea patients into a separate dev pool (a new ADR, since it changes the data source).

**Not changed:** the test set, its critic audit, and the seeded gate set (built from test cases).
