# Architecture gaps

## DSL and pre-crossover source contract (2026-10-11)

The [integration plan](dsl_pre_crossover_reflection_plan.md) tracks DSL/source-gate
verification. Historical closed gaps do not certify the new contract: source,
artifacts, tests, configuration, and resume must agree before closure.

Historical baseline snapshot: 2026-09-24.

That baseline retained one non-blocking hardening gap. Current DSL/source-gate
closure and validation are tracked in the integration plan above.

| ID | Gap | Current behavior | Completion condition | Status |
| --- | --- | --- | --- | --- |
| G-13 | Fine-grained selection/crossover timing | Mutation, generation, validation, compilation, integration, evaluation, objective, generation, and match timing are persisted. Parent-selection and crossover durations remain candidate-local rather than a dedicated event schema. | Add dedicated event records only if analysis needs cross-run selection/crossover timing. | Partial / P3 |

Previously tracked candidate, crossover, mutation, evaluation, scoring,
artifact, runtime, prompt, and legacy-cleanup gaps were closed at that baseline. Prompt Reflection scopes Reviewer source to the
editable strategy region and uses deterministic reusable-rule deltas. Code
Reflection persists a structured diagnosis, revises parent Java from that
conclusion only in the final materialization phase, and bypasses ordinary final
generation while preserving both prompt genes. Whole-generation assignment and
optional primary/generation-model phase switching are also implemented and
covered by contract tests. Explicit immutable-snapshot self-play, same-context
parent refresh, legacy-checkpoint resume migration, and per-policy
generation-zero Java decoding are implemented and covered as active contracts.
Self-play scalar fitness, inclusive non-chained tolerance tiers, versioned
map×phase behavior probes, exact semantic caching/equivalence, and offline
semantic analysis are also implemented and covered.
These are active contracts rather than open gaps.
Historical gap rows remain available in Git history.

## Gap update rule

Do not add a gap for an intentionally unsupported historical interface. Add a
gap only when executable source differs from the current architecture spec.
