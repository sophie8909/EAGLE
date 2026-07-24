# Running EAGLE

Use the repository-root entrypoint:

```bash
./run.sh
```

The GUI is the canonical control surface. Use Servers for local model/server lifecycle and role assignment, Experiment for the canonical YAML and prompt sources, and Analysis for persisted objective and timing artifacts.

For a deterministic headless check, use:

```bash
python3 scripts/run_eagle.py --config configs/eagle_minimal.yaml --mock
```
