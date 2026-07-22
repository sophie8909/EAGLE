# `code_quality`

This is the canonical implementation guide for successful-execution `code_quality`. Failure-stage values are owned by [`failure_classification.md`](failure_classification.md). Normative source: specification sections 15 through 17.

## Direction and roles

Higher is better. `code_quality` must:

1. distinguish generation, validation, compilation, integration, and runtime failures; and
2. evaluate candidates that complete all 10 matches.

Only successful 10-match candidates use the component formula below.

## Successful components

### Compilation score

```text
compilation_score = max(-500, -50 * warning_count)
```

Invoke `javac` with explicit warning flags, count structured diagnostics rather than stderr lines, deduplicate repeated warnings, and persist every diagnostic.

### Function capability score

```text
function_score =
    economy_score
  + production_score
  + combat_score
  + targeting_score
  + state_aware_decision_score
```

Each capability is scored from `0` to `20`; total range is `[0, 100]`. Evaluate capabilities with deterministic static analysis, runtime evidence, and match telemetry. Do not require specific function names or fixed internal structure.

### Strategy alignment score

An independent LLM evaluator consumes `strategy_prompt`, generated `CandidateAgent.java`, and optional behavior summary. It returns validated structured data:

```json
{
  "score": 0,
  "reason": "..."
}
```

The numeric score must be in `[0, 10]`. Persist both fields; only `score` contributes to `code_quality`. This is not a separate NSGA-II objective.

## Successful formula

The selected formula is:

```text
code_quality =
    500
  + compilation_score
  + function_score
  + strategy_alignment_score
```

Its range is `[0, 610]`. The explicit `500` base guarantees every successful 10-match execution scores above the runtime-failure range `[-400, -201]`; no additional success clamp or hidden offset is allowed.

Persist the selected formula through `objective_formula_version`. A formula-version change is an architecture change and requires updating the normative specification, this canonical owner, artifact compatibility, tests, the Matrix, and the Chinese overview.

## Invariants

- A candidate reaching a later failure stage always scores higher than an earlier failure.
- Every successful candidate scores higher than every runtime failure.
- Function scoring measures reachable behavior, not method names or code size alone.
- Compiler warnings cannot push a successful result into an earlier failure range.
- Strategy alignment is evaluated independently and cannot become a third objective.

## Tests

- Warning parsing, deduplication, `-50` penalty, and `-500` cap.
- Each capability level and total cap.
- Arbitrary helper/method names do not reduce capability credit when behavior exists.
- Unreachable code does not receive capability credit.
- Strategy-alignment response validation, bounds, and persistence.
- Exact selected-formula and formula-version behavior across the `[0, 610]` range.
- Cross-stage ordering against every failure boundary.

## Current mismatch

Active code sums compilation status, one marked-region validity score, and deterministic text metrics. It does not implement failure-stage ranges, capability scoring, or the independent alignment evaluator. See gap `G-07`.

