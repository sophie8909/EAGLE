# Architecture gaps

Snapshot: 2026-08-31.

The active architecture has one remaining non-blocking hardening gap.

| ID | Gap | Current behavior | Completion condition | Status |
| --- | --- | --- | --- | --- |
| G-13 | Fine-grained selection/crossover timing | Mutation, generation, validation, compilation, integration, evaluation, objective, generation, and match timing are persisted. Parent-selection and crossover durations remain candidate-local rather than a dedicated event schema. | Add dedicated event records only if analysis needs cross-run selection/crossover timing. | Partial / P3 |

All previously tracked candidate, crossover, mutation, evaluation, scoring,
artifact, runtime, prompt, and legacy-cleanup gaps are closed by the current
source and contract tests. Code Reflection additionally scopes Reviewer source
to the editable strategy region and uses deterministic reusable-rule deltas;
these are active contracts rather than open gaps. Historical gap rows remain
available in Git history.

## Gap update rule

Do not add a gap for an intentionally unsupported historical interface. Add a
gap only when executable source differs from the current architecture spec.
