# Running EAGLE

```bash
./run_env.sh
./run_env.sh check
./watchdog.sh
./run.sh configs/experiments/microrts.yaml
./run.sh configs/experiments/microrts.yaml --resume RUN_DIR
./analyze.sh
./run_env.sh stop
```

The runtime schema contains one local Qwen3.5-9B model and one endpoint. Start
does not launch the EA, stop never kills an unmanaged process, and check never
starts the server. The experiment configuration contains generation behavior
only; model, host, port, and server settings belong exclusively to
`configs/runtime.yaml`.

`watchdog.sh` is optional and independent from `run_env.sh`. It polls
`run_env.sh status` and invokes `run_env.sh start` when the managed runtime is
stopped or unhealthy. Use `./watchdog.sh --once` for a single check or
`./watchdog.sh --interval 30` for a 30-second foreground polling interval.
