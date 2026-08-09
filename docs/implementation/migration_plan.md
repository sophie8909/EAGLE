# EAGLE migration plan

## Canonical shell workflow (completed 2026-07-28)

- `runtime-v1` centralizes Conda, paths, local/remote endpoints, roles, model
  paths, ports, llama.cpp arguments, health checks, logs, and one PID.
- `run_env.sh` owns runtime processes only.
- `run.sh` owns experiment validation, execution, and resume only.
- `analyze.sh` owns static compact-artifact analysis only.
- `eagle-run-v1` records atomic survivor snapshots and objective statistics at
  every completed generation.
- Canonical analysis selects direct-child runs and never reads
  `results.jsonl`.
- The obsolete interface, its service managers, dependencies, launch scripts,
  views, controllers, and tests were removed rather than retained as
  compatibility surfaces.

Remaining live verification is host-specific: the checked-in model paths require a
local Ubuntu or WSL2 Conda installation, llama.cpp binary, GGUF file, ports, and
any intentionally configured remote hosts.
