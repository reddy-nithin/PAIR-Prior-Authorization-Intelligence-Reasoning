# ADR-0008: Rule expression language for policy checklists

**Status:** Accepted
**Date:** 2026-10-15
**Supersedes:** (none)

## Context

Each criterion in a policy YAML carries a machine `rule`, and each checklist carries a `logic` string that combines criteria (spec §4). The spec example writes them as Python-like expressions, e.g. `ahi >= 15 or (5 <= ahi <= 14 and any(symptoms_or_comorbidity))`. The policy loader must reject a bad rule at startup, and the rule engine (Phase 2) must evaluate rules without ever running arbitrary code. Calling Python's `eval` on YAML text is unsafe.

## Decision

- Rules and `logic` are written in a **restricted subset of Python expression syntax**, parsed with the standard-library `ast` module (`mode="eval"`).
- Allowed nodes: names; int, float, str, bool and `None` literals; list literals; comparisons including chained ones (`5 <= x <= 14`); `and`, `or`, `not`; `in`, `not in`, `is None`, `is not None`; calls to a fixed set of helpers: `any`, `all`, `len`, `days_between`, `within_days`.
- Everything else fails at load time with `RuleSyntaxError`, naming the node type and column: attribute access, subscripts, lambdas, comprehensions, arithmetic, calls to any other name, keyword arguments.
- Each criterion declares the `variables` its rule reads, with a type (`number`, `bool`, `date`, `text`, `list`). A rule that reads an undeclared name is rejected.
- A checklist declares `context` flags that come from the case rather than the records (e.g. `initial: bool` for initial vs continued coverage). `logic` may only reference criterion ids and context flags.
- In Phase 1, rules are parsed and validated only. Phase 2 adds an evaluator that walks the same whitelisted tree.
- **Contract additions this requires (spec §4):** `Criterion` gains `variables` and `source_id` (which `PolicySource` its clause quotes), `Checklist` gains `context`, and `Evidence` gains `variable` (which rule variable its `value` supplies). Without them the engine can't bind extracted values to rule names, and the letter can't cite the right document.

## Consequences

**Easier:**
- Policy YAML stays readable by a non-programmer reviewer, close to the LCD wording.
- No new dependency. The validator and evaluator are small, fully unit-tested walkers over `ast`.
- A broken or unsafe rule fails before any case runs.

**Harder:**
- We own the evaluator, including three-valued logic for missing values (Phase 2 must define how `None` maps to "insufficient").
- Rules that need arithmetic (e.g. a percentage of nights) must go through a named helper rather than inline math.

## Alternatives Considered

1. **json-logic**: rejected. Rules become nested JSON that is hard to review against LCD text, and it adds a dependency.
2. **`eval` with restricted globals**: rejected. Known escapes make it unsafe, and it gives no load-time validation.
3. **A third-party safe-eval library (e.g. simpleeval)**: rejected. It allows more than we need (arithmetic, attribute access by default), and the whitelist is the point.

## Notes

- Related: [ADR-0006](0006-patient-side-appeal-copilot.md), [ADR-0007](0007-bayes-strength-score-with-explanation.md).
