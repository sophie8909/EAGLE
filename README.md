# EAGLE

EAGLE is the **Evolutionary Algorithm for Game-playing with LLM-Enabled Agents**.
It evolves prompts that generate complete Java MicroRTS agents. The canonical
workflow is shell-first and has no GUI or web service.

## Canonical workflow

```bash
# Configure Conda, models, ports, and watchdog
editor configs/runtime.yaml

# Start Conda runtime, LLM servers, and watchdog
./run_env.sh

# Check runtime status
./run_env.sh status

# Run the EA
./run.sh configs/experiments/microrts.yaml

# Analyze the latest run
./analyze.sh

# Analyze a specific run
./analyze.sh runs/20260728_143000_eagle

# Stop model servers and watchdog
./run_env.sh stop
```

`run_env.sh` manages only the Conda runtime, configured endpoints, local
`llama-server` processes, PID/log files, and the single watchdog. `run.sh`
validates and runs or resumes an experiment; it never starts model processes.
`analyze.sh` reads compact canonical artifacts and writes static files only.

## Runtime configuration

[`configs/runtime.yaml`](configs/runtime.yaml) uses schema `runtime-v1` and is
the only source of truth for:

- the Conda environment and project/run/log/PID roots;
- the `llama-server` binary;
- local model paths, bind hosts, client hosts, ports, and llama.cpp arguments;
- remote endpoint hosts and ports;
- role assignments (`generator`, `reflector`, and `rewriter`);
- watchdog restart policy and health-check paths;
- analysis output naming and latest-run strategy.

A local server has `mode: local`, a bind `host`, a `client_host`, and a model
path. `run_env.sh start` launches and supervises it. A remote server has
`mode: remote` and a `client_host`; it is health-checked but never launched or
restarted locally. An optional remote `model_id` identifies the model served by
the OpenAI-compatible endpoint. EAGLE URLs always use `client_host`.

Runtime state is separate from runs:

```text
runtime/
├─ logs/
│  ├─ coder.log
│  ├─ general.log
│  └─ watchdog.log
├─ pids/
│  ├─ coder.pid
│  ├─ general.pid
│  └─ watchdog.pid
└─ resolved_endpoints.json
```

PID files are written atomically. Stop validates each managed command line and
never terminates a process merely because its name or port matches.

## Run artifacts

Each completed generation records the population that survived selection:

```text
RUN_DIR/
├─ manifest.json
├─ resolved_config.json
├─ generation_metrics.jsonl
├─ generations/generation_0000.json
├─ candidates/
├─ errors.jsonl
├─ timing.jsonl
├─ final_population.json
└─ final_test/
```

Objective statistics exclude the `-1000` game-failure sentinel. Snapshots and
manifest updates are atomic, and generation metrics are keyed by generation so
resume cannot duplicate records.

## Offline analysis

With no path, `analyze.sh` inspects direct children of the configured
`environment.run_root`, ignores hidden/temporary/invalid directories, and
selects the valid manifest with the newest `last_update_time` (directory mtime
is the fallback). A supplied relative path is resolved from the current
directory; an absolute path is used directly. The command validates and
analyzes exactly that canonical run folder.

Outputs are written to `RUN_DIR/analysis/` as Markdown, JSON, CSV, and static
Matplotlib PNG files. Canonical analysis reads the manifest, resolved config,
generation metrics/snapshots, final population, timing, and errors. It does
**not** open `results.jsonl`.

Legacy runs are never migrated automatically. The explicit boundary is:

```bash
python -m eagle migrate-run RUN_DIR
```

No legacy schema is enabled unless a migration implementation is added and
tested explicitly.
