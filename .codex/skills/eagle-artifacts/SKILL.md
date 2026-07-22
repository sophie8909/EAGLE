---
name: eagle-artifacts
description: Implement or review EAGLE run, generation, candidate, mutation, Java-generation, validation, compilation, integration, match, objective, lineage, raw-LLM, resolved-config, schema-version, and timing persistence. Use for artifact paths, payloads, readers, migrations, hashes, or timing changes.
---

# EAGLE artifact workflow

## Read first

- `docs/implementation/architecture_traceability_matrix.md` for the selected persistence contract and dependencies.
- `docs/eagle_architecture_spec.md` sections 21–27.
- `docs/artifacts/artifact_schema.md`.
- `docs/artifacts/timing_schema.md` for timing/attempt work.
- `docs/artifacts/lineage_schema.md` for ancestry/provenance work.
- `docs/implementation/current_status.md` and `docs/implementation/architecture_gaps.md`.

## Preserve

- Reconstruct exact pre-generation genotype, generated phenotype, lineage, variation, every LLM call, every pipeline stage, all matches, objectives, and timing.
- Persist raw LLM output before parsing.
- Keep one candidate directory and one directory per match.
- Store actual resolved configuration and explicit artifact/objective schema versions.
- Retain partial evidence on failure/interruption.
- Avoid duplicate canonical files; version compatibility aliases and give them a removal plan.

## Workflow

1. Identify the canonical schema owner and whether the specification marks physical layout as recommended or evidence as required.
2. Define versioned fields and readback/migration behavior before writers.
3. Write identity/lineage/genotype before external calls; use atomic summary updates.
4. Hash source/classes so compile and match identity is auditable.
5. Reject or explicitly migrate unknown/legacy schema versions.
6. Add golden-tree, schema, interruption, and reconstruction tests.

## Common files

`eagle/artifacts.py`, `eagle/llm_logging.py`, `eagle/search.py`, `eagle/evaluation.py`, `evaluation/microrts_runner.py`, analysis scripts, tests, and configuration serialization.

## Documentation updates

Update the relevant artifact/timing/lineage owner, repository map/current status/gaps, operational readers, and the Chinese documentation map. Any schema or docs-structure change requires updating the Chinese overview.

## Prohibited legacy behavior

No overwritten pre-generation code, discarded raw response, unversioned schema, input config presented as resolved config, duplicate result/source files without compatibility policy, `seed_none` silently presented as reproducible, or old split/function-body schema treated as active.

