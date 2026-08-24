# Timing schema

This is the canonical owner of candidate and LLM-attempt timing fields. Normative source: specification section 25.

## Requirements

- Use UTC timestamps with timezone information.
- Use monotonic clocks for durations where available; timestamps support audit, not duration arithmetic.
- Persist an attempt record for every LLM request, including retries and failures.
- Represent skipped optional stages with `null`, not fabricated zero-duration calls.
- Candidate total time includes all stages and persistence overhead defined by the implementation's schema version.

## Candidate `timing.json`

```json
{
  "candidate_started_at": "",
  "candidate_finished_at": "",
  "total_duration_seconds": 0.0,
  "selection_duration_seconds": 0.0,
  "crossover_duration_seconds": 0.0,
  "reflector_llm": {
    "started_at": null,
    "finished_at": null,
    "duration_seconds": null,
    "attempts": []
  },
  "rewriter_llm": {
    "started_at": null,
    "finished_at": null,
    "duration_seconds": null,
    "attempts": []
  },
  "generation_llm": {
    "started_at": "",
    "finished_at": "",
    "duration_seconds": 0.0,
    "attempts": []
  },
  "validation_duration_seconds": 0.0,
  "compilation_duration_seconds": 0.0,
  "integration_duration_seconds": 0.0,
  "strategy_alignment_llm": {
    "started_at": null,
    "finished_at": null,
    "duration_seconds": null,
    "attempts": []
  },
  "matches_total_duration_seconds": 0.0,
  "match_durations_seconds": []
}
```

For a successful evaluation, `match_durations_seconds` has exactly 126 entries.
For partial failure it has one entry per attempted match and is interpreted with
match statuses.

Generation-zero seed loading is not an LLM request. Its `generation_llm`
record has null start/finish/duration fields and an empty attempt list. Strategy
Alignment likewise has null timing and no attempts when an empty policy makes
the diagnostic not applicable.

## LLM attempt record

```json
{
  "attempt": 1,
  "started_at": "",
  "finished_at": "",
  "duration_seconds": 0.0,
  "status": "success",
  "error": null
}
```

Attempt order is stable and one-based. The owning stage artifact provides model/backend/request/response paths; timing may reference those paths in a versioned extension but must not duplicate their content.

## Match timing

Each match-level `timing.json` records at least start, finish, duration, process start/finish if distinct, timeout limit, and status. Candidate totals must agree with the match duration list within documented measurement boundaries.

AOS parent-vs-offspring matches use the same match-level timing schema under
`aos/head_to_head/matches/`. They are separate from the 126 normal-evaluation
durations in candidate `timing.json`; their aggregate is reconstructable from
the 18 AOS-owned match timing files and does not change normal evaluation counts.

## Tests

- UTC formatting and non-negative finite durations.
- Attempt count/order matches persisted raw request/response artifacts.
- Skipped/no-mutation stages are null with empty attempts.
- Failure timestamps close at the terminal stage and preserve earlier durations.
- Exactly 126 match durations on successful evaluation.
- Candidate total is not less than any contained stage duration.



## Phase 2C implementation note

timing.json now includes independent reflector_llm, rewriter_llm, and generation_llm
records for the mutation path. Each record has UTC start/finish timestamps, a monotonic
duration, and one-based attempt records. The generation record is closed and retained
when Java extraction or validation fails after Reflection and Rewrite have completed.

## Phase 4 implementation note

Candidate timing now includes post-Integration evaluation start/finish/duration, one duration for every attempted match, total match duration, Strategy Alignment request-attempt timing, and objective-calculation timing. Successful evaluation has exactly 126 match durations; partial runtime failure retains one duration per attempted match. Candidate-total plus selection/crossover timing remain tracked broader artifact work.

## Canonical runtime timing additions

Run-level timing.jsonl contains event=generation and event=llm_request records. Generation records include generation boundaries, mutation/crossover counts and aggregates, aggregate request/validation/compilation/evaluation durations, and the generation duration. Request records include run_id, generation, candidate_id, operation_type, operation_stage, server_or_endpoint, model_id, request_started_at, request_finished_at, duration_seconds, status, failure_category, token counts when supplied, and request_correlation_id.

Candidate timing.json contains operation-specific mutation and crossover generation-only spans, the shared child_generation span, separate validation/compilation/integration/evaluation spans, and child_total. Durations use a monotonic clock; UTC fields are display timestamps.

## Compact snapshot retention (2026-08-04)

Candidate `timing` is retained unchanged in `eagle-candidate-v2` generation and
final-population snapshots. Match stdout/stderr, commands, raw result payloads,
and telemetry are excluded from those snapshots and remain in their owning
match directories. Artifact compaction must never remove fitness objectives or
timing records needed by resume and analysis.

## Strategy Reflection role timing

Strategy Reflection attempt records use the canonical role names
`match_commentator`, `coach`, and `generator`. The Generator timing
is the existing Java-generation timing; Commentator and Coach timing
is stored in their role request/response envelopes with UTC start/finish fields
and monotonic duration. Each Commentator/Coach attempt also writes exactly one
run-level `llm_request` event with the same role and timing. Exact role prompts
and responses remain candidate-owned and are not duplicated in `llm_logs/`.
