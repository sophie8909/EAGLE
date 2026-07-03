# EAGLE

EAGLE evolves prompts that generate Java MicroRTS agents. The generated Java source is compiled, evaluated in MicroRTS, scored, and fed back into the evolutionary loop.

The old design where a Java agent called an LLM during a match has been archived under `archive/legacy_runtime/`.

## Quick Start

Run the minimal dry-run experiment:

```bash
python -m scripts.run_minimal_experiment --config configs/minimal_experiment.json
```

The default config uses the offline `template` generation backend and `dry_run=true`, so it writes generated Java source and records the compile/match commands without launching MicroRTS.

## Repository Map

```text
eagle/        core EA logic, candidate representation, population loop, operators
generation/   prompt-to-Java generation, output parsing, generated-source validation
agents/       generated Java agent workspace
evaluation/   compile plans, MicroRTS match plans, result parsing, fitness
configs/      experiment configs
scripts/      runnable entry points
docs/         architecture and handoff documentation
archive/      old runtime LLM-agent code and previous framework surfaces
```

Read `docs/ARCHITECTURE.md`, `docs/HANDOFF.md`, and `docs/TERMINOLOGY.md` before extending the system.
