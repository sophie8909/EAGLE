# EAGLE runtime architecture

The experiment `model` section defines the local/default primary profile,
including its endpoint, optional GGUF and llama-server executable, per-request
context size, batch size, and startup/health timeouts. `use_remote_llm: true`
instead selects the required unmanaged `remote_model` profile while retaining
both definitions in resolved configuration. An optional unmanaged
`generation_model` selects the materialization-phase model. GPU
layers (`999`), model threads (`8`), LLM workers (`2`), and match workers (`10`)
are fixed constants in `eagle/execution.py`; model parallel slots are fixed at
`2` (`--parallel 2`, `--n-gpu-layers 999`). These values are not serialized
config fields. The server receives
`--ctx-size context_size*2` and `--parallel 2`, providing one configured
request context to each slot.

Before local server startup, GPU-device preflight confirms that the configured runtime
can use CUDA. Each fresh child startup must also provide positive
`offloaded N/N layers to GPU` evidence for the selected model. Missing, stale,
malformed, or partial evidence shuts down the owned process and fails startup;
there is no CPU fallback.

`python -m eagle server --config CONFIG.yaml` is the foreground lifecycle owner
for a selected local primary profile. It constructs one `RuntimeManager`, starts
and health-checks the child, and keeps that server resident across experiment
runs until interruption or failure. The manager's compatibility key contains
the resolved model path, server executable, host, port, per-request context
size, batch size, and fixed GPU/thread/parallel settings.

`experiment.sh` delegates only to `python -m eagle experiment`. Fresh, resumed,
and batch experiments never construct a `RuntimeManager`, start or stop a
server, or switch endpoint models. They build fixed role clients, preflight
every selected primary, generation, and additional endpoint, and fail closed if
any endpoint is unavailable. `LLMClient` uses the resolved endpoint and model;
different role models therefore require independently running servers. Match
execution uses the fixed ten-worker pool. Each bounded LLM phase cancels queued
tasks on failure or interruption and waits for active requests to finish before
returning.

Ownership is stored per endpoint below `runtime/ownership/`. The record contains
an unguessable batch token, PID, Linux process start time, resolved executable,
exact command, launcher identity, project root, and runtime spec. PID alone is
never sufficient: dead or identity-mismatched records are removed without
signalling the PID; a verified orphaned EAGLE record is cleaned; a record with
a live verified launcher is left alone.

An occupied endpoint without verified ownership is foreign even if its executable
happens to be named `llama-server`. EAGLE never kills or attaches to it and
reports host, port, PID, executable, and command. The foreground server command
calls `stop_owned()` from its cleanup path after startup/health failure, Ctrl+C,
or CLI-translated SIGTERM. Experiments never signal an endpoint process.

If Ctrl+C interrupts termination after the owned process has already exited,
the original manager removes its matching ownership-token record before
re-raising the interrupt. It retains the record when that exact process is still
alive, and never removes a record owned by another manager token.

Experiment `--mock` mode bypasses endpoint preflight and model work. The separate
server command has no mock mode.

The optional `watchdog.sh` monitors the local network interface; it does not own
a model process or endpoint.
