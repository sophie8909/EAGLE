# EAGLE migration plan

## Canonical shell workflow (completed 2026-07-28)

- `runtime-v1` centralizes Conda, one local endpoint, one direct model path,
  ports, llama.cpp arguments, health checks, logs, and one PID.
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

## Direct AOS credit assignment (completed 2026-08-17)

- Parent A remains the explicit canonical AOS comparison parent.
- Runnable mutated offspring play the comparison parent on the configured
  three maps, three round seeds, and both sides using existing compiled classes.
- Direct W/D/L points replace seven-opponent rank changes as the sole AOS
  performance reward; lexicase fitness remains unchanged.
- `eagle-aos-v2` and `eagle-aos-reward-v2` preserve EMA/probability transitions
  and reconstructable head-to-head totals.
