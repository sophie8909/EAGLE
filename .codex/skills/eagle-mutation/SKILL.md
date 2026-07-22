---
name: eagle-mutation
description: Implement or review EAGLE Strategy Reflection, Strategy Prompt Rewrite, Code Reflection, Code Generation Prompt Rewrite, mutation selection, mutation LLM logging, and mutation artifacts. Use whenever Strategy Mutation or Code Mutation behavior, prompts, evidence, retries, or state transitions change.
---

# EAGLE mutation workflow

## Read first

- `docs/implementation/architecture_traceability_matrix.md` for the selected mutation contract and dependencies.
- `docs/eagle_architecture_spec.md` sections 7–10, 20, 22, and 28.
- `docs/architecture/mutation.md`.
- `docs/architecture/candidate_model.md`.
- `docs/artifacts/artifact_schema.md`, `docs/artifacts/timing_schema.md`, and `docs/artifacts/lineage_schema.md`.
- `docs/implementation/current_status.md` and `docs/implementation/architecture_gaps.md`.

## Preserve

- Strategy Mutation: Reflection LLM, Strategy Rewrite LLM, final Java Generation LLM.
- Code Mutation: Reflection LLM, Generation Prompt Rewrite LLM, final Java Generation LLM.
- Strategy Mutation changes only `strategy_prompt`; Code Mutation changes only `generation_prompt`.
- Mutation never directly edits Java.
- `previous_code` remains the selected parent's latest evaluated Java until final child generation produces the next phenotype.
- Select evidence through recorded provenance; do not compare prompt strings.

## Implement

1. Construct typed evidence matching the canonical input lists.
2. Persist each request before the call and each raw response before parsing.
3. Validate Reflection and rewrite-only response contracts.
4. Record model/backend, retries, errors, and timing per attempt.
5. Preserve earlier artifacts when Rewrite or final Java generation fails.
6. Route the complete mutated genotype to the separate final generation stage.

## Common files

`eagle/mutation.py`, `eagle/search.py`, `eagle/candidate.py`, `generation/backend.py`, `eagle/llm_logging.py`, `eagle/artifacts.py`, and mutation/artifact tests.

## Required tests and docs

Test ordered call counts, component isolation, both state transitions, evidence routing, response rejection, retries, failure retention, timing, and artifacts. Update mutation docs, artifact/timing schemas, current status/gaps, and the Chinese overview when documented flow or state changes.

## Prohibited legacy behavior

No no-op rule backend presented as mutation, one-call mutation, direct Java/method-body mutation, missing Reflection/Rewrite, unbounded error-history prompts, discarded raw output, or surrogate/runtime-LLM flow.

