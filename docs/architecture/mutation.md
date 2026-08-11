# Mutation

Reflection and Rewrite requests are hard-limited before transport. The shared LLM
transport keeps the beginning (instructions) and end (latest evidence) of an oversized
request, inserts an explicit truncation marker, and sends at most 60,000 characters.
Full telemetry and raw evidence remain in candidate artifacts; they are not silently
discarded from persistence or allowed to overflow the llama.cpp context.

The evaluation-to-mutation hand-off is the typed `ReflectionContext` in
`eagle/mutation.py`. Its authoritative objectives, evaluation status, failure fields,
and generation/compilation/integration/game/Code Quality evidence are copied from the
evaluated Candidate snapshot. Reflection does not recompute fitness or infer missing
stage results from legacy scalar fields.

## Normative source

See specification sections 7 through 10 and state-transition examples 28.2 and 28.3. Mutation persistence is owned by [`../artifacts/artifact_schema.md`](../artifacts/artifact_schema.md); LLM timing is owned by [`../artifacts/timing_schema.md`](../artifacts/timing_schema.md).

## Shared contract

Strategy Mutation and Code Mutation are separate. Strategy Mutation changes only
the `strategy_prompt` genotype component and its strategy metadata; Code Mutation
changes only `generation_prompt`. The final Java Generator remains a separate
stage after either mutation.

## Strategy Mutation

Strategy Reflection is a sports-team workflow:

1. Complete the configured evaluation matrix and compute Game Performance from every match.
2. Temporarily retain complete match logs, partition completed results into losses, draws,
   and wins, and select one pool with strict `loss > draw > win` priority.
3. Use the run-derived reproducible RNG to sample at most three matches from that pool
   without replacement. Within the selected outcome pool, higher `opponent_weight`
   tiers are selected before lower-weight tiers; lower-priority outcomes never
   backfill the sample and weights are not sampling probabilities.
4. Persist `reflection/match_selection.json`, delete unselected raw logs, and run Match
   Commentator only for the selected matches. Delete each selected raw log after terminal
   commentary handling.
5. Manager receives complete aggregate evaluation evidence plus only the selected analyses.
6. Coach receives the parent strategy, Manager plan, and one deterministic
   mutation intent, then replaces the parent `strategy_prompt` and emits a
   categorical strategy signature.
7. Generator receives the new strategy and the existing code-generation prompt.

The Match Commentator never rewrites strategy or Java. The Manager knows that
commentary is a biased worst-outcome sample and never treats it as the complete
evaluation distribution. The Manager never writes
the final prompt or Java. The Coach never writes Java. Raw ticks are never sent
to Manager or Coach. See [`../strategy-reflection.md`](../strategy-reflection.md)
for schemas, artifact ownership, failure semantics, and budgeting.

The four mutation intents are `REFINE` (local evidence-backed improvement),
`COUNTER` (respond to the selected opponent behavior), `STRUCTURAL` (permit a
major strategic reorganization), and `ALTERNATIVE` (solve the same problem with
a different strategy). The default run-RNG probabilities are 0.40, 0.25, 0.20,
and 0.15 respectively. Strategy niches, the run-level archive, and diversity
metrics are analysis metadata only and do not alter fitness or NSGA-II.

Canonical state transition:

```text
before mutation:       A1 + B2 + C1
after Coach:            A2 + B2 + C1
after Java generation:  A2 + B3 + C1
next inherited state:   A2 + B3 + C1
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
- Save the versioned `reflection_context.json` evidence snapshot with candidate ID,
  operation, objectives, evaluation status, failure cause, and stage evidence.
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


## Phase 2C implementation milestone

Phase 2C connects both mutation types to the existing final Java Generation boundary.
The rewritten genotype is passed unchanged into the candidate generation input, which
contains the rewritten strategy prompt or generation prompt, inherited previous_code,
and the other prompt component. Evaluation then stores the new generated_java phenotype
while retaining previous_code. Mutation and generation have independent canonical
artifacts and timing records, including terminal generation failures.
