# EAGLE runtime architecture

The selected experiment's `model` section is the only production runtime source of truth. It defines the model name/GGUF, llama-server executable, endpoint, context/GPU/thread/batch/parallel arguments, and startup/health timeouts.

`experiment.sh` delegates to `python -m eagle experiment`. `eagle.experiment` adapts the resolved model through `eagle.runtime.config`, starts it with `RuntimeManager`, waits for health, and lets search verify a chat completion before the EA begins. Runtime and `LLMClient` therefore consume the same resolved endpoint and model.

One batch creates one `RuntimeManager`. Its compatibility key contains the resolved model path, server executable, host, port, context size, GPU layers, parallelism, threads, and batch size. An equal key reuses the owned process; a changed key stops the verified current process before starting the replacement.

Ownership is stored per endpoint below `runtime/ownership/`. The record contains an unguessable batch token, PID, Linux process start time, resolved executable, exact command, launcher identity, project root, and runtime spec. PID alone is never sufficient: dead or identity-mismatched records are removed without signalling the PID; a verified orphaned EAGLE record is cleaned; a record with a live verified launcher is left alone. Legacy `runtime/pids/*.pid` records are reconciled only when the live process is a repository-local `llama-server`, and an adopting systemd process is not treated as an active EAGLE launcher.

An occupied endpoint without verified ownership is foreign even if its executable happens to be named `llama-server`. EAGLE never kills or attaches to it and reports host, port, PID, executable, and command. Batch cleanup calls `stop_owned()` from one `finally` after success, search/artifact/final-test failure, Ctrl+C, or CLI-translated SIGTERM. The experiment orchestrator is the sole lifecycle owner.

`--mock` bypasses runtime adaptation entirely: no model-file validation, port inspection, health check, or server ownership state is touched.

The optional `watchdog.sh` only monitors the local network interface. It never owns a model process or endpoint.
