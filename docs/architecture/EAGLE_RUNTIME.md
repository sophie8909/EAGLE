# EAGLE runtime architecture

`configs/runtime.yaml` (`runtime-v1`) is the only runtime source of truth. It owns one Conda environment, one LLM endpoint, one optional local model process, health checks, logs, PIDs, and watchdog policy.

All LLM-backed operations use this same endpoint. Reflection, rewriting, mutation, crossover, and generation remain logical operation labels only.

Runtime files: runtime/logs/llm-server.log, runtime/logs/watchdog.log, runtime/pids/llm-server.pid, runtime/pids/watchdog.pid, and runtime/resolved_endpoint.json.

