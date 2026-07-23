# Current implementation status

Snapshot: 2026-07-16 after the complete Phase 4 Evaluation Layer. This file describes active source/tests/configuration. It is not normative. Recent retained runs predate the current complete-file implementation and are treated as legacy format evidence only.

## Status summary

| Area | Active behavior | Contract alignment |
| --- | --- | --- |
| Candidate | Frozen `Candidate` retains the pre-generation `strategy_prompt`, `previous_code`, and `generation_prompt`, stores normalized output separately as `generated_java`, and exposes first-class identity, operator, mutation, component provenance, failure, artifact, and timing fields. | The Phase 1 genotype/phenotype boundary and Phase 2 mutation state transitions are implemented; later validation/integration/match stages remain outside this milestone. |
| Java generation | One request asks for complete `ai.generated.CandidateAgent`; raw/fenced source is normalized and written once. | Complete-file boundary exists. Validation imposes a fixed template/marker/action-helper layout not required by the spec. |
| Crossover | `eagle/crossover.py` independently chooses all three components, takes Previous Code from the selected parent's `generated_java`, and records each selected parent ID. Search feedback routing uses recorded provenance rather than prompt equality. | Phase 1 inheritance and component provenance are implemented and deterministic under the EA RNG. |
| Mutation | Strategy and Code mutations use Reflection followed by prompt-only Rewrite and the existing final Java Generation stage. Rewritten prompts are candidate state; inherited previous Java remains distinct from the generated phenotype. | Phase 2C is implemented; later validation/integration/match stages remain outside this milestone. |
| Selection | Binary tournament, Pareto sorting, crowding distance, and elitist parent+offspring survivors operate on two objective values. | Broadly aligned; population manifests and tie behavior need contract tests. |
| Validation | Checks exact `ai.generated.CandidateAgent` identity, both constructors, `getAction`/`reset`/`clone`, forbidden capabilities, and unavailable imports with structured passed/failed/blocked results. | External runtime/security contract is implemented without fixed helper names, markers, or internal layout. |
| Compilation | Runs `javac -Xlint:all` in an isolated candidate directory with the MicroRTS classpath and persists stdout/stderr/command. | Structured, deduplicated diagnostics with severity/code/file/line/column are implemented; objective scoring remains a later milestone. |
| Integration | Runs a standalone seven-check MicroRTS probe (load, inheritance, constructors, reset, clone, getAction, PlayerAction) before matches, with fail-fast routing and timing/artifacts. | Implemented for mock and bounded real runtime probes; 10-match execution remains outside this milestone. |
| Match protocol | After standalone Integration, one source/class hash pair runs exactly 10 independently seeded, bounded matches against `ai.abstraction.LightRush`; each match persists complete result, telemetry, logs, replay/round-state references, failure, and timing. | Phase 4 protocol is implemented; no generation, mutation, validation, compilation, or integration work occurs inside the match batch. |
| `game_performance` | Canonical +100/0/-100 result scoring plus bounded tanh material/resource and survival shaping is aggregated across exactly 10 valid matches with full statistics. | Implemented by `evaluation/canonical_game_performance.py` and `evaluation/canonical_game_metrics.py`; partial/invalid batches yield -1000. |
| `code_quality` | Successful evaluation uses `500 + compilation_score + function_score + strategy_alignment_score`; failures use the canonical stage hierarchy. | Implemented with range [0,610], deterministic five-capability evidence, and independent 0-10 Strategy Alignment. |
| Failure handling | Runtime exception, illegal action, timeout, deadlock, crash, invalid/missing result, and partial evaluation are classified with retained match evidence and runtime-progress fitness. | Generation/validation/compilation/integration/runtime ordering is implemented and all failures receive `game_performance = -1000`. |
| Artifacts | Candidates persist canonical Phase 4 evaluation summaries, per-match artifacts, runtime failures, capability evidence, Strategy Alignment request/raw/parsed result, objective values, and schema/formula versions. | Evaluation-layer persistence is implemented; broader run-layout migration and compatibility cleanup remain later work. |
| LLM logging | Final-generation, Reflection, Rewrite, and Strategy Alignment calls retain raw responses and UTC/monotonic attempt timing. | Phase 4 alignment plus evaluation/match/objective timing are active; candidate-total and selection/crossover timing remain broader artifact work. |

## Active configuration

- `ExperimentConfig.matches_per_candidate` is fixed at `10`; every checked-in YAML resolves to the same value.
- `ai.abstraction.LightRush`, map, cycles, timeout, material/resource scales, unit values, and ten distinct deterministic or explicit seeds are resolved and persisted.
- The parser forces `ai.abstraction.LightRush` even if YAML names another opponent. `config.yaml` preserves the input, while `resolved_config.json` records the actual forced opponent.
- `alignment_backend` is active (`mock`, `openai`, or `llama_cpp`) and is independent from the generation call while sharing configured endpoint/model values when applicable.
- Resolved configuration records `artifact_schema_version = phase4-v1` and `objective_formula_version = eagle-objectives-phase4-v1`.
- Only `game_performance` and `code_quality` are active optimizer objectives; Strategy Alignment is a Code Quality component.

## Active tests

The suite now covers Phase 2C mutation, Phase 3 validation/compilation/integration, and Phase 4 runtime evaluation, canonical Game Performance, failure-aware Code Quality, Function Capability, Strategy Alignment, objective aggregation, artifacts, and timing. Focused Phase 4 tests prove exactly 10 seeded LightRush calls, one source/class set, no regeneration, timeout/invalid/partial failures, formula boundaries, successful and partial end-to-end persistence, and two-objective output.

The full WSL unit suite passes. A bounded real seven-check Integration probe exists from Phase 3; no real 10-match Java/MicroRTS batch was run for this implementation turn, so real-runtime gameplay remains unverified here.

## Recent run evidence

The most recent complete saved population run (`runs/20260712_154209_634218`) uses an obsolete split/function-body schema and `strategy_alignment` objective. `contract-smoke-*` and `code_quality_smoke` also predate the current complete-file boundary. Analysis tools may read them for migration testing, but no retained run is proof of current architecture compliance.

## Operational state

- `python scripts/run_eagle.py --config configs/eagle_minimal.yaml --mock` exercises the contract-shaped 10-match evaluation pipeline, but mock execution is not real MicroRTS proof.
- Real mode requires the local generation endpoint, `javac`, and vendored MicroRTS runtime.
- WSL is the project default for Python/Java/MicroRTS commands.
- `scripts/play_candidate_gui.py` retains transitional generated-class discovery and defaults to `ai.PassiveAI`; it is a manual viewer, not the evaluation protocol.

See [`architecture_gaps.md`](architecture_gaps.md) for required changes and [`migration_plan.md`](migration_plan.md) for dependency order.

## Final Test compatibility evidence (2026-07-23)

Pinned TMA, Mayari, and COAC sources build locally with Temurin 17, and all three expected classes pass the vendored MicroRTS load/constructor probe. TMA uses its unchanged entrypoint and active `strategiesV2` sources plus an explicit behavior-free package marker for a stale import; the adapter path and SHA-256 are persisted.

A real bounded smoke selected candidate `1ed41153d0c4` from completed mock-evolution run `20260723_092713_386247`, compiled it once, and completed six of six real MicroRTS matches on `basesWorkers8x8` (one seed, all three champions, both sides). The candidate lost all six matches; compatibility, evidence completeness, and stable source/class identity passed. The smoke is runtime proof, not performance evidence and not a formal 54-match Final Test.
