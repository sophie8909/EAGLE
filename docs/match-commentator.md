# EAGLE Match Commentator (`match_commentator`, 賽評)

The Match Commentator is an auxiliary LLM role that analyzes one completed
MicroRTS match. It is independent from Strategy Reflection: it never rewrites a
strategy prompt, edits Java, calculates fitness, or affects candidate validity,
NSGA-II, or AOS.

## Responsibility flow

```text
all configured MicroRTS matches
→ temporary complete tick logs
→ strict loss/draw/win outcome selection
→ at most three selected logs
→ contiguous commentator chunks
→ final selected-match commentary
→ Manager with aggregate results and selection metadata
→ Strategy Reflection context
```

The Java observation hook is `third_party/microrts/src/rts/Game.java`, where
`writeRoundStateSnapshot` is called before the loop and after each cycle.
Python conversion and persistence are owned by `evaluation/match_trace.py`;
commentary and response validation are owned by the sports-role pipeline in
`eagle/strategy_reflection.py`. The general-purpose
`eagle/match_commentator.py` API is a standalone trace-commentary utility and is
not called once per EA match.

## Configuration and shared client

The role uses the existing `build_reflection_backend` client, endpoint, model,
and backend. Only role-specific settings are added:

```yaml
llm:
  roles:
    match_commentator:
      enabled: true
      temperature: 0.2
      chunk_ticks: 200
```

Retries use the existing bounded `mutation_max_attempts` setting. No second
model server or endpoint is introduced.

## Trace artifacts

Each match directory owns:

```text
match_metadata.json
match_trace.jsonl.gz
match_trace_integrity.json
match_result.json
commentary/
  chunk_000.json
  ...
  final_request.json
  final_response.json
  match_commentary.json
  commentary_status.json
```

`match_trace.jsonl.gz` is one compact JSON object per tick. Static metadata is
not repeated in rows. Metadata includes match/candidate identity, candidate
side, opponent, map, round/generation/seed, evaluation configuration, map
dimensions when observed, terrain (`null` when unavailable), start timestamp,
and schema version.

Rows include tick/time, terminal/winner, both player aggregate resources and
unit counts/types, and stable-sorted visible units. Unit ID, maximum HP, carried
resources, current action, action target, and remaining action time are optional
and remain `null` when the snapshot source does not expose them.

`match_trace_integrity.json` records first/last tick, recorded/expected counts,
missing ranges, duplicates, out-of-order observations, write failures, and a
boolean `complete`. Incomplete traces are visible and are not claimed
complete.

## Chunking and coverage

The commentator reads the compressed trace lazily. It validates that ticks are
contiguous, then makes contiguous ranges of `chunk_ticks`. A short trace uses
one chunk; a long trace analyzes every chunk and performs a final synthesis
request over ordered chunk analyses and coverage metadata. It never performs
blind character slicing and never skips quiet ticks.

Every chunk records `first_tick`, `last_tick`, `tick_count`, prompt/response
sizes, attempt count, and coverage status. Final validation checks match ID,
candidate side, trace bounds, tick references, turning-point evidence,
recommendation evidence, and `all_ticks_processed`.

## Commentary schema

Chunk responses contain `tick_range`, candidate/opponent state, events,
turning points, strengths, weaknesses, missed opportunities, and end state.
Final responses contain match identity/result, summary, timeline, turning
points, strengths/weaknesses, opponent behavior, decision errors, missed
opportunities, decisive causes, preserve behaviors, recommendations with tick
evidence, and complete coverage.

Invalid or generic evidence-free responses are retried a bounded number of
times. Persistent failure writes an unavailable commentary and status; it does
not change `game_performance`, `code_quality`, match winner, or selection.

## Strategy Reflection selection

Selection is categorical, not weighted:

```text
losses exist → sample up to 3 losses
otherwise draws exist → sample up to 3 draws
otherwise → sample up to 3 wins
```

The lower-priority classes have zero probability whenever a higher-priority
class exists. Missing slots are never backfilled from a lower-priority outcome
class. Within the selected outcome class, higher `opponent_weight` tiers are
preferred categorically before lower-weight tiers. Selection uses a local RNG
seed derived from existing EA/run identity and persists its provenance in
`reflection/match_selection.json`; opponent weights are not sampling
probabilities. The selected commentary is deliberately
biased toward the worst available outcome; the Match Commentator is instructed
not to generalize one selected match to the full candidate strategy.

## Strategy Reflection handoff

The Manager receives complete aggregate opponent/map/side and win/draw/loss
results, plus only the selected match analyses and selection metadata. It does
not receive raw traces. Fitness continues to use all configured matches; the
selection affects reflection context only.

## Storage and limitations

Compact match mode removes raw round-state files only after telemetry, trace,
and result artifacts are written. Existing replay artifacts remain subject to
the existing full/compact policy. The current Python converter writes the gzip
stream after the process exits; the Java source is still the per-cycle source of
truth. Terrain is not present in round-state text, and old compiled runtimes
may not emit the newer optional unit/action fields. Integrity metadata exposes
these limits instead of manufacturing values.
