# Strategy Reflection

Strategy Reflection is a Commentator-to-Coach workflow over the evaluated parent's gameplay
evidence. It uses the shared LLM endpoint and client; role settings may change
role-local enablement, temperature, and the configurable sample budget
(`llm.match_commentator.sample_count`, default `10`).

```text
all configured evaluation matches -> deterministic Global Evaluation Summary
temporary complete logs -> coverage-aware sample up to 10 -> match_selection.json
each selected log -> one independent Match Commentator -> match_analysis.json
parent strategy + global summary + selected analyses -> Coach -> new_strategy_prompt
new strategy + existing code-generation prompt -> Generator -> Java candidate
```

| Role | Input | Output | Must not do |
| --- | --- | --- | --- |
| Match Commentator | One selected complete match per call | One local match analysis | Modify strategy or code; generalize one match to the whole candidate |
| Coach | Parent strategy + global summary + selected analyses + selection metadata | New strategy prompt | Write Java or inspect raw ticks |
| Generator | Strategy + code-generation prompt | Java | Analyze matches |

## Match-log lifecycle

MicroRTS round-state files are streamed into a stable `match_log.jsonl.gz` with
one record per executed tick. After all matches finish, a deterministic greedy
sampler selects up to 10 completed matches without replacement. It first covers
opponents with losses (or draws when no loss exists), then unseen maps, then fills
diverse opponent/map/player-side combinations using LOSS > DRAW > WIN. Seeded
randomness only breaks equivalent choices. `reflection/match_selection.json`
records the counts, eligible IDs, selected IDs, coverage metadata, rule, and RNG
provenance. `reflection/global_evaluation_summary.json` records deterministic
breadth across all evaluated matches, including fully-beaten opponents.

Unselected raw logs are deleted before any commentary call. Selected logs are
deleted after successful commentary or bounded terminal failure. Compact result,
performance, opponent, map, side, round, and winner artifacts remain permanent.

Each selected raw log is sent to exactly one independent Commentator call. The
Coach receives only the resulting diagnoses and the deterministic global summary;
raw game logs are never concatenated into the Coach request.

## Artifacts and traceability

Per-match artifacts live under `commentary/<match_id>/`. Candidate-level role
artifacts live under `reflection/`:

```text
reflection/
  coach_request.json
  coach_response.json
  coach_result.json
```

Every role envelope records `role`, `candidate_id`, `generation_index`,
`request_id`, model-configuration identity, prompt version, and schema version.
Coach results retain both the parent and replacement strategy prompts.

## Failure and budgeting rules

Commentator failure does not change fitness; Coach receives an unavailable
entry for that selected match. Coach receives the full aggregate win/draw/loss
distribution and selection metadata, so selected commentary is never mistaken
for the complete evaluation distribution. Coach failure leaves the parent strategy
unchanged and records a role-attributed failure. Generator failures follow the
existing Java-generation failure contract.

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

The run-level `strategy_archive.json` keeps one successfully evaluated
representative per known niche, replacing it only when game performance is
better (then code quality and deterministic candidate-ID tie-breaking). It is
storage and analysis metadata only; it is not a population and never enters
the seven opponent-wise lexicase cases.

Generation snapshots include analysis-only metrics under
`strategy_diversity`: unique niches, dominant niche ratio, new and revisited
niches, mean categorical signature distance, and overall/per-intent niche
change rates. `./analyze.sh` emits `strategy_diversity.csv`,
`strategy_niches.csv`. Strategy diversity remains available as CSV analysis
metadata; it does not add plots to the compact current plot set. These metrics do not alter
the seven opponent scores, aggregate reporting, survivor selection, crossover,
or parent selection.

Generation snapshots also expose `light_rush_win_rate` and
`heavy_rush_win_rate`: the number of candidates whose canonical opponent-level
record has more wins than losses against that opponent, divided by the full
generation population. They are reporting/regression metrics only and are
included in `generation_metrics.csv` by `./analyze.sh`.
