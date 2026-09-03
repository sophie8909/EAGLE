# Strategy Reflection

Strategy Reflection is a Commentator-to-Coach workflow over the evaluated parent's gameplay
evidence. It uses the shared LLM endpoint and client; role settings may change
role-local enablement, temperature, and the configurable sample budget
(`llm.match_commentator.sample_count`, default `10`).

```text
all configured evaluation matches -> deterministic Global Evaluation Summary
canonical match traces -> coverage-aware sample up to 10 -> match_selection.json
each selected log -> one independent Match Commentator -> commentator_NN.json
gameplay contract + parent strategy + global summary + selected analyses -> Coach -> new_strategy_prompt
new strategy + existing code-generation prompt -> Generator -> Java candidate
```

| Role | Input | Output | Must not do |
| --- | --- | --- | --- |
| Match Commentator | Immutable gameplay contract + one selected complete match per call | One local match analysis | Modify strategy or code; generalize one match to the whole candidate |
| Coach | Immutable gameplay contract + parent strategy + global summary + selected analyses + selection metadata | New strategy prompt | Write Java or inspect raw ticks |
| Generator | Strategy + code-generation prompt | Java | Analyze matches |

## Match-trace lifecycle

MicroRTS round-state files are streamed into the canonical
`match_trace.jsonl.gz`, with one structured record and its raw source state per
available tick. If the engine emits no round-state file, the final result creates
one explicit fallback record. After all matches finish, a deterministic greedy
sampler selects up to 10 completed matches without replacement. It first covers
opponents with losses (or draws when no loss exists), then unseen maps, then fills
diverse opponent/map/player-side combinations using LOSS > DRAW > WIN. Seeded
randomness only breaks equivalent choices. `mutation/strategy_reflection/match_selection.json`
records the counts, eligible IDs, selected IDs, coverage metadata, rule, and RNG
provenance. `mutation/strategy_reflection/global_evaluation_summary.json` records deterministic
breadth across all evaluated matches, including fully-beaten opponents.

All traces belonging to the current parent population remain available while
the generation's siblings are constructed because seeded parent selection is
with replacement. After survivor selection is atomically recorded, traces for
retired parents and discarded offspring may be deleted. Traces belonging to
survivors remain available for the next generation. Compact result, performance,
opponent, map, side, round, and winner artifacts remain permanent.

Each selected raw log owns one independent Commentator role invocation. A role
invocation may make bounded retry attempts, all under the same request identity,
when transport, parsing, or semantic validation fails. The Coach receives only
the resulting diagnoses and the deterministic global summary; raw game logs are
never concatenated into the Coach request. Both roles also receive the same
immutable strategy-level gameplay contract. It is closed-world domain context,
not evidence: it permits any strategy type expressible with MicroRTS entities,
production, actions, and observable state, and prevents unsupported RTS concepts
from propagating into the replacement policy.

The canonical response has top-level strategy objects and integer-backed
`turning_points`. At the parser boundary EAGLE also normalizes the bounded local-
model variant observed in real runs: one `match_analysis` wrapper, string strategy
summaries, and `key_observations[].time` ranges whose first integer is the source
tick. This normalization never forwards `recommendations`; missing numeric tick
evidence remains a terminal Commentator attempt failure.

## Artifacts and traceability

Per-match artifacts live under `commentary/<match_id>/`. Candidate-level role
artifacts live under `mutation/strategy_reflection/`:

```text
mutation/strategy_reflection/
  metadata.json
  parent_strategy_prompt.txt
  selected_matches.json
  commentator_01.json
  ...
  coach_input.json
  coach_prompt.txt
  coach_request.json
  coach_response.json
  coach_raw.txt
  coach_output.json
  coach_result.json
  child_strategy_prompt.txt
  generator_strategy_input.txt
```

Every role envelope records `role`, `candidate_id`, `generation_index`,
`request_id`, model-configuration identity, prompt version, and schema version.
Every attempt additionally records UTC start/finish timestamps, monotonic
duration, status, and error. The same attempt has one compact `llm_request`
event in run `timing.jsonl`; the exact prompt/response remains only in the
candidate-owned role artifacts and is not duplicated under `llm_logs/`.
The numbered Commentator files contain the exact parsed responses in call order.
`coach_input.json` contains the semantic render inputs and selected Coach prompt
name, while `coach_prompt.txt` is the exact bounded prompt sent.
`coach_output.json` is the parsed response before validation or normalization;
it therefore preserves any model-provided parent-policy echo losslessly.
`coach_result.json` is the validated runtime result and always takes
`parent_strategy_prompt` from the authoritative Coach input rather than trusting
that echo. The post-normalization
`child_strategy_prompt.txt` is the value stored in the child genotype, and
`generator_strategy_input.txt` is written at the pre-Generator boundary from
the exact strategy placeholder value.

The implementation has no separate field named `policy`. The reusable strategy
policy is the genotype field `Candidate.strategy_prompt`; Coach directly returns
it as `new_strategy_prompt`, after which deterministic prompt normalization is
the only transformation before Generator use.

## Failure and budgeting rules

Commentator failure does not change fitness. Transport, JSON parsing, and
role-semantic validation share the configured bounded retry budget, and every
attempt retains its raw response and validation status. Coach receives an
unavailable entry for an individual selected match only when at least one other
selected match produced a valid diagnosis. With zero valid diagnoses, Strategy
Mutation fails without calling Coach and preserves the parent strategy. Coach
receives the full aggregate win/draw/loss distribution and selection metadata,
so selected commentary is never mistaken for the complete evaluation
distribution. Coach parsing and semantic validation use the same bounded retry
contract. Terminal Coach failure leaves the parent strategy unchanged and
records a role-attributed failure. Generator failures follow the existing
Java-generation failure contract.

Commentator budgeting prioritizes metadata, the selected raw log, and schema;
Coach receives compact analyses, the all-match global summary, parent strategy,
and selection metadata but never raw ticks. Generator budgeting is
unchanged.

Code Reflection remains a separate mutation path for Java validation,
compilation, integration, and code-quality evidence.

## Strategy diversity metadata

Coach returns the replacement strategy prompt and a structured
`strategy_signature` in the same response. The persisted signature has the
canonical fields `opening`, `economy`, `production`, `attack_timing`,
`combat_style`, `expansion`, `defense`, and `target_priority`. Values are
normalized deterministically; old candidates without the fields remain
`unknown` and are never parsed from raw prompt text.

`build_strategy_niche(signature)` derives a stable major-structure label from
attack timing, primary production (`mixed` for multiple unit types), and
combat style, with a stable `unknown` fallback. Each candidate snapshot and
candidate genotype stores `strategy_signature`, `strategy_niche`, and, for a
Strategy Mutation, `mutation_intent`, `parent_strategy_niche`, and
`niche_changed`.

Every Strategy Mutation receives exactly one intent from the run RNG:

| Intent | Default probability | Meaning |
| --- | ---: | --- |
| `REFINE` | 0.40 | Preserve strategic identity and make evidence-backed local changes. |
| `COUNTER` | 0.25 | Respond to opponent behavior identified by the selected diagnoses. |
| `STRUCTURAL` | 0.20 | Reorganize major opening/economy/production/timing/expansion/defense relationships. |
| `ALTERNATIVE` | 0.15 | Solve the diagnosed problem with a different strategic approach. |

The run-level `archives/strategy.json` keeps one successfully evaluated
representative per known niche, replacing it only when game performance is
better (then code quality and deterministic candidate-ID tie-breaking). It is
storage and analysis metadata only; it is not a population and never enters
the ten opponent-wise lexicase cases.

Generation snapshots include analysis-only metrics under
`strategy_diversity`: unique niches, dominant niche ratio, new and revisited
niches, mean categorical signature distance, and overall/per-intent niche
change rates. `./analyze.sh` emits `strategy_diversity.csv`,
`strategy_niches.csv`. Strategy diversity remains available as CSV analysis
metadata; it does not add plots to the compact current plot set. These metrics do not alter
the ten opponent scores, aggregate reporting, survivor selection, crossover,
or parent selection.

Generation snapshots also expose `light_rush_win_rate` and
`heavy_rush_win_rate`: the number of candidates whose canonical opponent-level
record has more wins than losses against that opponent, divided by the full
generation population. They are reporting/regression metrics only and are
included in `generation_metrics.csv` by `./analyze.sh`.
