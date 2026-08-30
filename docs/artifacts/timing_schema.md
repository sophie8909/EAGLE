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

Default-mode generation-zero seed loading is not an LLM request and has null
generation timing with an empty attempt list. Inherited-mode generation zero
uses the normal bounded `generation_llm` attempt records independently for all
`population_size` candidates. Strategy Alignment has null timing and no
attempts when an empty policy makes the diagnostic not applicable.

For bounded Java decoding, `generation_llm.attempts` is the ordered outer
`generation_attempt` list and includes `generation_attempt_id`, request hash,
`request_kind`, optional `repair_of_attempt`/previous-source hash,
validation/compilation status, and selected/final flags. Candidate-level
validation and compilation totals include all attempted work, while the flat
stage artifacts project the selected attempt or final failure. `child_total`
includes `generation_llm` as well as mutation/crossover generation, validation,
compilation, integration, and evaluation.

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

Code Prompt Rewrite attempts include structured reusable-rule validation inside
the owning attempt duration. An invalid category, unknown removal ID, concrete
policy/Java instruction, or ineffective delta is an ordinary failed rewrite
attempt and retains the same raw-response and retry timing contract.

Java generation has two distinct axes. `generation_attempt` (and stable
`generation_attempt_id`) identifies the outer decoder step;
`transport_attempt` identifies an HTTP transport try inside that sample. The
backend logger remains the sole writer of each real `llm_request` event. Both
axes and the shared request correlation ID appear in the durable LLM log and
run timing event; the outer decoder does not emit a duplicate request event.
The current generation transport remains fail-fast on HTTP/connection errors,
so `transport_attempt` is normally `1`; decoder steps are not a substitute for
an infrastructure retry. `initial_decode_retry` repeats the base request only
after extraction yielded no complete source. `compile_repair` consumes the
immediately previous complete source's structured validation/javac feedback.

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

Run-level timing.jsonl contains event=generation and event=llm_request records. Generation records include generation boundaries, mutation/crossover counts and aggregates, aggregate request/validation/compilation/evaluation durations, and the generation duration. Request records include run_id, generation, candidate_id, operation_type, operation_stage, server_or_endpoint, model_id, request_started_at, request_finished_at, duration_seconds, status, failure_category, token counts when supplied, request_correlation_id, generation_attempt, generation_attempt_id, transport_attempt, and generation_request_kind.

Candidate timing.json contains operation-specific mutation and crossover generation-only spans, the shared child_generation span, separate validation/compilation/integration/evaluation spans, and child_total. Durations use a monotonic clock; UTC fields are display timestamps.

Balance Reflection records one `reflector_llm` attempt stream and two ordered
rewrite attempts in `rewriter_llm` (strategy first, code-generation second).
Each request emits one run-level `llm_request` event and remains candidate-owned
under `mutation/balance_reflection/`.

## Compact snapshot retention (2026-08-04)

Candidate `timing` is retained unchanged in `eagle-candidate-v5` generation and
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
