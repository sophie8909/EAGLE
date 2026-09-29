# 0929 matched self-play experiments

## Added configuration

`self_play_5x40_semantic_tiebreak.yaml` fills the missing 5×40 arm for the same semantic-tie-break protocol as the completed 0927 10×20 run (`20260928_115653_334420`). The only intended configuration contrast is the population/generation allocation at a matched regular offspring budget: 5×40 = 10×20 = 200 offspring. Initial-population, refresh, and semantic-refresh evaluations are additional work, so total candidate artifacts and total evaluations will not be equal.

This run also pairs with the completed 0925 5×40 legacy-lexicase run to isolate the selection algorithm at a fixed 5×40 allocation. It cannot repair that historical run's phenotype-refresh hash changes; rerun only after the refresh invariant is corrected and audited.

## Pairing map

| Comparison | Existing arm | Added arm | What changes | Status |
| --- | --- | --- | --- | --- |
| Allocation at 200 regular offspring | 0927 semantic 10×20 | 0929 semantic 5×40 | population/generation allocation | Missing arm configured |
| Selection method at 5×40 | 0925 legacy lexicase 5×40 | 0929 semantic 5×40 | algorithm / semantic tie-break | Missing arm configured |
| Allocation at 100 regular offspring | 0926 semantic 10×10 and 5×20 | none | population/generation allocation | Both observed once; refresh integrity limits causal attribution |

For a confirmatory comparison, hold model, source revision, initial population, evaluation roster, snapshot slots, refresh interval, Java-preservation behavior, and final-test protocol fixed. Use multiple independent LLM initial populations. Report final fixed-roster W/L/D/E and per-opponent results. Keep `random_seed` fixed where supported, but do not treat it as controlling LLM sampling.
