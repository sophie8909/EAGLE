# 0929 matched self-play experiments

## Added configuration

`self_play_5x40_semantic_tiebreak.yaml` fills the missing 5×40 arm for the same semantic-tie-break protocol as the completed 0927 10×20 run (`20260928_115653_334420`). The only intended configuration contrast is the population/generation allocation at a matched regular offspring budget: 5×40 = 10×20 = 200 offspring. Initial-population, refresh, and semantic-refresh evaluations are additional work, so total candidate artifacts and total evaluations will not be equal.

The 0925 5×40 legacy-lexicase run also used self-play snapshot opponents; it is excluded from the single-objective results because its selection protocol differs. `fixed_opponent_10x20_control.yaml` restores the prior multi-opponent evaluation context at the same 10×20 profile as 0927. The 5×40 semantic config uses one numeric objective, `game_performance: maximize`; semantic probes only break ties within 1.0 fitness and are not a second objective.

## Pairing map

| Comparison | Existing arm | Added arm | What changes | Status |
| --- | --- | --- | --- | --- |
| Allocation at 200 regular offspring | 0927 semantic 10×20 | 0929 semantic 5×40 | population/generation allocation | Missing arm configured |
| Fixed-opponent vs self-play at 200 regular offspring | 0927 single-GP self-play 10×20 | `fixed_opponent_10x20_control.yaml` | search evaluation context | Matched arm configured; rerun both on one source revision for a causal contrast |
| Allocation at 100 regular offspring | 0926 semantic 10×10 and 5×20 | none | population/generation allocation | Both observed once; refresh integrity limits causal attribution |

For a confirmatory comparison, hold model, source revision, initial population, evaluation roster, snapshot slots, refresh interval, Java-preservation behavior, and final-test protocol fixed. Use multiple independent LLM initial populations. Report final fixed-roster W/L/D/E and per-opponent results. Keep `random_seed` fixed where supported, but do not treat it as controlling LLM sampling.
