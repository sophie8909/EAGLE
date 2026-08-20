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
2. Temporarily retain complete match logs and use a deterministic greedy sampler with a
   budget of up to 10 matches. It first covers opponents with losses (or draws when an
   opponent has no loss), then unseen maps, then fills with diverse opponent/map/side
   combinations using `LOSS > DRAW > WIN` and seeded random tie breaking.
3. Persist `reflection/match_selection.json` and
   `reflection/global_evaluation_summary.json`, delete unselected raw logs, and run
   exactly one Match Commentator call per selected match. Delete each selected raw log
   after its terminal commentary handling.
4. Build the Global Evaluation Summary deterministically from all evaluated matches;
   it provides breadth while the independent Commentator diagnoses provide depth.
5. Coach receives the parent strategy, the global summary, and only the selected
   Commentator analyses.
6. Coach receives the parent strategy, selected diagnoses, and one deterministic
   mutation intent, then replaces the parent `strategy_prompt` and emits a
   categorical strategy signature.
7. Generator receives the new strategy and the existing code-generation prompt.

The Match Commentator never rewrites strategy or Java. The Coach knows that
commentary is representative evidence and never treats it as the complete evaluation
distribution. Fully beaten opponents are explicitly marked as capabilities to preserve.
The Coach writes the replacement strategy prompt but never writes Java. Raw ticks are never sent
to Coach. See [`../strategy-reflection.md`](../strategy-reflection.md)
for schemas, artifact ownership, failure semantics, and budgeting.

The four mutation intents are `REFINE` (local evidence-backed improvement),
`COUNTER` (respond to the selected opponent behavior), `STRUCTURAL` (permit a
major strategic reorganization), and `ALTERNATIVE` (solve the same problem with
a different strategy). The default run-RNG probabilities are 0.40, 0.25, 0.20,
and 0.15 respectively. Strategy niches, the run-level archive, and diversity
metrics are analysis metadata only and do not alter opponent-wise fitness or
lexicase selection.

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

Lexicase selects the parent. One `ReflectionOperatorController` then selects
exactly one of the two mutation operators:

- `strategy_reflection` → Strategy Reflection → Commentator/Coach → strategy prompt rewrite;
- `generate_code_reflection` → Generate-Code Reflection → generation prompt rewrite.

`reflection_operator_mode` has exactly three values:

- `static`: fixed Strategy/Code probabilities for the whole run. No reward,
  EMA update, opponent comparison, or parent-vs-offspring match is performed.
- `aos_opponent`: adaptive probabilities using the historical execution-first
  change in performance against the seven evolutionary opponents.
- `aos_head2head`: adaptive probabilities using direct offspring-vs-parent-A
  MicroRTS matches.

`strategy_reflection_probability` and `code_reflection_probability` are fixed
probabilities in `static` and initial probabilities in both AOS modes. They
must each be in `[0,1]` and sum to `1.0`. `aos_minimum_probability` is parsed
for every mode but affects only adaptive updates; with two operators it must be
in `[0,0.5]`. Production starts at Strategy `0.20` / Generate-Code `0.80` and
uses a `0.10` adaptive floor.

For `aos_opponent`, candidate execution is compared first: failed parent to
runnable child is `+1.0`, runnable parent to failed child is `-1.0`, and two
failed candidates are `-0.1`. If both are runnable, each completed opponent
case is ranked LOSS=`0`, DRAW=`1`, WIN=`2`, where wins greater than losses is a
WIN, losses greater than wins is a LOSS, and a tied record is a DRAW. The exact
reward is `(improved cases - regressed cases) / compared cases`, or `0.0` when
no case is comparable. This mode reuses normal evaluation and launches no
additional matches.

For `aos_head2head`, after a runnable child completes its normal 126-match
evaluation, its compiled class plays parent A's compiled class on the configured
maps, rounds, and both player sides (currently `3 × 3 × 2 = 18` matches).
No Java is regenerated and no seven-opponent matrix is rerun. Its reward is

```text
(offspring wins + 0.5 × draws) / valid direct matches
```

and is therefore in `[0, 1]`. An offspring execution failure skips direct
matches and receives `0.0`. A parent that has no loadable compiled phenotype is
an execution repair and receives `1.0`; that exceptional source is recorded
separately. EMA uses `Q_new = 0.8 × Q_old + 0.2 × reward`, then probability
matching reapplies the configured floor. Both AOS reward providers feed this
same updater; alpha remains `0.20`. Direct matches never alter the seven-case
fitness, weighted Game Performance, lexicase, or final test. Select reflection
evidence by component provenance and mutation responsibility, not prompt equality.

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
