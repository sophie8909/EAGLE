# EAGLE documentation index

This directory is the implementation entry point for EAGLE (Evolutionary Algorithm for Game-playing with LLM-Enabled Agents).

## Authority and document classes

1. [`eagle_architecture_spec.md`](eagle_architecture_spec.md) is the authoritative normative architecture contract.
2. Files under [`architecture/`](architecture/overview.md), [`evaluation/`](evaluation/evaluation_pipeline.md), and [`artifacts/`](artifacts/artifact_schema.md) are canonical, responsibility-focused implementation contracts derived from the specification. They are normative only where they restate or link to the specification and are always subordinate to it.
3. Files under [`implementation/`](implementation/current_status.md) describe repository reality, gaps, migration work, and the current [architecture traceability matrix](implementation/architecture_traceability_matrix.md). They are non-normative.
4. Files under [`operations/`](operations/running_eagle.md) and [`testing/`](testing/test_contracts.md) describe workflows and verification.
5. [`architeture_specification_zh.md`](architeture_specification_zh.md) is the user-facing Traditional Chinese overview.

Codex should not read `docs/architeture_specification_zh.md` for implementation work.

When code and the specification differ, preserve the specification and update [`implementation/architecture_gaps.md`](implementation/architecture_gaps.md). Do not reinterpret the contract from legacy code, old runs, or the Chinese overview.

## Task routing

| Task | Required documents |
| --- | --- |
| Modify the Candidate model or genotype/phenotype boundary | [architecture spec](eagle_architecture_spec.md) + [candidate model](architecture/candidate_model.md) + [lineage schema](artifacts/lineage_schema.md) |
| Modify overall pipeline or NSGA-II flow | [architecture spec](eagle_architecture_spec.md) + [overview](architecture/overview.md) + [evolutionary flow](architecture/evolutionary_flow.md) |
| Modify Strategy or Code Mutation | [architecture spec](eagle_architecture_spec.md) + [mutation](architecture/mutation.md) + [artifact schema](artifacts/artifact_schema.md) + [timing schema](artifacts/timing_schema.md) |
| Modify Uniform Crossover | [architecture spec](eagle_architecture_spec.md) + [crossover](architecture/crossover.md) + [lineage schema](artifacts/lineage_schema.md) |
| Modify Java generation, validation, or compilation | [architecture spec](eagle_architecture_spec.md) + [Java generation](architecture/java_generation.md) + [failure classification](evaluation/failure_classification.md) |
| Modify MicroRTS execution | [evaluation pipeline](evaluation/evaluation_pipeline.md) + [failure classification](evaluation/failure_classification.md) + [artifact schema](artifacts/artifact_schema.md) |
| Modify `game_performance` | [game performance](evaluation/game_performance.md) + [evaluation pipeline](evaluation/evaluation_pipeline.md) |
| Modify `code_quality` | [code quality](evaluation/code_quality.md) + [failure classification](evaluation/failure_classification.md) |
| Modify artifacts, timing, or lineage | The matching canonical file under [artifacts/](artifacts/artifact_schema.md) + [architecture spec](eagle_architecture_spec.md) |
| Modify configuration | [running EAGLE](operations/running_eagle.md) + affected canonical contracts + [current status](implementation/current_status.md) |
| Add or update tests | [test contracts](testing/test_contracts.md) + affected canonical contract |
| Analyze or debug a run | [inspecting runs](operations/inspecting_runs.md) + [artifact schema](artifacts/artifact_schema.md) + [failure classification](evaluation/failure_classification.md) |
| Clean legacy code or migrate implementation | [current status](implementation/current_status.md) + [architecture gaps](implementation/architecture_gaps.md) |
| Track architecture implementation or choose the next gap | [architecture traceability matrix](implementation/architecture_traceability_matrix.md) + [architecture gaps](implementation/architecture_gaps.md) |
| Change repository ownership or docs structure | [repository map](implementation/repository_map.md) + this index |

## Canonical ownership

| Responsibility | Canonical document |
| --- | --- |
| Scope, global invariants, and precedence | [`eagle_architecture_spec.md`](eagle_architecture_spec.md) |
| Candidate model and inheritance | [`architecture/candidate_model.md`](architecture/candidate_model.md) |
| Population lifecycle, selection, and NSGA-II | [`architecture/evolutionary_flow.md`](architecture/evolutionary_flow.md) |
| Uniform Crossover | [`architecture/crossover.md`](architecture/crossover.md) |
| Strategy and Code Mutation | [`architecture/mutation.md`](architecture/mutation.md) |
| Full-file Java generation, validation, and compilation | [`architecture/java_generation.md`](architecture/java_generation.md) |
| Evaluation protocol | [`evaluation/evaluation_pipeline.md`](evaluation/evaluation_pipeline.md) |
| `game_performance` formula | [`evaluation/game_performance.md`](evaluation/game_performance.md) |
| Successful `code_quality` formula | [`evaluation/code_quality.md`](evaluation/code_quality.md) |
| Failure-stage classification and fitness | [`evaluation/failure_classification.md`](evaluation/failure_classification.md) |
| Artifact paths and payload ownership | [`artifacts/artifact_schema.md`](artifacts/artifact_schema.md) |
| Timing fields | [`artifacts/timing_schema.md`](artifacts/timing_schema.md) |
| Lineage and component provenance | [`artifacts/lineage_schema.md`](artifacts/lineage_schema.md) |
| Module ownership | [`implementation/repository_map.md`](implementation/repository_map.md) |
| Current implementation | [`implementation/current_status.md`](implementation/current_status.md) |
| Contract discrepancies and ambiguities | [`implementation/architecture_gaps.md`](implementation/architecture_gaps.md) |
| Contract-to-code/test/artifact status and implementation checklist | [`implementation/architecture_traceability_matrix.md`](implementation/architecture_traceability_matrix.md) |
| Architecture status and gaps | [`implementation/architecture_gaps.md`](implementation/architecture_gaps.md) |
| Run commands and configuration checks | [`operations/running_eagle.md`](operations/running_eagle.md) |
| Run analysis and candidate debugging | [`operations/inspecting_runs.md`](operations/inspecting_runs.md) |
| Required tests | [`testing/test_contracts.md`](testing/test_contracts.md) |

## Maintenance policy

- Do not duplicate a complete formula, schema, state transition, or path tree outside its canonical owner. Link to it.
- Update current-status, gap records, and the traceability matrix in the same change when implementation behavior changes.
- Update tests and the affected canonical document when a contract changes.
- Codex does not need to read `architeture_specification_zh.md` for normal implementation tasks.
- Any change to architecture, objective formulas, Candidate state transitions, mutation flow, evaluation protocol, artifact schemas, or documentation structure must also update `architeture_specification_zh.md`.
- Pure implementation fixes that do not alter documented behavior do not require rewriting the Chinese overview.
- Any added, removed, or renamed active documentation file must update the documentation map in `architeture_specification_zh.md`.

## Champion Final Test

Post-evolution champion comparison is owned by [`evaluation/final_test.md`](evaluation/final_test.md). It is separate from Evolution Evaluation fitness and must be read for opponent setup, candidate selection, final-test scheduling/execution, artifacts, aggregation, analysis, or reproduction work.
