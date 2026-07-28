# EAGLE

EAGLE (Evolutionary Algorithm for Game-playing with LLM-Enabled Agents) evolves
prompts that generate complete Java MicroRTS agents.

## Canonical workflow

```bash
./run_env.sh
./run.sh configs/experiments/microrts.yaml
./analyze.sh
./run_env.sh stop
```

`configs/runtime.yaml` is the only runtime source of truth. It selects the
existing Qwen3.5-9B GGUF model, one CUDA-enabled `llama-server`, and
`http://127.0.0.1:8080`. `run_env.sh` only manages that one process; it never
starts the EA or analysis. `run.sh` validates that endpoint and runs the EA.

Runtime state is intentionally small:

```text
runtime/
├── logs/llm-server.log
└── pids/llm-server.pid
```

No model menus, endpoint discovery, remote mode, watchdog, GUI, or fallback
model is supported.

## Analysis

`./analyze.sh` performs offline analysis of the latest valid run, or a supplied
run directory. It retains candidate fitness, objective trends, failures,
operation timing, request counts, token counts, and total LLM time. Historical
run records may still be read by the analysis readers.
