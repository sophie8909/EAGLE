# Repository and responsibility map

This file maps active repository paths to responsibilities. It is descriptive, not an architecture source. Read [`../eagle_architecture_spec.md`](../eagle_architecture_spec.md) and the affected canonical contract before changing a module.

## Active paths

| Path | Current responsibility | Canonical contract to read |
| --- | --- | --- |
| `eagle/candidate.py` | Candidate dataclass and final generation request construction | [`../architecture/candidate_model.md`](../architecture/candidate_model.md), [`../architecture/java_generation.md`](../architecture/java_generation.md) |
| `eagle/config.py` | Config parsing/defaults and template validation | [`../operations/running_eagle.md`](../operations/running_eagle.md), affected formula/protocol docs |
| `eagle/search.py` | Run setup, initial population, operator order, evaluation loop | [`../architecture/evolutionary_flow.md`](../architecture/evolutionary_flow.md) |
| `eagle/selection.py` | Tournament selection, non-dominated sorting, crowding, survivors | [`../architecture/evolutionary_flow.md`](../architecture/evolutionary_flow.md) |
| `eagle/crossover.py` | Three-component Uniform Crossover | [`../architecture/crossover.md`](../architecture/crossover.md), [`../artifacts/lineage_schema.md`](../artifacts/lineage_schema.md) |
| `eagle/mutation.py` | Reflection/rewrite prompt construction and mutation records | [`../architecture/mutation.md`](../architecture/mutation.md) |
| `eagle/evaluation.py` | Candidate stage orchestration | [`../evaluation/evaluation_pipeline.md`](../evaluation/evaluation_pipeline.md), [`../evaluation/failure_classification.md`](../evaluation/failure_classification.md) |
| `eagle/artifacts.py` | Current run/candidate serialization | [`../artifacts/artifact_schema.md`](../artifacts/artifact_schema.md), timing/lineage docs |
| `eagle/llm_logging.py` | Current generation-attempt JSON logging | [`../artifacts/artifact_schema.md`](../artifacts/artifact_schema.md), [`../artifacts/timing_schema.md`](../artifacts/timing_schema.md) |
| `generation/backend.py` | Mock and OpenAI-compatible final-generation transport | [`../architecture/java_generation.md`](../architecture/java_generation.md) |
| `generation/java_agent_generator.py` | Full-source extraction, validation, and file writing | [`../architecture/java_generation.md`](../architecture/java_generation.md) |
| `generation/agent_template.py` | Current template and marker validation | [`../architecture/java_generation.md`](../architecture/java_generation.md) |
| `generation/parsing.py` | Secondary output parser; currently bypassed by active generator | [`current_status.md`](current_status.md) |
| `evaluation/compiler.py` | `javac` invocation | [`../architecture/java_generation.md`](../architecture/java_generation.md), [`../evaluation/code_quality.md`](../evaluation/code_quality.md) |
| `evaluation/microrts_runner.py` | Process command, per-match execution, telemetry persistence | [`../evaluation/evaluation_pipeline.md`](../evaluation/evaluation_pipeline.md), [`../artifacts/artifact_schema.md`](../artifacts/artifact_schema.md) |
| `eagle/final_test/` | Post-evolution selection, champion resolution, scheduling, execution, aggregation, artifacts, and configuration | [`../evaluation/final_test.md`](../evaluation/final_test.md) |
| `scripts/setup_final_test_opponents.py`, `scripts/run_final_test.py` | Reproducible champion preparation and final-test CLI entrypoint | [`../evaluation/final_test.md`](../evaluation/final_test.md) |
| `third_party/final_test_opponents/` | Pinned external manifests, legally redistributable adapters, ignored sources/builds/JARs, and resolved provenance | [`../evaluation/final_test.md`](../evaluation/final_test.md) |
| `evaluation/game_performance.py`, `evaluation/game_metrics.py` | Current telemetry and gameplay aggregation | [`../evaluation/game_performance.md`](../evaluation/game_performance.md) |
| `evaluation/code_quality.py` | Current deterministic scoring | [`../evaluation/code_quality.md`](../evaluation/code_quality.md), [`../evaluation/failure_classification.md`](../evaluation/failure_classification.md) |
| `evaluation/nsga2_objectives.py` | Current two-value objective dictionary | objective and failure docs |
| `scripts/run_eagle.py` | CLI entry point | [`../operations/running_eagle.md`](../operations/running_eagle.md) |
| `scripts/analyze_run.py` | Failure summary and legacy objective read compatibility | [`../operations/inspecting_runs.md`](../operations/inspecting_runs.md) |
| `scripts/analysis/plot_game_performance_by_generation.py` | Gameplay plotting/CSV export | [`../operations/inspecting_runs.md`](../operations/inspecting_runs.md) |
| `scripts/play_candidate_gui.py` | Manual GUI playback of an existing candidate | [`../operations/inspecting_runs.md`](../operations/inspecting_runs.md) |
| `tests/` | Current unit/integration-contract tests | [`../testing/test_contracts.md`](../testing/test_contracts.md) |
| `configs/` | Input configurations; currently non-conformant to the 10-match contract | [`../operations/running_eagle.md`](../operations/running_eagle.md) |
| `eagle/java_templates/CandidateAgent.java` | Current known-good complete-file seed/template | [`../architecture/java_generation.md`](../architecture/java_generation.md) |
| `third_party/microrts/` | Vendored runtime, maps, libraries, and Java entry points | [`../evaluation/evaluation_pipeline.md`](../evaluation/evaluation_pipeline.md) |

## Dependency direction target

```text
scripts -> eagle orchestration -> generation/evaluation operators
                           \-> artifact serializers

canonical docs -> implementation and tests
implementation status -> never a source for normative behavior
```

Scoring modules should return data and not own process execution. Artifact writers should serialize decisions and never compute them. Search should orchestrate operators and not contain operator-specific prompt logic.

## Legacy boundaries

- `runs/`, `logs/`, ignored generated Java, compiled MicroRTS classes, and archived caches are evidence only.
- `scripts/analyze_run.py` may read old `strategy_alignment` artifacts, but compatibility must not leak that name into active optimizer output.
- Current marker/helper scaffolding is implementation state, not a normative internal Java architecture.
- Do not restore surrogate or runtime-LLM components while migrating this contract.

