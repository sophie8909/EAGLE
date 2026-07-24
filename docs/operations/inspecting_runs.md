# Inspecting runs and debugging candidates

Read [`../artifacts/artifact_schema.md`](../artifacts/artifact_schema.md) and [`../evaluation/failure_classification.md`](../evaluation/failure_classification.md) first. The active reader accepts only the current versioned artifact layout and objective names.

## Current failure summary

```bash
cd /mnt/d/Project/EAGLE
python3 scripts/analyze_run.py runs/<run_id>
```

The analysis CLI and GUI read canonical per-candidate results and objective values. Missing or malformed current artifacts are reported; historical schemas are outside the active runtime.

## Current gameplay plot

```bash
cd /mnt/d/Project/EAGLE
python3 scripts/analysis/plot_game_performance_by_generation.py --run-dir runs/<run_id>
```

The script writes plot and CSV outputs under the selected run. Use only when creating analysis artifacts is intended. Confirm schema compatibility before comparing runs across artifact/objective versions.

## Candidate debugging order

1. Read `candidate_result.json` only as an index; follow its stage artifact references.
2. Confirm lineage and the exact pre-generation genotype.
3. Compare final generation request, raw response, extracted source, and normalized source.
4. Read source-validation checks and terminal stage.
5. Read compiler command and structured diagnostics.
6. Read integration checks before interpreting match failures.
7. Count match directories/results and verify identical source/class hashes.
8. Recompute objective components from persisted inputs using the recorded formula version.
9. Compare candidate timing/attempt count with request/response artifacts.

If a run is missing canonical evidence, consult [`../implementation/current_status.md`](../implementation/current_status.md) and document the missing artifact. Do not fill missing fields by assumption.

## Failure triage

| Symptom | Inspect first | Do not misclassify as |
| --- | --- | --- |
| no backend response or extractable Java | generation attempts/raw responses | validation or compilation |
| complete source rejected before `javac` | validation result | generation transport failure |
| `javac` nonzero | compiler diagnostics | integration |
| class/constructor/method cannot load | integration checks | compilation or runtime match |
| process starts but result is missing/partial | match stdout/stderr/result/timing | valid loss/draw |
| fewer than 10 valid matches | completed match evidence | successful aggregate |
| objective looks inconsistent | formula/schema versions and component payload | NSGA-II bug before recomputation |

## Manual GUI inspection

```bash
cd /mnt/d/Project/EAGLE
python3 scripts/play_candidate_gui.py runs/<run_id> <candidate_id> --opponent ai.abstraction.LightRush
```

This is a manual visualization path. It may recompile an existing artifact and allows alternate opponents; it is not the evolutionary evaluation protocol and must not modify stored fitness.

## Artifact boundary

- Runs containing `module_bodies`, `CandidateBehaviors.java`, `GeneratedAgent_*`, or objective `strategy_alignment` are outside the active schema and are not readable by the current analysis runtime.
- Runs with one match, RandomAI, or unversioned formulas are not architecture-compliance evidence.
- Never copy historical prompts, schemas, or scoring into active code without checking the normative spec.
- New analysis code must consume the versioned canonical schema directly.

