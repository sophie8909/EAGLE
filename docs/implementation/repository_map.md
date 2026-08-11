# Repository and responsibility map

This is the current executable repository map. The only user-facing entrypoints
are `run_env.sh`, `run.sh`, `analyze.sh`, and `watchdog.sh`. Python modules are
grouped below by the entrypoint dependency closure; files outside that closure
are not part of the runtime contract.

## Entrypoints

| Path | Responsibility | Calls |
| --- | --- | --- |
| `run_env.sh` | Start, stop, restart, inspect, or health-check the one local LLM server | `python -m eagle runtime` |
| `run.sh` | Validate experiment/runtime configuration and run or resume EA search | `python -m eagle run` |
| `analyze.sh` | Select a canonical run and generate offline CSV/JSON/Markdown/PNG reports | `python -m eagle analyze` |
| `watchdog.sh` | Poll the local default-route network interface and recover it with `ip link` | Shell commands only; no Python or LLM lifecycle |

`scripts/run_gui_match.py` is a retained, read-only visual inspection utility,
not a fifth EA entrypoint. `scripts/setup_allibot.py` and
`scripts/allibot_llama_cpp_adapter.py` prepare its optional AlliBot dependency.

## Python command and orchestration layer

| Path | Responsibility |
| --- | --- |
| `eagle/__main__.py` | Dispatches only `runtime`, `run`, and `analyze`. |
| `eagle/cli/runtime.py` | Runtime command parsing and status exit codes. |
| `eagle/cli/run.py` | Experiment document checks, runtime endpoint preflight, and search/resume dispatch. |
| `eagle/cli/analyze.py` | Canonical run selection, agent Game Performance view, commentary view, and report dispatch. |
| `eagle/runtime/config.py` | Loads and validates `configs/runtime.yaml`. |
| `eagle/runtime/endpoints.py` | Local endpoint URL construction and health checks. |
| `eagle/runtime/processes.py` | PID-validated local `llama-server` process lifecycle. |
| `eagle/config.py` | Experiment configuration parsing, defaults, validation, and resolved settings. |
| `eagle/search.py` | Population initialization, generation loop, variation/evaluation orchestration, NSGA-II survivor update, and final run status. |
| `eagle/resume.py` | Resumes a canonical run while preserving its persisted state and artifact ownership. |
| `eagle/offspring.py` | Candidate seed/offspring construction and prompt normalization. |
| `eagle/candidate.py` | Candidate genotype/phenotype state, identity, lineage, failure, objective, and artifact metadata. |
| `eagle/crossover.py` | Three-component uniform crossover and provenance recording. |
| `eagle/mutation.py` | Mutation context, reflection/rewrite dispatch, and mutation records. |
| `eagle/rewrite.py` | Prompt-only Code/Strategy rewrite handling. |
| `eagle/strategy_reflection.py` | Sports-role Strategy Reflection: strict match selection, Match Commentator, Manager, Coach, strategy signature, niche, and intent artifacts. |
| `eagle/reflection_context.py` | Structured evidence passed to Strategy and Code Reflection. |
| `eagle/reflection_prompts.py` | Code Reflection prompt construction. |
| `eagle/strategy_archive.py` | Run-level strategy-niche representative archive. |
| `eagle/strategy_diversity.py` | Deterministic signature normalization, niche derivation, distance, and diversity metrics. |
| `eagle/opponents.py` | Evolution opponent identities, roster constants, JAR paths, and opponent setup errors. |
| `eagle/prompts.py` | Seed and final-generation prompt text. |

## Evaluation and generation layer

| Path | Responsibility |
| --- | --- |
| `eagle/evaluation.py` | Single child pipeline: generate result handling, validation, compilation, integration, all-match evaluation, objective construction, and candidate artifact persistence. |
| `eagle/artifacts.py` | Candidate input, stage, match, objective, and compact artifact serialization. |
| `eagle/run_artifacts.py` | Run manifest, generation snapshots, generation metrics, error memory, final population, and atomic JSON/JSONL writes. |
| `eagle/timing.py` | Candidate/stage timing events. |
| `eagle/llm_errors.py` | LLM transport/server error types. |
| `eagle/llm_logging.py` | Raw LLM request/response and attempt timing artifacts. |
| `eagle/llm_profiles.py` | Runtime role/profile configuration values. |
| `eagle/llm_progress.py` | Bounded LLM progress reporting. |
| `eagle/llm_roles.py` | Canonical role names and role settings. |
| `eagle/llm_transport.py` | OpenAI-compatible transport, prompt limits, and shared client plumbing. |
| `evaluation/compiler.py` | `javac` invocation and compiler diagnostic parsing. |
| `evaluation/code_quality.py` | Static metrics, strategy-region diagnostics, and compatibility exports for the canonical quality implementation. |
| `evaluation/canonical_code_quality.py` | Failure-aware Code Quality objective formula and diagnostic breakdown. |
| `evaluation/function_capability.py` | Generated-function capability checks. |
| `evaluation/game_metrics.py` | Match telemetry component extraction and aggregate game metrics. |
| `evaluation/game_performance.py` | Weighted Game Performance calculation. |
| `evaluation/match_matrix.py` | Deterministic opponent/map/round/side matrix construction. |
| `evaluation/match_logs.py` | Temporary match-log reading and chunking for reflection. |
| `evaluation/match_trace.py` | Match trace serialization/read helpers. |
| `evaluation/microrts_runner.py` | MicroRTS integration probe and compatibility façade for canonical match execution. |
| `evaluation/runtime_evaluation.py` | Canonical MicroRTS match process, result validation, hashes, and runtime failure classification. |
| `evaluation/nsga2_objectives.py` | Exactly two optimizer objectives and failure values. |
| `evaluation/opponent_schedule.py` | Weighted opponent schedule and previous-generation EAGLE opponent. |
| `evaluation/strategy_alignment.py` | Strategy-alignment diagnostic evaluation. |
| `generation/agent_template.py` | Complete Java-agent template paths and source contract. |
| `generation/backend.py` | Mock/OpenAI-compatible generation backend. |
| `generation/java_agent_generator.py` | Complete Java generation, extraction, validation, and source persistence. |

## Analysis layer

| Path | Responsibility |
| --- | --- |
| `eagle/analysis/loader.py` | Reads only versioned compact run artifacts and resolves latest/explicit runs. |
| `eagle/analysis/report.py` | Produces static CSV, JSON, Markdown, and Matplotlib reports, including per-agent `game_performance`. |
| `eagle/analysis/__init__.py` | Lightweight loader exports; report import is lazy so run selection does not load Matplotlib. |

## Configuration and runtime assets

| Path | Responsibility |
| --- | --- |
| `configs/runtime.yaml` | Single local LLM runtime source of truth. |
| `configs/experiments/microrts.yaml` | Canonical production EA experiment. |
| `configs/experiments/microrts-smoke.yaml` | Small mock/contract smoke configuration. |
| `config/prompt_templates.toml` | Canonical repository-backed prompt templates for reflection, rewrite, generation, and strategy alignment. |
| `runtime/` | Ignored local PID/log state for `run_env.sh`; not source code. |
| `experiment_env/` | Local Conda/model/llama.cpp runtime assets; external dependency, not EAGLE Python logic. |
| `third_party/microrts/` | Vendored MicroRTS runtime, maps, libraries, and Java sources used by evaluation. |
| `third_party/final_test_opponents/` | External opponent manifests/JAR/adapters still referenced by the active ten-opponent evolution roster. The final-test executor was removed. |
| `third_party/gui_opponents/` | AlliBot runtime assets referenced by active evaluation and the retained GUI inspection utility. |

## Tests and documentation

| Path | Responsibility |
| --- | --- |
| `tests/` | Unit and contract tests for the four-entrypoint dependency closure plus the retained GUI inspection utility. Tests for removed final-test and standalone commentator paths were deleted. |
| `docs/architecture/` | Architecture and ownership contracts. |
| `docs/evaluation/` | Active evaluation and objective contracts. |
| `docs/artifacts/` | Persisted artifact and timing contracts. |
| `docs/implementation/` | Current implementation map/status/gaps/traceability. |
| `docs/operations/` | Four-entrypoint operating and analysis instructions. |
| `docs/testing/` | Test contracts. |
| `docs/reflection-current-state.md`, `docs/strategy-reflection.md` | Current reflection behavior and strategy-reflection contract. |

## Removed legacy surface

The following were not reachable from the four entrypoints and were removed:

- `eagle/cli/migrate_run.py` and the `migrate-run` dispatcher branch;
- `eagle/final_test/` and `configs/final_test_champions.yaml`;
- `scripts/` utilities for final tests and legacy plotting; GUI match and AlliBot setup utilities are retained;
- `eagle/analysis/{errors,final_tests,objectives,records,timing}.py`;
- `eagle/match_commentator.py` and `eagle/commentary_aggregation.py` standalone APIs;
- unused `agents/` and `generation/parsing.py` scaffolding;
- unused historical `configs/eagle_*.yaml` files.

These deletions do not remove active in-pipeline Match Commentator behavior: that
behavior remains implemented by `eagle/strategy_reflection.py`.

## Dependency direction

```text
shell entrypoints
    -> eagle CLI/runtime/search/analysis orchestration
        -> generation/evaluation/mutation operators
            -> artifact serializers and timing
```

Scoring modules return data; artifact writers serialize it; search owns
orchestration; prompt formatting remains in reflection/rewrite modules. External
runtime trees and generated run evidence are dependencies or outputs, not Python
entrypoints.
