# Game Performance

## Per-match score

The existing match formula remains owned by `evaluation/game_performance.py`:

```text
Win  = +100
Draw =    0
Loss = -100
```

Material, final-resource, and survival shaping are bounded and retained in
the per-match summaries. `evaluation/game_metrics.py` groups these scores by
opponent and retains map, player-side, and individual-match evidence.

## Candidate reporting aggregate

Each active opponent has 18 records (three maps × three rounds × p0/p1). The
fixed weights are:

```text
passive/random/randombias = 0.5 each
lightrush/heavyrush/workerrush = 1 each
allinbot/mayari/coac/tma = 2 each
```

The denominator is `12.5`. The weighted mean is stored as
`game_eval_result.game_performance` and is reporting-only. It is not an
evolutionary objective and does not replace the ten opponent scores stored in
`Candidate.fitness_objectives`.

## Failure behavior

If generation, validation, compilation, integration, runtime, or matrix
completion fails, each of the ten opponent fitness cases is `-1000.0`. Partial
match results and failure diagnostics remain in the candidate artifacts.

## Analysis

Each `generations/generation_*.json` stores per-case objective statistics and
`opponent_scores.by_opponent` generation summaries. The analysis command
exports `opponent_game_performance.csv` and one per-opponent generation plot.
The canonical per-match ranges are loss `-110` to `-90`, draw `-10` to `+10`,
and win `+90` to `+110`. Aggregate plots use a dashed `0` neutral baseline
and overlay retained single-match scores as narrow, semi-transparent violin
distributions with a median marker. A generation with only one value or no
variance uses a short horizontal degenerate-distribution marker. Individual agent win rates are exported by opponent
in `agent_win_rate.csv` and
`win_rate_by_generation_<opponent>.png`.
