# Repository and responsibility map

This map lists active executable owners. Removed compatibility files are not
kept as documentation entries.

## Entrypoints

| Path | Responsibility |
| --- | --- |
| `experiment.sh` | Positional wrapper for `python -m eagle experiment` |
| `analyze.sh` | Wrapper for `python -m eagle analyze` |
| `watchdog.sh` | Optional network-interface monitor; no model lifecycle ownership |
| `scripts/run_gui_match.py` | Optional read-only visual match inspection |
| `scripts/benchmark_match_workers.py` | Bounded mock/real MicroRTS match-worker benchmark |
| `scripts/test_llm_seed_restarts.py` | Restart-owned-server LLM seed stability comparison |

## Experiment and search

| Path | Responsibility |
| --- | --- |
| `eagle/__main__.py` | Dispatches `experiment`, `analyze`, and read-only `monitor` |
| `eagle/cli/monitor.py` | Local experiment monitor arguments and server lifecycle |
| `eagle/monitoring.py` | Canonical run status collection and read-only HTTP API |
| `eagle/cli/experiment.py` | Experiment arguments and exit codes |
| `eagle/cli/analyze.py` | Run selection and report dispatch |
| `eagle/experiment.py` | Config discovery, fresh/resumable folder-batch index, owned runtime, search/resume, final test, cleanup |
| `eagle/runtime/config.py` | Adapts the experiment model section to runtime settings |
| `eagle/runtime/processes.py` | Owned process start/reuse/switch/health/stop safety |
| `eagle/config.py` | File-only prompts, one execution mode, EA/model/evaluation validation |
| `eagle/evolution/runtime.py` | Shared fresh/resume LLM, mutation, and controller bootstrap |
| `eagle/evolution/search.py` | Fresh run initialization, generation loop, and finalization |
| `eagle/evolution/generation.py` | Shared fresh/resume generation ordering, evaluation, credit, selection, and persistence |
| `eagle/evolution/offspring.py` | Whole-generation assignment, reflection/rewrite, deferred Code materialization, evidence-parent lookup |
| `eagle/evolution/parent_refresh.py` | Phenotype-preserving fitness refresh and diagnostic rematerialization replicas/sidecars |
| `eagle/self_play.py` | Managed self-play opponent library, five-generation context selection, context hashes, resume loading, and selection guards |
| `eagle/operators/initialization.py` | Configured/LLM generation-zero policy construction and candidate-owned evidence |
| `eagle/evolution/resume.py` | v2 snapshot load/finalization around the shared generation step |
| `eagle/operators/selection.py` | Seeded ten-case lexicase parent selection and joint parent-plus-offspring survivor selection |
| `eagle/operators/adaptive.py` | Static and adaptive reflection-operator selection |

## Candidate and mutation

| Path | Responsibility |
| --- | --- |
| `eagle/candidate.py` | Candidate genotype, phenotype, lineage, failure, fitness, references |
| `eagle/operators/crossover.py` | Independent prompt and optional inherited-Java crossover with provenance |
| `eagle/operators/reflection.py` | Reflection context and transport contracts |
| `eagle/operators/prompt.py` | Prompt-only mutation rewrite |
| `eagle/operators/code.py` | Diagnosis-guided direct parent-Java Code Reflection |
| `eagle/operators/strategy.py` | Match sampling, Commentator, Coach, trace lifecycle |
| `eagle/operators/context.py` | Structured mutation evidence |
| `eagle/operators/reflection_prompts.py` | Prompt Reflection reviewer rendering |
| `eagle/prompts.py` | Prompt manifest loading, rendering, and bounds |
| `eagle/strategy_diversity.py` | Strategy signature/niche/archive diagnostics |

## Generation and evaluation

| Path | Responsibility |
| --- | --- |
| `eagle/generation/backend.py` | Mock/OpenAI-compatible complete-source generation |
| `eagle/generation/java_agent_generator.py` | Complete-source extraction, envelope checks, canonical assembly, validation, source persistence |
| `eagle/generation/agent_template.py` | Java template and canonical scaffold assembly contract |
| `eagle/java_templates/CandidateAgent.java` | Hardened fixed scaffold for offspring decoding |
| `eagle/java_seeds/CandidateAgent.java` | Shared callable no-op seed and configured inherited-mode scaffold |
| `eagle/java_seeds/worker_rush/CandidateAgent.java` | Fixed Worker Rush generation-zero phenotype for mixed-policy initialization |
| `eagle/evaluation/pipeline.py` | Population/candidate evaluation, objectives, timing and result assembly |
| `eagle/evaluation/records.py` | Typed cross-stage evaluation/decoder/opponent records |
| `eagle/evaluation/decoding.py` | Bounded Java decoding, validation, compilation, diagnostic repair and class promotion |
| `eagle/evaluation/opponents.py` | Fixed/self-play pools, prerequisite checks and opponent compilation |
| `eagle/evaluation/matches.py` | Ordered matrix dispatch with configured match workers |
| `eagle/evaluation/compiler.py` | Isolated javac and diagnostics |
| `eagle/evaluation/microrts_runner.py` | Standalone seven-check integration probe only |
| `eagle/evaluation/runtime_evaluation.py` | Sole MicroRTS match process owner |
| `eagle/evaluation/match_trace.py` | Sole compressed tick-stream format and integrity report |
| `eagle/evaluation/match_matrix.py` | Opponent/map/round/side schedule |
| `eagle/evaluation/game_performance.py` | Per-match Game Performance formula |
| `eagle/evaluation/game_metrics.py` | Matrix aggregation and compact summaries |
| `eagle/evaluation/code_quality.py` | Static metrics and canonical simplicity diagnostic |
| `eagle/evaluation/function_capability.py` | Standalone Function Capability helper; not called by normal evaluation |
| `eagle/evaluation/strategy_alignment.py` | Standalone Strategy Alignment helper; not called by normal evaluation |
| `eagle/evaluation/objectives.py` | Ten opponent fitness cases and reporting aggregate |
| `eagle/evaluation/parent_offspring.py` | Head-to-head AOS evidence only |

## Persistence and analysis

| Path | Responsibility |
| --- | --- |
| `eagle/artifacts.py` | Candidate/stage artifact serialization |
| `eagle/run_artifacts.py` | v2 manifest, compact generation, candidate reconstruction, atomic writes |
| `eagle/timing.py` | Timing events |
| `eagle/analysis/loader.py` | v2-only run discovery and bounded materialization |
| `eagle/analysis/report.py` | Survivor-snapshot-aligned CSV/JSON/Markdown/PNG reports |
| `eagle/final_test.py` | Post-search final evaluation; never fitness |

## Configuration and assets

| Path | Responsibility |
| --- | --- |
| `configs/experiments/*/*.yaml` | Production/static definitions plus generated directory-batch `experiment.yaml` indexes |
| `prompts/manifest.toml` | Prompt metadata and placeholder contracts only |
| `prompts/*.txt` | One executable prompt body per file |
| `third_party/microrts/` | Vendored MicroRTS runtime/maps/libraries |
| `third_party/final_test_opponents/` | Final-test opponent dependencies |
| `third_party/gui_opponents/` | Optional GUI/external opponent assets |

## Editing an EA operator

| Change | Start here |
| --- | --- |
| Initial policies | `eagle/operators/initialization.py` |
| Parent/survivor selection | `eagle/operators/selection.py` |
| Component crossover | `eagle/operators/crossover.py` |
| Reflection choice or adaptive credit | `eagle/operators/adaptive.py` |
| Strategy mutation | `eagle/operators/strategy.py` |
| Prompt mutation | `eagle/operators/prompt.py` |
| Code mutation | `eagle/operators/code.py` |
| Operator evidence | `eagle/operators/context.py`, `eagle/operators/reflection_prompts.py` |
| Phase order | `eagle/evolution/generation.py`, `eagle/evolution/offspring.py` |

All executable Python belongs to the `eagle` package. Internal callers import the actual owner; removed paths have no compatibility shim. Assets/config/checkpoint paths retain their existing contracts. The [refactor plan](maintainability_refactor_plan.md) records the migration.

## Dependency direction

```text
experiment/analyze entrypoints
  -> lifecycle/search/analysis orchestration
    -> mutation/generation/evaluation
      -> artifact and timing owners
```

Scoring modules return data, artifact modules persist it, search owns population
transitions, and prompt resources remain outside executable Python source.
