# EAGLE

EAGLE (Evolutionary Algorithm for Game-playing with LLM-Enabled Agents) evolves
prompts that generate complete Java MicroRTS agents.

## Canonical workflow

```bash
./run_env.sh
./run.sh configs/experiments/microrts.yaml
./analyze.sh
./run_env.sh stop
./watchdog.sh
```

`configs/runtime.yaml` is the only runtime source of truth. It selects the
existing Qwen3.5-9B GGUF model, one CUDA-enabled `llama-server`, and
`http://127.0.0.1:8080`. `run_env.sh` only manages that one process; it never
starts the EA or analysis. `run.sh` validates that endpoint and runs the EA.

`watchdog.sh` is an optional independent foreground connectivity monitor. It
checks the local network interface used by the default route and cycles the
interface down/up when it is disconnected. It does not start, stop, or restart
the LLM server. Use `run_env.sh` for server lifecycle, `./watchdog.sh --once`
for one probe/recovery attempt, or `--interval SECONDS` to change the default
five-minute polling interval. Set `EAGLE_WATCHDOG_INTERFACE` to pin a specific
interface. Non-root execution requires passwordless `sudo` for `ip link`.

Runtime state is intentionally small:

```text
runtime/
├── logs/llm-server.log
└── pids/llm-server.pid
```

No model menus, endpoint discovery, remote mode, GUI, or fallback model is
supported. The watchdog is only a shell-level local-interface monitor/recovery
script; it is not a server lifecycle manager, second server, or endpoint router.

## Analysis

`./analyze.sh` performs offline analysis of the latest valid run, or a supplied
run directory. It retains candidate fitness, objective trends, failures,
operation timing, request counts, token counts, and total LLM time. Historical
run records may still be read by the analysis readers.
