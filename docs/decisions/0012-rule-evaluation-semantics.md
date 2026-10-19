# ADR-0012: Rule evaluation semantics: three-valued logic and evidence binding

**Status:** Accepted
**Date:** 2026-10-16
**Supersedes:** (none; completes ADR-0008)

## Context

ADR-0008 left two things to Phase 2: how a missing value maps to "insufficient", and the exact meaning of `days_between` and `within_days`. The engine also needs rules for turning extracted `Evidence` into rule variables: negated, uncertain and conflicting mentions.

## Decision

**Three-valued (Kleene) logic.** A rule evaluates to True, False or Unknown (`None`).
- A variable with no usable evidence is `None`.
- A comparison or `in` test with a `None` operand is Unknown. `x is None` / `x is not None` always give True or False.
- `not Unknown` is Unknown. `and` is False if any operand is False, else Unknown if any is Unknown. `or` is True if any operand is True, else Unknown if any is Unknown.
- In a chained comparison, each link is evaluated and combined with `and`.
- `len(None)`, `any(None)` and `all(None)` are Unknown. `any`/`all` over a list of truth values use the same Kleene rules.
- `days_between(a, b)` is `(b - a).days`, so it's positive when `b` is later. `within_days(a, b, n)` is `0 <= (b - a).days <= n`. Any `None` argument gives Unknown.
- Criterion status: True → **met**, False → **unmet**, Unknown → **insufficient**. Checklist `logic` uses the same mapping over criterion outcomes and context flags.

**Evidence binding.**
- Only `asserted` evidence binds a value. `negated` and `uncertain` evidence stays in the rule trace but binds nothing.
- A bool variable states its own truth: "no radiculopathy" is extracted as `untreated_radiculopathy = False`, asserted.
- A list variable is the list of asserted items, or `None` if there are none. So "denies daytime sleepiness" alone leaves a symptom list Unknown (insufficient), not empty.
- If one variable gets two different asserted values (e.g. two AHI numbers), the criterion is **insufficient**, and the trace shows both spans. The engine never picks one.
- Rules must not guard with `is not None` when a missing value should mean insufficient. Under this logic the guard turns "missing" into unmet. The Phase 1 rules that did this are rewritten.

## Consequences

**Easier:**
- "Insufficient" falls out of the logic instead of special cases, and the gap list follows from it.
- One semantics serves both criterion rules and checklist `logic`.

**Harder:**
- Policy authors must know that `is not None` is definite. The loader can't detect a misused guard, so tests per policy cover the missing-value case.

## Alternatives Considered

1. **Missing value → False (two-valued)**: rejected. It reports "unmet" when the record is just silent, which tells a patient their appeal is hopeless when it's only incomplete.
2. **Pick the first or the most recent of conflicting values**: rejected. Silent choice hides the conflict the patient needs to resolve (plan §2.4).

## Notes

- Related: [ADR-0008](0008-rule-expression-language.md).
