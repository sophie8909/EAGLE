---
name: eagle-migration
description: Plan and implement EAGLE refactors from current repository behavior toward docs/eagle_architecture_spec.md, including gap closure, legacy removal, config/test updates, dependency ordering, and compatibility cleanup. Use when closing architecture gaps or removing obsolete split-agent, surrogate, runtime-LLM, or legacy objective behavior.
---

# EAGLE migration workflow

## Read first

- `docs/implementation/architecture_traceability_matrix.md` as the primary implementation tracker.
- `docs/eagle_architecture_spec.md` and `docs/README.md`.
- `docs/implementation/current_status.md`.
- `docs/implementation/architecture_gaps.md`.
- `docs/implementation/migration_plan.md`.
- The canonical contract(s) for the selected gap and `docs/testing/test_contracts.md`.

## Select scope

1. Choose one dependency-coherent migration phase or gap cluster.
2. Treat A-01/A-02 as resolved. Resolve any future ambiguous contract before implementation and never encode an undocumented choice.
3. Inventory the live worktree and preserve unrelated changes.
4. Keep migration toward EAGLE only; do not reintroduce GEPA, ACE, MIPRO, CAPO, surrogate search, runtime LLM control, split Java generation, or fixed method-body evolution.

## Execute

1. Update foundational data/schema contracts before dependent operators/scoring.
2. Implement code, tests, configuration, artifacts/readers, and docs as one coherent behavior change.
3. Fence legacy readers by explicit schema/version; do not let compatibility override active writes.
4. Run WSL-first unit/contract validation and the smallest relevant real integration check.
5. Update current status, affected gap statuses, migration plan, and repository map.

## Completion rules

- Close a gap only with passing tests and matching source/config/artifact behavior.
- Do not use historical runs as proof of current compliance.
- Do not run a full evolutionary experiment unless explicitly requested.
- Remove obsolete code/docs rather than preserving misleading compatibility without maintenance value.
- Update the Chinese overview for architecture/formula/state/protocol/schema/docs-structure changes; pure behavior-preserving fixes do not require it.

## Common files

Potentially all active Python modules, `tests/`, `configs/`, `scripts/`, and the affected canonical documentation. Follow the migration phase boundary to keep changes reviewable.

