# EAGLE reflection and Match Commentator current state

Audit date: 2026-08-06. This document describes the executable repository path.
The Match Commentator role is analysis context only: it does not calculate
`game_performance`, `code_quality`, candidate validity, or NSGA-II objectives.

## Current flow

```text
MicroRTS Game.start
  → per-cycle round-state snapshots
  → evaluation/match_trace.py + match_log.jsonl.gz
  → all evaluation match results and aggregate fitness
  → strict loss/draw/win selection (at most 3, reproducible)
  → delete unselected logs
  → eagle/strategy_reflection.py Match Commentator
  → delete selected logs after terminal commentary
  → Manager → Coach → Strategy Reflection child
```

The existing game-performance scorer still owns match scoring. It continues to
consume `MatchTelemetry` and `GamePerformanceBreakdown` in
`evaluation/game_performance.py`; the complete evaluation matrix is scored before
the Strategy Reflection selection. Match Commentator is not called from
`eagle/evaluation.py` for every match.

## Reflection entrypoints

| Source and symbol | Caller | Trigger | Operator | Reflects | Candidate state |
| --- | --- | --- | --- | --- | --- |
| `eagle/search.py:create_offspring` | `run_search` / resume path | `rng.random() < config.mutation_rate` | selected mutation from `mutations` | strategy or code | successful or failed parent can be selected |
| `eagle/search.py:choose_mutation` | `create_offspring` | failure, warnings, low capability/alignment, or mutation policy | strategy/code selector | neither; chooses path | failure evidence routes preferentially to code mutation |
| `eagle/search.py:mutation_context_from_candidate` | `create_offspring` | immediately before mutation | shared context adapter | strategy or code | feedback parent plus equivalent references |
| `eagle/rewrite.py:PromptRewriteMutation.mutate` | `create_offspring` | one mutation selected | strategy or code mutation | strategy or code | Reflection then prompt-only Rewrite |
| `eagle/mutation.py:ReflectionStage.run` | `PromptRewriteMutation.mutate` | every selected mutation | `strategy_reflection` / `code_reflection` | one component at a time | bounded retries; raw response persisted |
| `eagle/strategy_reflection.py:StrategyReflectionPipeline.run` | `eagle/search.py:create_offspring` | selected strategy mutation after complete parent evaluation; at most 3 matches from one strict outcome pool | `match_commentator` | selected completed matches only | never a mutation parent and never a fitness input |

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

`eagle/strategy_reflection.py:select_reflection_matches` partitions completed
match summaries into losses, draws, and wins. It chooses exactly one pool in
strict `loss > draw > win` order, samples up to three entries without
replacement using a seed derived from run seed, generation, candidate, and
reflection invocation, and writes `reflection/match_selection.json` before raw
log deletion. Lower-priority outcomes never backfill the sample.

`eagle/reflection_context.py:build_reflection_context` exposes complete
per-match compact result summaries and complete opponent results to the sports
pipeline. The Manager receives aggregate counts and summaries plus only the
selected Match Commentator analyses and selection metadata.
The active sports-role prompts are assembled by
`eagle/strategy_reflection.py:_commentator_prompt`,
`_commentator_synthesis_prompt`, `_manager_prompt`, and `_coach_prompt` in this
order:

1. aggregate evaluation and opponent results;
2. strict-priority selection metadata;
3. selected Match Commentator analyses;
4. parent comparison when available;
5. behaviors and aggregate strengths to preserve in the Manager input.

Raw traces are not inserted into the Manager or Coach prompts. Selected tick
records are inserted into Commentator requests, and the complete compact match
record is inserted alongside each selected chunk. Every role request passes
through `eagle/strategy_reflection.py:_call_role`, which applies the configured
prompt-character bound before the LLM request. Role request artifacts retain the
bounded prompt actually sent to the LLM.

The sports-role output is parsed in
`eagle/strategy_reflection.py:_parse_commentary`, `_parse_manager`, and
`_parse_coach`. It produces `MatchAnalysis`, `ManagerPlan`, and `CoachResult`;
the Coach result replaces only `strategy_prompt`. The separate generic
prompt-only reflection path in `eagle/mutation.py:ReflectionStage` still parses
the following compatibility shape when that path is invoked:

```json
{
  "diagnosis": {"primary_failure": "", "secondary_failures": [], "supporting_matches": [{"match_id": "", "ticks": []}], "behaviors_to_preserve": []},
  "mutation_plan": {"remove_or_reduce": [], "add_or_strengthen": [], "conditional_behaviors": []},
  "revised_strategy_prompt": ""
}
```

`eagle/rewrite.py` remains the active code-mutation reflection/rewrite owner.
The sports-role Strategy Reflection path persists Manager/Coach artifacts and
updates only `strategy_prompt`; the final Java generation stage remains
separate.

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

The commentary artifacts are stored under the selected child candidate's
`reflection/` and `commentary/` directories. Legacy aggregation readers remain
available for older run artifacts. No GUI is involved (`eagle/cli/analyze.py`).

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
- Match Commentator selection is not a fitness sampler: Game Performance still
  uses every configured evaluation match, while Strategy Reflection samples one
  strict-priority outcome class and at most three detailed matches.

## Evidence map

| Concern | Executable owner |
| --- | --- |
| Java per-cycle state snapshot | `third_party/microrts/src/rts/Game.java:171-214,452-481` |
| Match result and cleanup | `evaluation/runtime_evaluation.py:_finish_match` |
| Trace schema/integrity/lazy reader | `evaluation/match_trace.py` |
| Shared LLM request/retry contract | `eagle/mutation.py:ReflectionStage`, `build_reflection_backend` |
| Commentator prompt/selection/artifacts | `eagle/strategy_reflection.py`, `eagle/match_commentator.py` |
| Strategy context/prompt | `eagle/reflection_context.py`, `eagle/strategy_reflection.py`, `config/prompt_templates.toml` |
| Scoring ownership | `evaluation/game_performance.py`, `evaluation/game_metrics.py`, `evaluation/nsga2_objectives.py` |
| Candidate artifact writer | `eagle/artifacts.py` |
| Text analysis | `analyze.sh`, `eagle/cli/analyze.py` |

## Active Strategy Reflection path

The active Strategy Reflection path is the sports-team pipeline documented in
[`strategy-reflection.md`](strategy-reflection.md): Match Commentator, Manager,
Coach, then the existing Generator.

The old monolithic strategy reflector/re-writer path is no longer used for
Strategy Mutation. Code Reflection still owns implementation-level mutation and
continues to operate independently.

The evaluator remains authoritative for the fixed match roster, match count,
game-performance scoring, code-quality simplicity scoring, and NSGA-II
objectives. Strategy Reflection only consumes the resulting evidence and
changes `strategy_prompt`.

The temporary full match trace is deleted after terminal Commentator handling.
Compact results and role artifacts remain sufficient to reconstruct the
LLM-analysis chain without retaining raw tick logs.
