# Current implementation status

Snapshot: 2026-07-15 after Phase 2A Reflection Framework. This file describes active source/tests/configuration. It is not normative. Recent retained runs predate the current complete-file implementation and are treated as legacy format evidence only.

## Status summary

| Area | Active behavior | Contract alignment |
| --- | --- | --- |
| Candidate | Frozen `Candidate` retains the pre-generation `strategy_prompt`, `previous_code`, and `generation_prompt`, stores normalized output separately as `generated_java`, and exposes first-class identity, operator, mutation, component provenance, failure, artifact, and timing fields. | The Phase 1 genotype/phenotype boundary is implemented; later stages still need to populate the complete artifact/timing records. |
| Java generation | One request asks for complete `ai.generated.CandidateAgent`; raw/fenced source is normalized and written once. | Complete-file boundary exists. Validation imposes a fixed template/marker/action-helper layout not required by the spec. |
| Crossover | `eagle/crossover.py` independently chooses all three components, takes Previous Code from the selected parent's `generated_java`, and records each selected parent ID. Search feedback routing uses recorded provenance rather than prompt equality. | Phase 1 inheritance and component provenance are implemented and deterministic under the EA RNG. |
| Mutation | Strategy and Code Reflection use a typed LLM backend abstraction with bounded retries, full evidence prompts, raw response persistence, and per-attempt timing. Phase 2A intentionally leaves prompts unchanged; Rewrite is not active yet. | Reflection framework is implemented; Rewrite and final three-call mutation remain for Phase 2B/2C. |
| Selection | Binary tournament, Pareto sorting, crowding distance, and elitist parent+offspring survivors operate on two objective values. | Broadly aligned; population manifests and tie behavior need contract tests. |
| Validation | Requires exact package/class/superclass text, strategy markers, helper markers, six helper declarations, translation call, and a small forbidden-pattern set. | Over-constrains internal layout and under-specifies the full external runtime/security contract. |
| Compilation | Runs `javac` in an isolated candidate directory with MicroRTS classpath. | No `-Xlint`; diagnostics are parsed from matching lines, not structured/deduplicated/capped consistently. |
| Integration | No distinct pre-match integration stage. Load/constructor/signature failures surface through the match process. | Missing. |
| Match protocol | Sequential loop uses player 0 vs forced LightRush, fixed 8x8 map, configurable match count, no seed, and no subprocess timeout. | Opponent/side broadly aligned; active configs run 1 or 3 matches, not 10, and do not provide distinct seeds. |
| `game_performance` | Current score combines ±100/0 result with unbounded average state, final resource difference, and up to 200 survival points, then averages successful matches. | Conflicts with the bounded canonical formula. |
| `code_quality` | Deterministic sum of compile score, marked-region ±100, and static text metrics. `strategy_consistency` is always `None`. | Does not implement failure-stage ranges, capability scoring, or alignment LLM. |
| Failure handling | Generation/validation, compile, and match failures receive first-class `failure_stage`/`failure_reason` plus legacy categories. Game failure is `-1000`; code quality comes from the current component sum. | State retention is aligned, but the required failure-score hierarchy and integration/runtime progress formulas remain missing. |
| Artifacts | Candidates additionally persist Reflection request/raw-response attempt files, mutation metadata, and candidate timing. | Phase 2A reflection evidence is durable; rewrite/generation attempt trees and full timing remain later Phase 2 work. |
| LLM logging | Final-generation and Reflection attempts write UTC-stamped JSON; Reflection retries are logged per stage. | Rewrite/alignment calls and complete generation timing remain absent. |

## Active configuration

- `ExperimentConfig.matches_per_candidate` defaults to `1`.
- Checked-in YAMLs specify `1` or `3`, never `10`.
- The parser forces `ai.abstraction.LightRush` even if YAML names another opponent. `config.yaml` preserves the input, while `resolved_config.json` records the actual forced opponent.
- `alignment_backend` remains in YAML files but is ignored by the dataclass/parser.
- Map and match seed are not configuration fields; resolved configuration records the hard-coded 8x8 map and explicitly marks match seeds unsupported/null.
- Resolved configuration records the Phase 1 artifact schema, the active legacy objective-formula identifier, EA/LLM/retry values, and Git commit. Prompt version remains explicitly unsupported/null.

## Active tests

The test suite covers current config parsing, LightRush forcing, complete template/marker/helper validation, one-file mock generation, genotype/phenotype separation, generated-Java inheritance, all eight crossover provenance combinations including equal text, seed/copy/crossover/mutation lineage serialization, canonical Phase 1 artifacts, resolved runtime values, current mutation preservation, NSGA-II helpers, current gameplay arithmetic, current deterministic code quality, legacy analysis, and final-generation HTTP logging/retries.

It does not prove the architecture contract's real two-stage LLM mutations, external-only Java validation, integration stage, 10-match/no-regeneration invariant, bounded objective formulas, failure hierarchy, full artifact/timing schema completion, schema migration/readback, or current-source real MicroRTS end-to-end behavior.

## Recent run evidence

The most recent complete saved population run (`runs/20260712_154209_634218`) uses an obsolete split/function-body schema and `strategy_alignment` objective. `contract-smoke-*` and `code_quality_smoke` also predate the current complete-file boundary. Analysis tools may read them for migration testing, but no retained run is proof of current architecture compliance.

## Operational state

- `python scripts/run_eagle.py --config configs/eagle_minimal.yaml --mock` is a current smoke path, not architecture validation.
- Real mode requires the local generation endpoint, `javac`, and vendored MicroRTS runtime.
- WSL is the project default for Python/Java/MicroRTS commands.
- `scripts/play_candidate_gui.py` retains transitional generated-class discovery and defaults to `ai.PassiveAI`; it is a manual viewer, not the evaluation protocol.

See [`architecture_gaps.md`](architecture_gaps.md) for required changes and [`migration_plan.md`](migration_plan.md) for dependency order.
