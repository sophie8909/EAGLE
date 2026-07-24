# EAGLE canonical runtime

## Startup and ownership

`./run.sh` resolves the repository, prepares the `eagle` environment, starts `python -m eagle_ui`, and starts `python -m eagle.runtime.watchdog --pid <gui-pid>`. The watchdog reports GUI liveness only. It does not start, restart, or supervise experiment or LLM children.

The GUI owns the user-facing lifecycle. `RunController` owns one experiment subprocess and shuts it down on GUI exit. `LLMServerManager` owns local LLM command construction, process identity, readiness, status, output, stop, restart, and role association. Configured LAN servers are endpoint records tested from the GUI; they are not launched by this machine.

## GUI functions

- **Servers**: discover `.gguf` models, choose a local model/server/port, assign `reflector`, `rewriter`, and `generator`, start/stop/restart local servers, and inspect endpoint/process output.
- **Experiment**: edit one authoritative experiment YAML and prompt-template source, start/stop the EA subprocess, and inspect current progress and artifacts.
- **Analysis**: read persisted objective artifacts for NSGA-II plots and persisted timing artifacts for generation, operation, pipeline-stage, request, and slow-operation views.

## Experiment and prompt flow

`ExperimentConfig` is the canonical run configuration. `InitialPromptController` writes seed and generation prompts to that config, while `MetaPromptController` writes the active meta-prompt TOML source consumed by mutation stages. The GUI does not copy prompt values into a compatibility file.

## Evolution ownership

`eagle.search.run_search` owns population lifecycle and generation boundaries. `eagle.search.create_offspring` owns parent selection, mutation selection, and direct crossover/mutation orchestration. `eagle.crossover.Crossover` owns uniform component crossover. `eagle.rewrite.PromptRewriteMutation` owns mutation reflection/rewrite stages. `eagle.evaluation.evaluate_candidate` owns the shared child pipeline: complete Java generation, validation, compilation, MicroRTS integration, matches, and objective calculation.

## Timing artifacts

Each candidate persists `candidates/<candidate_id>/timing.json`. Each run appends generation and LLM request records to `timing.jsonl`; individual LLM attempt details remain in `llm_logs/*.json`. Durations use `time.monotonic()`, while UTC timestamps are for human-readable event ordering.

Mutation and crossover records contain generation-only duration and parent-selection duration. The shared child record separately reports validation, compilation, integration, evaluation, and `child_total`; downstream evaluation is never labeled as mutation-generation time. Requests record run/candidate/generation identity, operation type, stage, model, endpoint, wall timestamps, monotonic duration, status, and correlation ID.

## Removed entrypoints

The old interactive `experiment_env` server launch menu, role-specific shell launchers, generated launcher helpers, standalone `tmux_services.sh`, and network-reset watchdog are removed. There is one normal startup path: `./run.sh`.
