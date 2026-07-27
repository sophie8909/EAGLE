# Running EAGLE

Use the repository-root entrypoint:

```bash
./run.sh
```

The GUI is the canonical control surface. Use Servers for local model/server lifecycle and role assignment, Experiment for the canonical YAML and prompt sources, and Analysis for persisted objective and timing artifacts.

To inspect the resolved configured-server state without opening the GUI, run:

```bash
python -m eagle.runtime.server_manager --diagnose
```

This command does not launch a server. It reports configuration and path validity, managed process state when available, port and endpoint state, and GPU expectation/backend evidence.

Local managed servers use the logical backend settings in the topology: `backend: cpu` emits no GPU flags, while `backend: cuda` requires a CUDA-capable executable and maps `fit_to_vram: true` to the llama.cpp version-compatible `--gpu-layers auto --fit on` arguments. Remote records are validated without spawning a process.

Mutation, generation, and Strategy Alignment requests are hard-truncated at the shared
LLM transport boundary when oversized; the prompt head and latest evidence tail are
retained, while complete telemetry remains in run artifacts.

For a deterministic headless check, use:

```bash
python3 scripts/run_eagle.py --config configs/eagle_minimal.yaml --mock
```
