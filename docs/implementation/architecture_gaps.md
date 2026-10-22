# Architecture gaps

## Deterministic DSL compiler decision (2026-10-14)

| ID | Gap | Decision | Verification | Status |
| --- | --- | --- | --- | --- |
| DSL-COMP-01 | Entity-target `move` endpoint and adjacent/self-target behavior | User explicitly decided that entity-target `move` uses the existing deterministic pathfinder to an adjacent position (range 1). Already adjacent, self-target and unreachable actions cannot issue and fall through; target filtering uses that same legal-step contract. Recorded in `prompts/strategy_dsl_reference.txt`. | Golden sources plus real adjacent/self-target/fallthrough fixtures in `tests/test_dsl_java_compiler.py`. | Resolved and implemented |
| DSL-COMP-02 | Gen 0 WorkerRush was only an approximate finite-rule policy | Reserve one checked-in `reference_agent: WorkerRush` seed; deterministic materialization delegates to and replays the vendored implementation, pins its source hash, and rejects reference agents from LLM-produced/evolved policies. | Multi-map, both-side, multi-cycle differential action test plus Gen 0 wiring/hash artifact test. | Resolved and implemented |
| FWSLOT-01 | Allow one generated full Java architecture while keeping candidate evolution bounded, reproducible, and controllable | Use an explicit one-time Groq structured bootstrap to create an exact versioned bundle; freeze its bytes/hash per run; expose only finite typed numeric or enumerated-expression slots; perform local deterministic sampling/crossover/mutation/rendering; disable all candidate-time LLM/reflection/repair; retain the normal validation and evaluation pipeline. | Bootstrap/core/config/candidate/materialization/artifact/resume contract tests. A live provider call and real MicroRTS smoke remain optional operational validation. | Resolved and implemented |

## Framework Coach evolution decision (2026-10-15)

| ID | Question | Decision | Verification | Status |
| --- | --- | --- | --- | --- |
| FWSLOT-02 | Add model-guided genome choice without changing frozen framework materialization | Keep `framework.evolution_mode: local` as the default. Opt-in `llm_coach` uses the experiment model for complete initial genomes and the existing worst-match Commentator→Coach Strategy path. Optional `framework.coach_offspring_probability` selects an exclusive Coach route before crossover, independently of `mutation_rate`; `null` preserves legacy Coach behavior, while numeric values from `0.0` through `1.0` require `llm_coach` and are resume-fenced (`null` for missing legacy values). The Coach branch copies parent A's genome and requests a complete replacement without crossover or parent B. The traditional branch preserves configured `crossover_rate`/donor selection and local single-slot mutation at `mutation_rate`. Generation-zero genomes remain Coach-selected. Coach-routed offspring record their reproduction route. Coach responses use the exact bundle-hash-pinned `eagle-framework-selection-v1` genome; Java materialization stays `eagle-framework-slots-v1`. Raw responses precede parsing; attempts are bounded and timed; failed Coach mutation preserves the pre-Coach child genome and fails the child without fallback. | 67 focused WSL tests including exclusive routes, mock search/resume, candidate persistence, and config tamper rejection | Resolved and implemented; focused validation passed |

## Opponent-pool self-play decision (2026-10-17)

| ID | Question | Decision | Verification | Status |
| --- | --- | --- | --- | --- |
| SELFPLAY-POOL-01 | Replace active delayed birth-generation cohort scheduling and FIFO library eviction | Maintain a capacity-bounded pool with four permanent protected built-ins; admit novel eligible entries into free slots, then use seeded 18-match head-to-head duels to decide replacement. Generation zero uses all ten built-in sources in the stable slot schema; refresh contexts retain protected case IDs and sample six nonprotected members. Fence changed self-play resume behavior with `self_play_pool_policy: tournament-v1`. | 28 focused tests passed; broader regression: 105 tests, one skip; separate 36-match real runtime smoke. Full real evolutionary run not exercised. See the canonical [evaluation contract](../eagle_architecture_spec.md#9-evolution-evaluation). | Implemented; bounded validation passed |

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
conclusion only in its own materialization step, and bypasses ordinary final
generation while preserving both prompt genes. Canonical streamed assignment and
permanent primary/generation-server routing are implemented and
covered by contract tests. The historical immutable-cohort self-play schedule,
same-context parent refresh, and legacy-checkpoint migration were implemented
and covered at this baseline; the approved tournament-v1 replacement is tracked
above, implemented, and validated within the stated test scope. Self-play scalar
fitness, inclusive non-chained tolerance tiers, versioned map×phase behavior
probes, exact semantic caching/equivalence, and offline semantic analysis are
implemented and covered.
Historical gap rows remain available in Git history.

## Dependency-driven execution (2026-10-21)

| ID | Decision | Verification | Status |
| --- | --- | --- | --- |
| EXEC-STREAM-01 | Replace model switching and whole-batch barriers with fixed role endpoints, two server-origin request slots, canonical source-gated plan streaming, two preparation workers and one ten-worker match matrix. External primary/generation servers are never lifecycle-managed. Keep parent-score, AOS, survivor and persistence dependencies. | Source/mutation/match overlap, endpoint routing, ordering, interruption/drain, self-play dependencies and resume contracts. | Implemented |

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
