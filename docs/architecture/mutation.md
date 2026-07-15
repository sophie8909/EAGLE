# Mutation

## Normative source

See specification sections 7 through 10 and state-transition examples 28.2 and 28.3. Mutation persistence is owned by [`../artifacts/artifact_schema.md`](../artifacts/artifact_schema.md); LLM timing is owned by [`../artifacts/timing_schema.md`](../artifacts/timing_schema.md).

## Shared contract

Mutation has exactly two types: `strategy_mutation` and `code_mutation`. Each uses two separate LLM stages:

1. Reflection analyzes evidence and returns reflection text.
2. Prompt Rewrite consumes the reflection and returns only the rewritten prompt component.

The final Java Generation LLM is a third call after mutation. Reflection and Rewrite never produce or edit Java directly.

## Strategy Mutation

Changes only `strategy_prompt`; preserves `previous_code` and `generation_prompt`.

Reflection inputs must include the current strategy, parent generated Java, opponent identity, the complete 10-match summary, per-match results, win/draw/loss counts, final resources, material/survival/round-state evidence, and behavior summary. The response is `strategy_reflection` and must not rewrite prompts or generate Java.

Rewrite inputs are the original strategy, reflection, parent generated Java, and game-evaluation summary. The response is only `new_strategy_prompt`.

Canonical state transition:

```text
before mutation:      A1 + B2 + C1
after rewrite:        A2 + B2 + C1
after Java generation:A2 + B3 + C1
next inherited state: A2 + B3 + C1
```

## Code Mutation

Changes only `generation_prompt`; preserves `strategy_prompt` and `previous_code`.

Reflection inputs must include the strategy, current generation prompt, parent Java, latest child Java if any, raw generation response, validation/compile/integration/runtime results, completed-match count, function and strategy-alignment scores, and failure stage/category/reason. The response is `code_reflection` and must not generate replacement Java.

Rewrite inputs are the original generation prompt, reflection, strategy, parent Java, and code-quality summary. The response is only `new_generation_prompt` suitable for full-file regeneration.

Canonical state transition:

```text
before mutation:      A1 + B2 + C1
after rewrite:        A1 + B2 + C2
after Java generation:A1 + B3 + C2
next inherited state: A1 + B3 + C2
```

## Mutation selection

- Use Strategy Mutation when reliable completed-game evidence exists.
- Prefer Code Mutation for generation, validation, compilation, integration, or runtime failures; low capability/alignment; or excessive compiler warnings.
- A candidate without reliable gameplay results must not use Strategy Mutation as its primary operator.
- Select feedback evidence by component provenance and mutation responsibility, not by prompt equality.

## Persistence checklist

- Save both requests and raw responses even if a later stage fails.
- Record mutation type, models, attempts, status, and errors.
- Record that no mutation was applied with explicit `applied: false` metadata.
- Save the final Java generation request/response separately from mutation calls.
- Include every attempt in candidate timing.

## Required tests

- Three distinct calls occur in order for each mutated offspring.
- Strategy Mutation changes only `strategy_prompt`; Code Mutation changes only `generation_prompt`.
- Reflection failure, Rewrite failure, and final generation failure retain all earlier artifacts.
- Response parsing rejects Java/prose where a rewritten prompt alone is required.
- Mutation selection follows available evidence and failure stage.
- The canonical state transitions produce the correct next-generation `previous_code`.

## Prohibited legacy behavior

- rule-based no-op mutation presented as an LLM mutation;
- one-call mutation;
- mutation without Reflection and Rewrite;
- direct Java edits, patches, or method-body mutation;
- unbounded accumulation of old compiler errors in `generation_prompt`;
- discarded raw responses or unlogged retries.


## Implementation milestone

Phase 2A implements the Reflection stage for both mutation types with typed evidence, a backend abstraction, bounded retries, raw request/response artifacts, and UTC attempt timing. It intentionally does not rewrite prompts or generate Java; those stages are delivered in Phase 2B and 2C.

## Phase 2B implementation milestone

Phase 2B adds Strategy Prompt Rewrite and Generation Prompt Rewrite after Reflection. Rewritten prompt components are first-class candidate state, original prompt values are retained in mutation artifacts, and Java generation remains deferred to Phase 2C.
