# Running EAGLE

```bash
./run_env.sh start
./run_env.sh start --model /path/to/other-model.gguf
./run_env.sh check
./watchdog.sh
./run.sh configs/experiments/microrts.yaml
./run.sh configs/experiments/microrts.yaml --resume RUN_DIR
./run.sh configs/experiments/microrts.yaml --resume
./analyze.sh
./run_env.sh stop
```

The runtime schema contains one default local Qwen3.5-9B GGUF and one endpoint.
Use `run_env.sh start --model /path/to/other-model.gguf` or
`run_env.sh restart --model /path/to/other-model.gguf` to test another model;
the argument is a direct GGUF path and is not an alias. Start
does not launch the EA, stop never kills an unmanaged process, and check never
starts the server. The experiment configuration contains generation behavior
only; model, host, port, and server settings belong exclusively to
`configs/runtime.yaml`.

Pressing Ctrl-C interrupts the EA safely. The run manifest becomes
`interrupted`, and the last atomically recorded generation snapshot remains
available. Continue that run explicitly with `--resume RUN_DIR`, or let
`--resume` select the newest incomplete run with a completed generation:

```bash
./run.sh configs/experiments/microrts.yaml --resume runs/20260811_120000_000000
./run.sh configs/experiments/microrts.yaml --resume
```

Only completed generation snapshots are resumed. If interruption occurs
before generation 0 is fully recorded, there is no safe population checkpoint
to continue from. In-progress candidate or match work is discarded by the
resume boundary and will be recomputed for the next generation.

`watchdog.sh` is optional and independent from `run_env.sh`. It checks the
local network interface used by the default route and cycles it down/up when
disconnected; it does not manage the server process. Non-root execution
requires passwordless `sudo` for `ip link`. Use
`./watchdog.sh --once` for a single check or
`./watchdog.sh --interval 30` for a 30-second foreground polling interval.
Use `run_env.sh start|stop|restart|status|check` for server lifecycle.
