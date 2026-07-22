---
name: eagle-evaluation
description: Implement or review EAGLE Java validation/compilation/integration, 10-match MicroRTS evaluation against LightRush, game_performance, code_quality, failure-stage fitness, and two-objective NSGA-II assembly. Use for runner, scoring, telemetry, diagnostics, integration, or failure-classification changes.
---

# EAGLE evaluation workflow

## Read first

- `docs/implementation/architecture_traceability_matrix.md` for status, priority, dependencies, and missing tests.
- `docs/eagle_architecture_spec.md` sections 12–19 and 26–27.
- `docs/evaluation/evaluation_pipeline.md`.
- The affected canonical formula file: `game_performance.md`, `code_quality.md`, or `failure_classification.md`.
- `docs/architecture/java_generation.md` for validation/compile/integration work.
- `docs/artifacts/artifact_schema.md` and `docs/artifacts/timing_schema.md`.
- Current status and architecture gaps.

## Preserve

- Validate, compile once, integrate, then run exactly 10 matches against `ai.abstraction.LightRush`.
- Reuse identical source/classes; make no generation call between matches.
- Use only `game_performance` and `code_quality` as optimizer objectives.
- Assign every failed evaluation `game_performance = -1000` and stage-aware `code_quality`.
- Keep Strategy Alignment inside successful `code_quality`, never as a third objective.
- Retain completed match evidence on partial runtime failure.
- Use the resolved `+500` successful-code-quality base from `docs/evaluation/code_quality.md`; do not reintroduce the no-offset alternative.
- Enforce the exact `ai.generated.CandidateAgent` identity and seven ordered pre-match integration checks from the Java-generation and evaluation owners.

## Workflow

1. Identify the exact stage boundary and formula owner.
2. Treat `A-01`/`A-02` as resolved decisions; use their canonical contracts and keep dependent implementation gaps open until tests/artifacts conform.
3. Keep process execution, scoring, and serialization responsibilities separate.
4. Persist commands, diagnostics, checks, telemetry, results, formula versions, and timings.
5. Add stage fixtures plus exact formula/boundary tests.
6. Run WSL unit tests and only the smallest required real Java/MicroRTS integration check.

## Common files

`eagle/evaluation.py`, `evaluation/compiler.py`, `evaluation/microrts_runner.py`, `evaluation/game_performance.py`, `evaluation/game_metrics.py`, `evaluation/code_quality.py`, `evaluation/nsga2_objectives.py`, `eagle/config.py`, `eagle/artifacts.py`, `tests/`, and `configs/`.

## Required documentation updates

Update the affected evaluation owner, current status/gaps, testing contract, artifact/timing docs for payload changes, and the Chinese overview for any protocol/formula/failure-contract change.

## Prohibited legacy behavior

No RandomAI active opponent, one-match evaluation, regeneration between matches, unbounded old shaping formula, deterministic marker/text score substituted for the canonical code-quality contract, or active `strategy_alignment` objective.

