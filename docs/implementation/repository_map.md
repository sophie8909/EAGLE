# Repository and responsibility map

The local experiment control surface lives in `eagle/cli/gui.py` and
`eagle/cli/gui.html`; `eagle/gui_data.py` owns config editing and read-only
run/generation browsing. `gui.sh` launches on Ubuntu, `gui.cmd` on native
Windows, and `gui-wsl.cmd` through WSL. `eagle/interrupts.py` shares CLI cleanup
signals, including waking Windows blocking waits on Ctrl+Break. The GUI
delegates execution to the existing experiment CLI and visual
inspection script rather than owning evolution or evaluation behavior.

This map lists active executable owners. Removed compatibility files are not
kept as documentation entries.

## Entrypoints

| Path | Responsibility |
| --- | --- |
| `experiment.sh` | Positional wrapper for `python -m eagle experiment` |
| `analyze.sh` | Wrapper for `python -m eagle analyze` |
| `watchdog.sh` | Optional network-interface monitor; no model lifecycle ownership |
| `scripts/run_gui_match.py` | Optional read-only visual match inspection |
| `scripts/test_llm_seed_restarts.py` | Restart-owned-server LLM seed stability comparison |

## Experiment and search

| Path | Responsibility |
| --- | --- |
| `eagle/__main__.py` | Dispatches `experiment`, `analyze`, read-only `monitor`, and standalone compatibility Groq framework bootstrap |
| `eagle/cli/framework.py` | Standalone compatibility Groq framework-bootstrap arguments and exit codes |
| `eagle/cli/monitor.py` | Local experiment monitor arguments and server lifecycle |
| `eagle/monitoring.py` | Canonical run status collection and read-only HTTP API |
| `eagle/cli/experiment.py` | Experiment arguments and exit codes |
| `eagle/cli/analyze.py` | Run selection and report dispatch |
| `eagle/experiment.py` | Config discovery, fresh/resumable folder-batch index, experiment-scoped shared framework bootstrap binding, owned runtime, search/resume, final test, cleanup |
| `eagle/experiment_index.py` | Shared index recognition/schema validation for batch execution and GUI config protection; no execution dependencies |
| `eagle/execution.py` | Fixed concurrency, canonical worker routing, and shared per-server request budgets |
| `eagle/runtime/config.py` | Adapts the experiment model section to runtime settings |
| `eagle/runtime/processes.py` | Owned process start/reuse/switch/health/stop safety |
| `eagle/config.py` | File-only prompts, Java materialization and candidate Java modes, framework evolution policy, EA/model/evaluation validation |
| `eagle/evolution/framework_reflection.py` | Refresh-boundary whole-framework reflection, batch Coach transition, compilation probes, immutable version publication, and parent replicas |
| `eagle/evolution/runtime.py` | Shared fresh/resume LLM, mutation, and controller bootstrap |
| `eagle/evolution/search.py` | Fresh run creation plus shared fresh/startup-checkpoint generation-zero initialization/evaluation and failure/interruption marking |
| `eagle/evolution/loop.py` | Shared fresh/resume generation loop, state propagation, finalization, and `SearchResult` |
| `eagle/evolution/generation.py` | Shared fresh/resume streaming offspring preparation, evaluation, credit, selection, and persistence |
| `eagle/evolution/offspring.py` | Canonical source-gated plan stream, per-plan mutation/revision, mode-aware variation and evidence |
| `eagle/evolution/parent_refresh.py` | Phenotype-preserving fitness refresh and diagnostic rematerialization replicas/sidecars |
| `eagle/opponent_pool.py` | Tournament-v1 pool admission, deduplication, seeded promotion, and pool persistence |
| `eagle/self_play.py` | Immutable self-play context construction, snapshot/resume, and selection guards; legacy cohort helpers remain only for historical inspection (see the [architecture spec](../eagle_architecture_spec.md#9-evolution-evaluation)) |
| `eagle/operators/initialization.py` | Configured/LLM generation-zero policy construction, authored framework strategy profiles, description-guided Coach initialization, and evidence |
| `prompts/framework_initial_strategies.txt` | Registered ten-profile natural-language initial strategy set, including faithful vendored WorkerRush |
| `eagle/operators/framework_slots.py` | Seeded per-slot crossover, one-slot mutation, and exact slot provenance |
| `eagle/operators/framework_coach.py` | Framework initial-genome and Coach selection schemas, prompts, and strict validation |
| `eagle/evolution/resume.py` | Resume fences, frozen-framework/atomic-generation checkpoint restoration, partial-work archival, and handoff to generation zero or the shared loop |
| `eagle/operators/selection.py` | Seeded ten-case lexicase parent selection and joint parent-plus-offspring survivor selection |
| `eagle/operators/adaptive.py` | Static and adaptive reflection-operator selection |

## Candidate and mutation

| Path | Responsibility |
| --- | --- |
| `eagle/strategy_dsl.py` | Versioned closed-vocabulary strategy DSL validation and canonical JSON normalization; no runtime interpreter |
| `docs/implementation/dsl_pre_crossover_reflection_plan.md` | Staged DSL and independent reproduction-source gate integration plan |
| `eagle/candidate.py` | Candidate genotype, phenotype, lineage, failure, fitness, references |
| `eagle/operators/crossover.py` | LLM-mode independent prompt and optional inherited-Java crossover with provenance; deterministic whole-policy variation |
| `eagle/operators/reflection.py` | Reflection context and transport contracts |
| `eagle/operators/prompt.py` | Prompt-only mutation rewrite |
| `eagle/operators/code.py` | LLM-mode diagnosis-guided direct parent-Java Code Reflection |
| `eagle/operators/strategy.py` | Match sampling, Commentator, DSL/framework Coach roles, trace lifecycle |
| `eagle/operators/context.py` | Structured mutation evidence |
| `eagle/operators/reflection_prompts.py` | Prompt Reflection reviewer rendering |
| `eagle/prompts.py` | Prompt manifest loading, rendering, and bounds |
| `eagle/strategy_diversity.py` | Strategy signature/niche/archive diagnostics |

## Generation and evaluation

| Path | Responsibility |
| --- | --- |
| `eagle/generation/backend.py` | LLM-mode mock/OpenAI-compatible complete-source generation |
| `eagle/generation/groq_framework.py` | Shared fresh-run multi-provider/standalone Groq structured bootstrap, bounded attempt evidence, and normalized bundle publication |
| `eagle/generation/codex_framework.py` | One-shot read-only Codex CLI framework bootstrap with schema-constrained output and durable process evidence |
| `eagle/generation/framework_slots.py` | Strict bundle/genome validation, finite domains, hashing, seeded sampling, and deterministic marker rendering |
| `eagle/generation/framework_reflection.py` | Whole-bundle local-model reflection and batch Coach genome requests, raw evidence, bounded diagnostic-guided repairs, and fallback |
| `eagle/generation/java_agent_generator.py` | LLM-mode complete-source extraction, envelope checks, canonical assembly, validation, source persistence |
| `eagle/generation/agent_template.py` | Java template and canonical scaffold assembly contract |
| `eagle/java_templates/CandidateAgent.java` | Hardened fixed scaffold for offspring decoding |
| `eagle/java_seeds/CandidateAgent.java` | Shared callable no-op seed and configured inherited-mode scaffold |
| `eagle/java_seeds/worker_rush/CandidateAgent.java` | Fixed Worker Rush generation-zero phenotype for mixed-policy initialization |
| `eagle/evaluation/pipeline.py` | Population/candidate evaluation, objectives, timing and result assembly |
| `eagle/evaluation/records.py` | Typed cross-stage evaluation/decoder/opponent records |
| `eagle/evaluation/decoding.py` | Bounded Java decoding, validation, compilation, diagnostic repair and class promotion |
| `eagle/evaluation/opponents.py` | Fixed/self-play pools, prerequisite checks and opponent compilation |
| `eagle/evaluation/matches.py` | Ordered matrix dispatch with the fixed match-worker count |
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
| `eagle/fixed_evaluation.py` | Separate fixed-protocol evaluation of exact cross-generation snapshots; no search mutation |

## Configuration and assets

| Path | Responsibility |
| --- | --- |
| `configs/experiments/*/*.yaml` | Production/static definitions plus generated `eagle-experiment-index-v1` directory-batch indexes |
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
| Independent Code source gate / corrective Java | `eagle/operators/code.py` |
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


### Deterministic Java compiler

`eagle/generation/dsl_java_compiler.py` owns normalized strategy DSL to Java
compilation, typed IR emission, deterministic diagnostics, and policy/scaffold/
source hashes. `eagle/evaluation/decoding.py` owns materialization, validation, and javac.
`eagle/evaluation/pipeline.py` owns subsequent Integration, semantic probes,
and match evaluation for either materialization mode.
