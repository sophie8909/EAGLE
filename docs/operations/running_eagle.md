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

For a deterministic headless check, use:

```bash
python3 scripts/run_eagle.py --config configs/eagle_minimal.yaml --mock
```
