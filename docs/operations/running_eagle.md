# Running EAGLE

The canonical workflow has exactly three shell entrypoints:

```bash
./run_env.sh [start|stop|restart|status|check] [--config configs/runtime.yaml]
./run.sh [configs/experiments/microrts.yaml] [--resume RUN_DIR]
./analyze.sh [RUN_DIR|--latest] [--force]
```

`run_env.sh` activates the Conda environment named by `configs/runtime.yaml`
and delegates endpoint/process management to `python -m eagle runtime`. It
starts enabled local llama.cpp servers, health-checks enabled remote servers,
writes PID/log/endpoint state, and starts one watchdog. It does not run an
experiment.

`run.sh` activates the same configured environment and delegates to
`python -m eagle run`. With no config argument it presents the files directly
under `configs/experiments/` as a numbered terminal list. It validates the
experiment and required role endpoints before creating or resuming a run. It
does not start model processes.

`analyze.sh` performs static offline analysis only. It does not manage the
environment or runtime processes.

The default checked-in runtime paths target `/home/mhlab/EAGLE`. Edit
`configs/runtime.yaml` for the actual host before starting the runtime.

This command does not launch a server. It reports configuration and path validity, managed process state when available, port and endpoint state, and GPU expectation/backend evidence.

Local managed servers use the logical backend settings in the topology: `backend: cpu` emits no GPU flags, while `backend: cuda` requires a CUDA-capable executable and maps `fit_to_vram: true` to the llama.cpp version-compatible `--gpu-layers auto --fit on` arguments. Remote records are validated without spawning a process.

The Servers page loads its initial values from
`experiment_env/config/llm_topology.json`. A server becomes `ready` only after
both `/health` and `/v1/models` validate the configured model. Use **Test
connection** to send a minimal `/v1/chat/completions` request without starting
an EA run, or **Copy diagnostic report** to copy the resolved command,
endpoint, process state, failure category, and stdout/stderr tails.

Human-readable output is appended to
`experiment_env/runtime/servers/<server-id>/server.log`. Structured lifecycle,
health-check, state-transition, and process-output events are appended to
`lifecycle.jsonl` in the same directory. Environment overrides are recorded
with secret-bearing values redacted.

Mutation, generation, and Strategy Alignment requests are hard-truncated at the shared
LLM transport boundary when oversized; the prompt head and latest evidence tail are
retained, while complete telemetry remains in run artifacts.

For a deterministic headless check, use:

```bash
python3 scripts/run_eagle.py --config configs/eagle_minimal.yaml --mock
```
