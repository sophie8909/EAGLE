# EAGLE runtime architecture

`configs/runtime.yaml` (`runtime-v1`) is the only runtime source of truth. It
defines one Conda environment, one Qwen3.5-9B GGUF file, one CUDA-enabled
llama.cpp server binary, one endpoint, one PID, and one log.

The runtime process is controlled by `run_env.sh start|stop|restart|status|check`.
The optional independent `watchdog.sh` checks the local network interface used
by the default route and cycles it down/up when disconnected. It does not
start, stop, or restart the server and does not own a second server, endpoint,
model, or runtime configuration.

All LLM operations receive the same `LLMClient` configuration. Operation labels
are metadata for prompts, timing, and artifacts; they never select a model or
endpoint.
