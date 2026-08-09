# EAGLE reflection and Match Commentator current state

Audit date: 2026-08-06. This document describes the executable repository path.
The Match Commentator role is analysis context only: it does not calculate
`game_performance`, `code_quality`, candidate validity, or NSGA-II objectives.

## Current flow

```text
MicroRTS Game.start
  → per-cycle round-state snapshots
  → evaluation/match_trace.py
  → match_trace.jsonl.gz + integrity metadata
  → eagle/match_commentator.py
  → commentary/match_commentary.json
  → eagle/commentary_aggregation.py
  → Strategy Reflection prompt
```

The existing game-performance scorer still owns match scoring. It continues to
consume `MatchTelemetry` and `GamePerformanceBreakdown` in
`evaluation/game_performance.py`; commentary is attached after `game_metrics` is
computed in `eagle/evaluation.py`.

## Reflection entrypoints

| Source and symbol | Caller | Trigger | Operator | Reflects | Candidate state |
| --- | --- | --- | --- | --- | --- |
| `eagle/search.py:create_offspring` | `run_search` / resume path | `rng.random() < config.mutation_rate` | selected mutation from `mutations` | strategy or code | successful or failed parent can be selected |
| `eagle/search.py:choose_mutation` | `create_offspring` | failure, warnings, low capability/alignment, or mutation policy | strategy/code selector | neither; chooses path | failure evidence routes preferentially to code mutation |
| `eagle/search.py:mutation_context_from_candidate` | `create_offspring` | immediately before mutation | shared context adapter | strategy or code | feedback parent plus equivalent references |
| `eagle/rewrite.py:PromptRewriteMutation.mutate` | `create_offspring` | one mutation selected | strategy or code mutation | strategy or code | Reflection then prompt-only Rewrite |
| `eagle/mutation.py:ReflectionStage.run` | `PromptRewriteMutation.mutate` | every selected mutation | `strategy_reflection` / `code_reflection` | one component at a time | bounded retries; raw response persisted |
| `eagle/match_commentator.py:commentate_match` | `eagle/evaluation.py:evaluate_candidate` | every match with a match directory when enabled; disabled/failing matches get an explicit status artifact | `match_commentator` | one completed match | never a mutation parent and never a fitness input |

The shared reflection transport is `eagle/mutation.py:ReflectionBackend`,
`build_reflection_backend`, and `OpenAICompatibleReflectionBackend`. The
commentator reuses that client/model/endpoint and supplies only its own role
prompt and role settings from `eagle/config.py:ExperimentConfig`.

## Trace production and data flow

`third_party/microrts/src/rts/Game.java:171-214` calls
`writeRoundStateSnapshot` at tick zero and after each `gs.cycle()`; the snapshot
contains time, terminal marker, resources, map dimensions, and visible units.
The same source now includes optional unit ID, maximum HP, carried resources,
current action, target, and ETA in `renderFeatureLine`
(`Game.java:452-481`). A compiled MicroRTS runtime must include this source
change for those optional fields to appear.

`evaluation/runtime_evaluation.py:45-181` adds trace paths to `MatchResult`.
`_finish_match` calls `evaluation.match_trace:write_match_trace` before compact
cleanup (`runtime_evaluation.py:407-560`). The converter reads round-state
files in order and writes one compact JSON object per line to gzip;
`iter_match_trace` is lazy (`evaluation/match_trace.py`). The current Java
snapshot writer is file-based, so compressed trace output is finalized after the
process exits rather than being written directly by the JVM.

Each trace row contains `tick`, `game_time`, `terminal`, `winner`, both
player aggregate states, and stable-sorted `units`. Static metadata is written
once to `match_metadata.json`; dimensions are recovered from `Map size`, while
terrain is `null` because round-state text does not expose the terrain grid.
Missing optional fields remain `null`. `match_result.json` is the final
compact `MatchResult` envelope; `result.json` remains the existing
compatibility name.

Integrity is calculated from observed ticks and the expected final tick:
`first_tick`, `last_tick`, `recorded_tick_count`,
`expected_tick_count`, `missing_tick_ranges`, `duplicate_ticks`,
`out_of_order_ticks`, `trace_write_failure`, and `complete`
(`evaluation/match_trace.py:43-113`). Incomplete traces are not passed to the
commentator as complete evidence; an explicit `commentary_status.json`
records the failure.

## Commentator execution

`eagle/match_commentator.py:commentate_match` loads metadata/integrity and
lazily reads the gzip rows. It partitions the complete ordered tick sequence by
`llm.roles.match_commentator.chunk_ticks`; it never character-slices a prompt
or splits a serialized row. Every chunk request includes its exact range and
rows. The final request includes metadata, result, integrity, ordered chunk
analyses, and coverage—not the entire raw trace again.

The role system prompt is `MATCH_COMMENTATOR_SYSTEM_PROMPT`
(`eagle/match_commentator.py:15-34`). It prohibits Java/strategy rewriting
and fitness calculation and requires tick evidence, observation/inference
separation, and structured JSON. Chunk and final schemas are emitted by
`_chunk_schema` and `_final_schema`.

Every request records `first_tick`, `last_tick`, `tick_count`,
prompt/response sizes, attempt count, and coverage status. Chunk files contain
the request and validated response. Final request/response and
`match_commentary.json` are stored beside them. Validation checks identity,
candidate side, range bounds, complete coverage, tick references,
turning-point evidence, and recommendation evidence
(`validate_chunk`, `validate_final`). Retries are bounded by
`ExperimentConfig.mutation_max_attempts`.

Commentary failure produces `commentary_status.json` and an unavailable
`match_commentary.json`; it does not alter any scorer value or candidate
status. The aggregation carries `failed_commentary_count` and unavailable
match IDs.

## Candidate aggregation and Strategy Reflection

`eagle/commentary_aggregation.py:aggregate_commentaries` groups structured
comments by opponent, map, candidate side, and result. It deterministically
counts recurring strengths, weaknesses, decisive causes, and recommendations;
selects loss-first representative matches; and preserves match IDs and tick
references. It does not call another LLM and does not include raw traces or full
chunk documents.

`eagle/evaluation.py:evaluate_candidate` adds the aggregation to
`game_payload["commentary_aggregation"]` and to `reflection_evidence` only
after `compute_game_metrics` and objective construction. The candidate writer
persists `evaluation/commentary_aggregation.json`.

`eagle/reflection_context.py:build_reflection_context` exposes the compact
aggregation, representative match entries, priority changes, and preserve list.
`eagle/reflection_prompts.py:build_strategy_reflection_prompt_bundle` renders
these sections in this order:

1. mutation task;
2. current strategy prompt;
3. aggregate objectives (`game_performance` and scalar `code_quality`);
4. equivalent parent/generation-best comparison;
5. prioritized mutation targets;
6. per-opponent commentary summaries and representative evidence;
7. behaviors to preserve;
8. output schema.

Raw traces, all chunks, full Java, compiler logs, and every match document are
not inserted into this Strategy Reflection prompt. Section sizes and omitted or
truncated low-priority fields remain in reflection prompt metadata. The current
strategy prompt and output schema are not truncated.

The new accepted Strategy Reflection shape is parsed in
`eagle/mutation.py:parse_reflection_response`:

```json
{
  "diagnosis": {"primary_failure": "", "secondary_failures": [], "supporting_matches": [{"match_id": "", "ticks": []}], "behaviors_to_preserve": []},
  "mutation_plan": {"remove_or_reduce": [], "add_or_strengthen": [], "conditional_behaviors": []},
  "revised_strategy_prompt": ""
}
```

`eagle/rewrite.py` persists the reflection and rewrites only
`strategy_prompt` for a strategy mutation or only `generation_prompt` for a
code mutation. The final Java generation stage remains separate.

Equivalent parent comparison is implemented in
`eagle/reflection_context.py:_parent_comparison`. It requires equal persisted
evaluation configuration and the same `(opponent_id, map, candidate_player)`
key; unmatched games are not compared. The comparison records parent/child
candidate and match IDs plus score deltas. `eagle/search.py:create_offspring`
supplies direct parents and the evaluated generation-best candidate when one is
available.

## Analysis commands

`analyze.sh` accepts both the legacy positional run directory and the explicit
form that the CLI advertises:

```bash
./analyze.sh --run-dir <run_dir>
./analyze.sh --candidate <candidate_id> --match-commentaries
./analyze.sh --candidate <candidate_id> --match <match_id> --commentary
```

The first commentary view is a text summary from
`evaluation/commentary_aggregation.json`; the second reads one
`commentary/match_commentary.json` and prints summary, timeline, evidence,
and trace path. No GUI is involved (`eagle/cli/analyze.py`).

## Current limitations

- Complete trace coverage depends on the Java runtime emitting one round-state
  snapshot per cycle. Integrity exposes sparse legacy or failed runs instead
  of filling quiet ticks.
- Terrain is not available in snapshot text and is stored as `null`.
- Unit IDs/actions are optional in the persisted source format; old compiled
  MicroRTS classes may therefore produce `null` optional fields.
- The Python converter currently finalizes the gzip trace after the match rather
  than streaming directly from the JVM during execution.
- Commentator output is auxiliary context; it cannot repair a sparse trace or
  distinguish hidden intent beyond the supplied state.
- Parent comparison is unavailable for legacy candidates without the persisted
  evaluation-configuration signature.
- There is no separate error-pool sampler. Runtime/generation/compiler errors
  remain in existing candidate failure/diagnostic artifacts; commentary status
  is per match and is not an error-pool input.

## Evidence map

| Concern | Executable owner |
| --- | --- |
| Java per-cycle state snapshot | `third_party/microrts/src/rts/Game.java:171-214,452-481` |
| Match result and cleanup | `evaluation/runtime_evaluation.py:_finish_match` |
| Trace schema/integrity/lazy reader | `evaluation/match_trace.py` |
| Shared LLM request/retry contract | `eagle/mutation.py:ReflectionStage`, `build_reflection_backend` |
| Commentator prompt/validation/artifacts | `eagle/match_commentator.py` |
| Candidate aggregation | `eagle/commentary_aggregation.py` |
| Strategy context/prompt | `eagle/reflection_context.py`, `eagle/reflection_prompts.py`, `config/prompt_templates.toml` |
| Scoring ownership | `evaluation/game_performance.py`, `evaluation/game_metrics.py`, `evaluation/nsga2_objectives.py` |
| Candidate artifact writer | `eagle/artifacts.py` |
| Text analysis | `analyze.sh`, `eagle/cli/analyze.py` |
