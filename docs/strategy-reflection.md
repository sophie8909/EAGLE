# Strategy Reflection

Strategy Reflection is a four-role workflow over the evaluated parent's gameplay
evidence. It uses the shared LLM endpoint and client; role settings may change
only role-local enablement and temperature.

```text
complete match log -> Match Commentator -> match_analysis.json
all match analyses -> Manager -> manager_analysis.json
parent strategy + manager plan -> Coach -> new_strategy_prompt
new strategy + existing code-generation prompt -> Generator -> Java candidate
```

| Role | Input | Output | Must not do |
| --- | --- | --- | --- |
| Match Commentator | One complete match | Match analysis | Modify strategy or code |
| Manager | All match analyses | Improvement plan | Write final prompt or code |
| Coach | Parent strategy + Manager plan | New strategy prompt | Write Java |
| Generator | Strategy + code-generation prompt | Java | Analyze matches |

## Match-log lifecycle

MicroRTS round-state files are streamed into a stable `match_log.jsonl.gz` with
one record per executed tick. Records contain match metadata, both players'
resources, deterministic unit ordering, and only state exposed by the engine.
The compressed trace is temporary. After Commentator success, or after bounded
Commentator retries have produced `commentary_failure.json`, the raw trace is
deleted. `match_result.json`, `commentary/match_analysis.json`, and
`commentary/commentary_status.json` remain permanent.

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
entry for that match. Manager or Coach failure leaves the parent strategy
unchanged and records a role-attributed failure. Generator failures follow the
existing Java-generation failure contract.

Commentator budgeting prioritizes metadata, complete tick coverage, and schema;
Manager receives compact analyses and aggregate results but never raw ticks;
Coach receives only the parent strategy and Manager plan. Generator budgeting is
unchanged.

Code Reflection remains a separate mutation path for Java validation,
compilation, integration, and code-quality evidence.
