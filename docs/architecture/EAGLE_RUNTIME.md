# EAGLE runtime architecture

The experiment `model` section selects the GGUF, llama-server executable,
endpoint, per-request context size, batch size, and startup/health timeouts.
An optional `generation_model` selects the materialization-phase model. GPU
layers (`999`), model threads (`8`), LLM workers (`2`), and match workers (`10`)
are fixed constants in `eagle/execution.py`; model parallel slots are fixed at
`2` (`--parallel 2`, `--n-gpu-layers 999`). These values are not serialized
config fields. The server receives
`--ctx-size context_size*2` and `--parallel 2`, providing one configured
request context to each slot.

Before server startup, GPU-device preflight confirms that the configured runtime
can use CUDA. Each fresh child startup must also provide positive
`offloaded N/N layers to GPU` evidence for the selected model. Missing, stale,
malformed, or partial evidence shuts down the owned process and fails startup;
there is no CPU fallback.

`experiment.sh` delegates to `python -m eagle experiment`. The orchestrator
uses `RuntimeManager` for owned startup, health checks, phase switching, and
cleanup. One batch uses one `RuntimeManager`. Its compatibility key contains the
resolved model path, server executable, host, port, per-request context size,
batch size, and fixed GPU/thread/parallel settings. An equal key reuses the
currently owned process; a changed key stops that verified process before
starting its replacement. Each run or replicate starts a fresh child and
requires fresh full-offload evidence; within one run,
the same server can switch between `model` and `generation_model` at the
reflection/materialization boundary. `LLMClient` uses the same resolved
endpoint and model. Match execution uses the fixed ten-worker pool. Each bounded
LLM phase cancels queued tasks on failure or interruption and waits for active
requests to finish before returning, so a model switch cannot interrupt requests
still in flight.

Ownership is stored per endpoint below `runtime/ownership/`. The record contains
an unguessable batch token, PID, Linux process start time, resolved executable,
exact command, launcher identity, project root, and runtime spec. PID alone is
never sufficient: dead or identity-mismatched records are removed without
signalling the PID; a verified orphaned EAGLE record is cleaned; a record with
a live verified launcher is left alone.

An occupied endpoint without verified ownership is foreign even if its executable
happens to be named `llama-server`. EAGLE never kills or attaches to it and
reports host, port, PID, executable, and command. Batch cleanup calls
`stop_owned()` from one `finally` after success, search/artifact/final-test
failure, Ctrl+C, or CLI-translated SIGTERM. The experiment orchestrator is the
sole lifecycle owner.

If Ctrl+C interrupts termination after the owned process has already exited,
the original manager removes its matching ownership-token record before
re-raising the interrupt. It retains the record when that exact process is still
alive, and never removes a record owned by another manager token.

`--mock` bypasses runtime adaptation, GPU preflight, port inspection, health
checks, and server ownership.

The optional `watchdog.sh` monitors the local network interface; it does not own
a model process or endpoint.
