# Architecture gaps

## Deterministic DSL compiler decision (2026-10-14)

| ID | Gap | Decision | Verification | Status |
| --- | --- | --- | --- | --- |
| DSL-COMP-01 | Entity-target `move` endpoint and adjacent/self-target behavior | User explicitly decided that entity-target `move` uses the existing deterministic pathfinder to an adjacent position (range 1). Already adjacent, self-target and unreachable actions cannot issue and fall through; target filtering uses that same legal-step contract. Recorded in `prompts/strategy_dsl_reference.txt`. | Golden sources plus real adjacent/self-target/fallthrough fixtures in `tests/test_dsl_java_compiler.py`. | Resolved and implemented |
| DSL-COMP-02 | Gen 0 WorkerRush was only an approximate finite-rule policy | Reserve one checked-in `reference_agent: WorkerRush` seed; deterministic materialization delegates to and replays the vendored implementation, pins its source hash, and rejects reference agents from LLM-produced/evolved policies. | Multi-map, both-side, multi-cycle differential action test plus Gen 0 wiring/hash artifact test. | Resolved and implemented |
| FWSLOT-01 | Allow one generated full Java architecture while keeping candidate evolution bounded, reproducible, and controllable | Use an explicit one-time Groq structured bootstrap to create an exact versioned bundle; freeze its bytes/hash per run; expose only finite typed numeric or enumerated-expression slots; perform local deterministic sampling/crossover/mutation/rendering; disable all candidate-time LLM/reflection/repair; retain the normal validation and evaluation pipeline. | Bootstrap/core/config/candidate/materialization/artifact/resume contract tests. A live provider call and real MicroRTS smoke remain optional operational validation. | Resolved and implemented |

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

## Deterministic materialization verification (2026-10-14)

The typed compiler, dedicated return API, policy-only genotype, no-Java-LLM
materialization, artifact hashes, timing, and strict deterministic resume fences
are implemented. Legacy LLM manifests without a protocol field remain readable
when their resolved config has the supported LLM protocol. Golden source, real
Java/MicroRTS integration, and focused compatibility tests pass. The bounded
self-play smoke has complete semantic probes and matches; final repository-wide
regression results are recorded in `../testing/test_contracts.md`.

The local checkout lacks the fixed-roster AllInBot JAR, so the real smoke uses
the existing self-play protocol. No fitness/selection formula or third-party
MicroRTS behavior was changed.
