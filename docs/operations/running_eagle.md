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

Runtime status and check operations report every configured server separately.
Local servers are accepted only when their recorded PID still refers to the
exact configured command. Remote servers are checked but never launched or
stopped. Bind hosts and client hosts remain distinct in `configs/runtime.yaml`.
Logs and PID files are written beneath its configured `log_root` and
`pid_root`; resolved role endpoints are written atomically for the EA process.
Local llama.cpp model aliases are passed explicitly with `--alias` so the
configured `model_id` matches `/v1/models`. The default
`prompt_cache_mib: 0` disables llama.cpp's optional cross-request prompt cache;
`reuse_prompt_cache: false` disables per-slot prompt reuse. Increase or enable
them only after validating the installed llama.cpp build under repeated
requests.

Mutation, generation, and Strategy Alignment requests are hard-truncated at the shared
LLM transport boundary when oversized; the prompt head and latest evidence tail are
retained, while complete telemetry remains in run artifacts.

For a deterministic headless check, use:

```bash
python -m eagle run \
  --config configs/experiments/microrts.yaml \
  --runtime-config configs/runtime.yaml \
  --mock
```
