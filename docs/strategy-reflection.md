# Strategy Reflection

Strategy Reflection is a four-role workflow over the evaluated parent's gameplay
evidence. It uses the shared LLM endpoint and client; role settings may change
only role-local enablement and temperature.

```text
all configured evaluation matches -> aggregate Game Performance
temporary complete logs -> strict loss/draw/win selection -> match_selection.json
selected logs only -> Match Commentator -> selected match_analysis.json
aggregate results + selected analyses -> Manager -> manager_analysis.json
parent strategy + manager plan -> Coach -> new_strategy_prompt
new strategy + existing code-generation prompt -> Generator -> Java candidate
```

| Role | Input | Output | Must not do |
| --- | --- | --- | --- |
| Match Commentator | At most three selected complete matches | Selected match analyses | Modify strategy or code; generalize one match to the whole candidate |
| Manager | Complete aggregate results + selected analyses + selection metadata | Improvement plan | Write final prompt or code; treat selected matches as unbiased |
| Coach | Parent strategy + Manager plan | New strategy prompt | Write Java |
| Generator | Strategy + code-generation prompt | Java | Analyze matches |

## Match-log lifecycle

MicroRTS round-state files are streamed into a stable `match_log.jsonl.gz` with
one record per executed tick. After all matches finish, completed outcomes are
partitioned into `loss`, `draw`, and `win`. The first non-empty pool in that order
is the only eligible pool; up to three entries are sampled without replacement
using a seed derived from the EA run seed, generation, candidate, and reflection
invocation. `reflection/match_selection.json` records the counts, eligible IDs,
selected IDs, rule, and RNG provenance.

Unselected raw logs are deleted before any commentary call. Selected logs are
deleted after successful commentary or bounded terminal failure. Compact result,
performance, opponent, map, side, round, and winner artifacts remain permanent.

Long traces are chunked on complete tick records. Chunks are non-overlapping and
the final Commentator synthesis represents the entire trace.

## Artifacts and traceability

Per-match artifacts live under `commentary/<match_id>/`. Candidate-level role
artifacts live under `reflection/`:

```text
reflection/
  manager_request.json
  manager_response.json
  manager_analysis.json
  coach_request.json
  coach_response.json
  coach_result.json
```

Every role envelope records `role`, `candidate_id`, `generation_index`,
`request_id`, model-configuration identity, prompt version, and schema version.
Coach results retain both the parent and replacement strategy prompts.

## Failure and budgeting rules

Commentator failure does not change fitness; Manager receives an unavailable
entry for that selected match. Manager receives the full aggregate win/draw/loss
distribution and selection metadata, so selected commentary is never mistaken
for the complete evaluation distribution. Manager or Coach failure leaves the parent strategy
unchanged and records a role-attributed failure. Generator failures follow the
existing Java-generation failure contract.

Commentator budgeting prioritizes metadata, complete tick coverage, and schema;
Manager receives compact analyses and aggregate results but never raw ticks;
Coach receives only the parent strategy and Manager plan. Generator budgeting is
unchanged.

Code Reflection remains a separate mutation path for Java validation,
compilation, integration, and code-quality evidence.
