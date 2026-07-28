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
