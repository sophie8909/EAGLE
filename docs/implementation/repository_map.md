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

## Experiment and search

| Path | Responsibility |
| --- | --- |
| `eagle/__main__.py` | Dispatches only `experiment` and `analyze` |
| `eagle/cli/experiment.py` | Experiment arguments and exit codes |
| `eagle/cli/analyze.py` | Run selection and report dispatch |
| `eagle/experiment.py` | Config discovery, fresh/resumable folder-batch index, owned runtime, search/resume, final test, cleanup |
| `eagle/runtime/config.py` | Adapts the experiment model section to runtime settings |
| `eagle/runtime/processes.py` | Owned process start/reuse/switch/health/stop safety |
| `eagle/config.py` | File-only prompts, one execution mode, EA/model/evaluation validation |
| `eagle/search_runtime.py` | Shared fresh/resume LLM, mutation, and controller bootstrap |
| `eagle/search.py` | Initialization and evolutionary generation loop |
| `eagle/initial_population.py` | Configured/LLM generation-zero policy construction and candidate-owned evidence |
| `eagle/resume.py` | v2 snapshot resume |
| `eagle/selection.py` | Seeded ten-case lexicase parent selection and joint parent-plus-offspring survivor selection |
| `eagle/aos.py` | Static and adaptive reflection-operator selection |

## Candidate and mutation

| Path | Responsibility |
| --- | --- |
| `eagle/candidate.py` | Candidate genotype, phenotype, lineage, failure, fitness, references |
| `eagle/crossover.py` | Independent prompt and optional inherited-Java crossover with provenance |
| `eagle/mutation.py` | Reflection context and transport contracts |
| `eagle/rewrite.py` | Prompt-only mutation rewrite |
| `eagle/strategy_reflection.py` | Match sampling, Commentator, Coach, trace lifecycle |
| `eagle/reflection_context.py` | Structured mutation evidence |
| `eagle/reflection_prompts.py` | Code Reflection prompt rendering |
| `eagle/prompts.py` | Prompt manifest loading, rendering, and bounds |
| `eagle/strategy_diversity.py` | Strategy signature/niche/archive diagnostics |

## Generation and evaluation

| Path | Responsibility |
| --- | --- |
| `generation/backend.py` | Mock/OpenAI-compatible complete-source generation |
| `generation/java_agent_generator.py` | Complete-source extraction, envelope checks, canonical assembly, validation, source persistence |
| `generation/agent_template.py` | Java template and canonical scaffold assembly contract |
| `eagle/java_templates/CandidateAgent.java` | Hardened fixed scaffold for offspring decoding |
| `eagle/java_seeds/CandidateAgent.java` | Shared callable no-op seed and configured inherited-mode scaffold |
| `eagle/java_seeds/worker_rush/CandidateAgent.java` | Fixed Worker Rush generation-zero phenotype for mixed-policy initialization |
| `eagle/evaluation.py` | Canonical child evaluation orchestration |
| `evaluation/compiler.py` | Isolated javac and diagnostics |
| `evaluation/microrts_runner.py` | Standalone seven-check integration probe only |
| `evaluation/runtime_evaluation.py` | Sole MicroRTS match process owner |
| `evaluation/match_trace.py` | Sole compressed tick-stream format and integrity report |
| `evaluation/match_matrix.py` | Opponent/map/round/side schedule |
| `evaluation/game_performance.py` | Per-match Game Performance formula |
| `evaluation/game_metrics.py` | Matrix aggregation and compact summaries |
| `evaluation/code_quality.py` | Static metrics and canonical simplicity diagnostic |
| `evaluation/function_capability.py` | Function-capability diagnostic |
| `evaluation/strategy_alignment.py` | Strategy-alignment diagnostic |
| `evaluation/objectives.py` | Ten opponent fitness cases and reporting aggregate |
| `evaluation/parent_offspring.py` | Head-to-head AOS evidence only |

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

## Dependency direction

```text
experiment/analyze entrypoints
  -> lifecycle/search/analysis orchestration
    -> mutation/generation/evaluation
      -> artifact and timing owners
```

Scoring modules return data, artifact modules persist it, search owns population
transitions, and prompt resources remain outside executable Python source.
