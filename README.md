# EAGLE

EAGLE (Evolutionary Algorithm for Game-playing with LLM-Enabled Agents) evolves a three-part Candidate genotype that generates one complete Java MicroRTS agent. The target architecture compiles that Java once, evaluates it in 10 matches against LightRush, and optimizes `game_performance` plus `code_quality` with NSGA-II.

Start with [`docs/README.md`](docs/README.md). It routes Codex and maintainers to the authoritative architecture specification, responsibility-focused contracts, current implementation status, architecture gaps, migration plan, and operational guidance.

Historical runtime-LLM, surrogate, split-Java, fixed function-body, and legacy objective artifacts are not active implementation contracts.

## Current smoke command

Run from WSL:

```bash
cd /mnt/d/Project/EAGLE
python3 scripts/run_eagle.py --config configs/eagle_minimal.yaml --mock
```

This validates the current mock pipeline only. The current implementation and checked-in configs do not yet satisfy every target architecture contract; see [`docs/implementation/current_status.md`](docs/implementation/current_status.md) and [`docs/implementation/architecture_gaps.md`](docs/implementation/architecture_gaps.md).

## Repository map

```text
eagle/        Candidate, evolutionary orchestration, operators, selection, artifacts
generation/   LLM transport, Java extraction, validation, and template support
evaluation/   Java compilation, MicroRTS execution, telemetry, and objective code
configs/      current experiment input configurations
scripts/      run, analysis, plotting, and manual GUI entry points
tests/        current unit and pipeline-contract tests
docs/         normative, canonical, implementation-status, and operations documentation
```
