---
name: eagle-evaluation
description: Implement or review EAGLE Java validation/compilation/integration, the configured 126-match seven-opponent MicroRTS matrix, opponent-wise lexicase fitness, game_performance/code_quality diagnostics, and failure-stage handling. Use for runner, scoring, telemetry, diagnostics, integration, or failure-classification changes.
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

- Validate, compile once, integrate, then run the configured seven-opponent × map × round × side matrix (126 matches in the canonical production configuration), including a distinct WorkerRush.
- Reuse identical source/classes; make no generation call between matches.
- Use the seven opponent scores as the only optimizer fitness cases; `game_performance`, `code_quality`, Function Capability, and Strategy Alignment are diagnostics.
- Assign every failed evaluation the canonical `-1000` sentinel on all seven opponent cases and retain stage-aware diagnostics.
- Skip Strategy Alignment for an empty policy; otherwise retain it as a diagnostic, never as an optimizer case.
- Retain completed match evidence on partial runtime failure.
- Enforce the exact `ai.generated.CandidateAgent` identity and seven ordered pre-match integration checks from the Java-generation and evaluation owners.

## Workflow

1. Identify the exact stage boundary and formula owner.
2. Treat `A-01`/`A-02` as resolved decisions; use their canonical contracts and keep dependent implementation gaps open until tests/artifacts conform.
3. Keep process execution, scoring, and serialization responsibilities separate.
4. Persist commands, diagnostics, checks, telemetry, results, formula versions, and timings.
5. Add stage fixtures plus exact formula/boundary tests.
6. Run WSL unit tests and only the smallest required real Java/MicroRTS integration check.

## Common files

`eagle/evaluation.py`, `evaluation/compiler.py`, `evaluation/microrts_runner.py`, `evaluation/game_performance.py`, `evaluation/game_metrics.py`, `evaluation/code_quality.py`, `evaluation/objectives.py`, `eagle/config.py`, `eagle/artifacts.py`, `tests/`, and `configs/`.

## Required documentation updates

Update the affected evaluation owner, current status/gaps, testing contract, artifact/timing docs for payload changes, and the Chinese overview for any protocol/formula/failure-contract change.

## Prohibited legacy behavior

No RandomAI active opponent, one-match evaluation, regeneration between matches, unbounded old shaping formula, deterministic marker/text score substituted for the canonical code-quality contract, or active `strategy_alignment` objective.
