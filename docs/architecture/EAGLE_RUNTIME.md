# EAGLE canonical runtime

## Startup and ownership

`./run.sh` resolves the repository, prepares the `eagle` environment, starts `python -m eagle_ui`, and starts `python -m eagle.runtime.watchdog --pid <gui-pid>`. The watchdog reports GUI liveness only. It does not start, restart, or supervise experiment or LLM children.

The GUI owns the user-facing lifecycle. `RunController` owns one experiment subprocess and shuts it down on GUI exit. `LLMServerManager` owns local LLM command construction, process identity, readiness, status, output, stop, restart, and role association. Configured LAN servers are endpoint records tested from the GUI; they are not launched by this machine.

`LLMServerManager` resolves one specification for both launch and connection. It contains the local/remote location type, explicit `cpu`/`cuda`/`remote` backend, executable and model paths where applicable, bind and client hosts, port, base URL, API/health endpoints, roles, logical GPU-layer and VRAM-fit settings, additional arguments, environment overrides, and working directory. Capability checks run the selected binary's version and `--list-devices` probes before a CUDA launch; CPU-only binaries are rejected in CUDA mode and CPU mode emits no GPU arguments. The topology saved for EA roles is written from that resolved specification. A configured port is never silently replaced.

Server lifecycle states are `STOPPED`, `STARTING`, `READY`, `FAILED`, and `STOPPING`. A local process remains `STARTING` while the model loads and becomes `READY` only when the process is alive, the client port accepts connections, `/health` succeeds, and `/v1/models` exposes the configured model alias. Remote records use the same endpoint checks without creating a local process. Failure retains the exit code, concrete reason, recent output, and combined log under `experiment_env/runtime/servers/<server_id>/server.log`. Stop signals and reaps only the owned process group.

## GUI functions

- **Servers**: discover `.gguf` models, choose a local model/server/port, assign `reflector`, `rewriter`, and `generator`, start/stop/restart local servers, and inspect endpoint/process output.
- **Experiment**: edit one authoritative experiment YAML and prompt-template source, start/stop the EA subprocess, and inspect current progress and artifacts.
- **Analysis**: read persisted objective artifacts for NSGA-II plots and persisted timing artifacts for generation, operation, pipeline-stage, request, and slow-operation views.

## Experiment and prompt flow

`ExperimentConfig` is the canonical run configuration. `InitialPromptController` writes seed and generation prompts to that config, while `MetaPromptController` writes the active meta-prompt TOML source consumed by mutation stages. The GUI does not copy prompt values into a compatibility file.

## Evolution ownership

`eagle.search.run_search` owns population lifecycle and generation boundaries. `eagle.search.create_offspring` owns parent selection, mutation selection, and direct crossover/mutation orchestration. `eagle.crossover.crossover` owns component crossover. `eagle.rewrite.PromptRewriteMutation` owns mutation reflection/rewrite stages. `eagle.evaluation.evaluate_candidate` owns the shared child pipeline: complete Java generation, validation, compilation, MicroRTS integration, matches, and objective calculation.

## Algorithm lifecycle

The canonical generation lifecycle, mutation path, crossover path, shared child pipeline, population update, timing semantics, and post-evolution final evaluation are documented in [`EAGLE_SEARCH.md`](EAGLE_SEARCH.md).

## Timing artifacts

Each candidate persists `candidates/<candidate_id>/timing.json`. Each run appends generation and LLM request records to `timing.jsonl`; individual LLM attempt details remain in `llm_logs/*.json`. Durations use `time.monotonic()`, while UTC timestamps are for human-readable event ordering.

Mutation and crossover records contain generation-only duration and parent-selection duration. The shared child record separately reports validation, compilation, integration, evaluation, and `child_total`; downstream evaluation is never labeled as mutation-generation time. Requests record run/candidate/generation identity, operation type, stage, model, endpoint, wall timestamps, monotonic duration, status, and correlation ID.

## Removed entrypoints

The old interactive `experiment_env` server launch menu, role-specific shell launchers, generated launcher helpers, standalone `tmux_services.sh`, and network-reset watchdog are removed. There is one normal startup path: `./run.sh`.

Configured server diagnostics are available without opening the GUI:

```bash
python -m eagle.runtime.server_manager --diagnose
```

The report validates configuration, resolved paths, process/port/endpoint state, selected backend, executable version, detected devices, and GPU expectation/backend evidence without launching a server.
