# Running EAGLE

This document describes current commands and preflight checks. It does not claim that current implementation/configuration satisfies the architecture contract. Read [`../implementation/current_status.md`](../implementation/current_status.md) before interpreting a run.

## Environment rule

Use WSL by default for Python, Java compilation, and MicroRTS runtime work in this repository. Run from `/mnt/d/Project/EAGLE`. Do not spend time debugging Windows-side Java/PATH behavior unless a task explicitly targets Windows.

## Documentation preflight

Before changing or launching architecture-relevant work:

1. Read [`../README.md`](../README.md) and the routed canonical contracts.
2. Check [`../implementation/architecture_gaps.md`](../implementation/architecture_gaps.md).
3. Confirm the run is a smoke/current-state probe or a contract-conformant experiment.
4. Verify resolved values will include 10 matches, LightRush, map/cycles/seeds, LLM/retry versions, objective formula version, artifact schema version, and Git commit.

The checked-in configs currently specify one or three matches and therefore are not contract-conformant experiment configs.

## Current smoke command

From WSL:

```bash
cd /mnt/d/Project/EAGLE
python3 scripts/run_eagle.py --config configs/eagle_minimal.yaml --mock
```

This exercises current Python orchestration with mock generation/compile/matches and writes a run directory. It does not prove real LLM behavior, Java integration, the 10-match protocol, canonical objectives, or canonical artifacts.

`run.sh` invokes the same current mock path.

## Current real-mode entry point

```bash
cd /mnt/d/Project/EAGLE
python3 scripts/run_eagle.py --config <config-path>
```

Preconditions:

- configured OpenAI-compatible generation endpoint and model are reachable;
- WSL `python3`, `java`, and `javac` are available;
- `third_party/microrts/bin` and required JARs exist;
- the selected config is reviewed against the architecture contract;
- the output run ID/path does not collide.

Do not launch a large experiment merely to validate documentation or a local serializer. Prefer unit/contract tests and a bounded integration fixture.

## Configuration ownership

| Concern | Required resolved value |
| --- | --- |
| Evolution | population, generations, crossover/mutation rates and selection policy, EA seed |
| Evaluation | 10 matches, `ai.abstraction.LightRush`, map, cycles, per-match seeds |
| Generation | backend, model, endpoint identity, temperature, retry policy, prompt version |
| Objectives | formula version plus all material/resource scale values |
| Persistence | artifact schema version and Git commit |

Input `config.yaml` and `resolved_config.json` have distinct roles. Never treat a copied input file as proof of actual runtime values.

## Validation before accepting a run

- Every candidate has lineage, genotype, generation, stage, evaluation, objective, and timing artifacts.
- Every successful candidate has exactly 10 match directories.
- Commands name LightRush and the expected source/class hash.
- No Java-generation LLM attempt occurs inside the match batch.
- Objective payloads name only `game_performance` and `code_quality`.
- Schema/formula versions are present and supported by analysis tools.
- Partial or failed runs are classified by terminal stage.

Until the migration gaps close, state explicitly which of these checks cannot pass.

