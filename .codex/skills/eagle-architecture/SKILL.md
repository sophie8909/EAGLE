---
name: eagle-architecture
description: Route and implement EAGLE Candidate model, genotype/phenotype, state-transition, overall pipeline, parent selection, or opponent-wise lexicase architecture changes. Use for edits to candidate records, search orchestration, selection, Java inheritance, or cross-cutting architecture contracts.
---

# EAGLE architecture workflow

## Read first

1. Read `docs/implementation/architecture_traceability_matrix.md` to select the tracked contract and dependency layer.
2. Read `docs/eagle_architecture_spec.md` completely for cross-cutting changes; otherwise read the affected normative sections.
3. Read `docs/architecture/overview.md` and `docs/architecture/candidate_model.md`.
4. Read `docs/architecture/evolutionary_flow.md` for pipeline/selection work.
5. Read `docs/artifacts/lineage_schema.md` when candidate identity, inheritance, or provenance changes.
6. Read `docs/implementation/current_status.md` and `docs/implementation/architecture_gaps.md` before editing code.

Do not read `docs/architeture_specification_zh.md` as an implementation source.

## Preserve

- Preserve the configured candidate boundary: default `generated_phenotype` has
  exactly the policy and code-generation prompt genes; explicit
  `inherited_genotype` adds one complete inherited-Java component with
  independent provenance.
- Keep generated full-file Java as the current phenotype. In inherited mode,
  keep the selected pre-generation Java input separate from that newly
  generated phenotype and pass it to the Generator without letting mutation
  edit it directly.
- Make every offspring pass through final Java generation after crossover and optional mutation.
- Keep exactly seven maximized opponent fitness cases and seeded lexicase parent/survivor selection; weighted `game_performance` and `code_quality` are diagnostics only.
- Keep failed candidates in lexicase with the canonical per-case failure sentinel and failure-stage diagnostics.
- Preserve the exact CandidateAgent/integration contract from the canonical owners.
- Persist component provenance, lineage, artifacts, and timing.
- Do not introduce GEPA, ACE, MIPRO, CAPO, surrogate search, or runtime LLM-controlled agents.

## Workflow

1. Identify the canonical owner in `docs/README.md`.
2. Compare the request with the specification and active source/tests/config.
3. If the specification is ambiguous, update a `Decision required` row in `docs/implementation/architecture_gaps.md`; do not guess.
4. Implement only the requested dependency layer.
5. Add/update the contract tests in `docs/testing/test_contracts.md`.
6. Update current status, gap status, repository map, and migration plan where affected.
7. Update artifact/timing/lineage schemas when serialized fields or flow changes.
8. Run WSL-first validation.

## Common files

`eagle/candidate.py`, `eagle/search.py`, `eagle/selection.py`, `eagle/evaluation.py`, `eagle/config.py`, `eagle/artifacts.py`, affected operator/evaluation modules, `tests/`, and `configs/`.

## Documentation policy

Update `docs/architeture_specification_zh.md` for architecture, objective, Candidate transition, mutation/evaluation protocol, artifact schema, or docs-structure changes. Pure behavior-preserving fixes do not require it. Any active documentation add/remove/rename must update its documentation map.
