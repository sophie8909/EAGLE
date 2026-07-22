# EAGLE

EAGLE evolves prompts that generate Java MicroRTS agents. The generated Java source is compiled, evaluated in MicroRTS, scored, and fed back into the evolutionary loop.

The old design where a Java agent called an LLM during a match has been archived under `archive/legacy_runtime/`.

## Quick Start

Run the minimal mock experiment:

```bash
python scripts/run_eagle.py --config configs/eagle_minimal.yaml --mock
```

The mock path writes generated Java source, mock compile results, mock MicroRTS match results, `results.jsonl`, and `summary.json` under `runs/<run_id>/`.

## GUI

Install the project and launch the restored NiceGUI interface:

```bash
python3 -m pip install -e .
python3 -m eagle_ui
```

See [`docs/gui.md`](docs/gui.md) for LLM role configuration, prompt editing, run/candidate inspection, objective analysis, error analysis, and current limitations.

## Repository Map

```text
eagle/        candidate representation, config loading, search loop, selection, mutation
generation/   generation backend interface, LLM-compatible backend, Java output parsing and validation
agents/       generated Java agent workspace helpers
evaluation/   Java compilation, MicroRTS match adapter, fitness calculation
configs/      experiment configs
scripts/      runnable entry points
docs/         architecture and handoff documentation
archive/      old runtime LLM-agent code and previous framework surfaces
```

Read `docs/ARCHITECTURE.md`, `docs/HANDOFF.md`, and `docs/TERMINOLOGY.md` before extending the system.
