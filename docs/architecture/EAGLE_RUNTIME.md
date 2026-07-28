# EAGLE runtime architecture

`configs/runtime.yaml` (`runtime-v1`) is the only runtime source of truth. It
defines one Conda environment, one Qwen3.5-9B GGUF file, one CUDA-enabled
llama.cpp server binary, one endpoint, one PID, and one log.

The runtime process is controlled only by `run_env.sh start|stop|restart|status|check`.
There is no remote mode, model routing, endpoint routing, watchdog, resolved
endpoint cache, or interactive runtime management.

All LLM operations receive the same `LLMClient` configuration. Operation labels
are metadata for prompts, timing, and artifacts; they never select a model or
endpoint.
