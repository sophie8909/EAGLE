# EAGLE evolutionary flow

This document describes the active implementation. The seven opponent cases are
the evolutionary fitness dimensions; the weighted aggregate is reporting-only.

## Population lifecycle

1. Create one candidate per configured seed policy file, with a blank policy
   gene and the configured initial Java seed as its generation-zero phenotype.
   Do not replicate one seed to fill `population_size`.
2. Validate, compile, integrate, and evaluate every seed candidate without an
   LLM call. Later offspring use the normal two-gene Generator boundary.
3. Store one score for each fixed opponent case:
   `lightrush`, `heavyrush`, `workerrush`, `allinbot`, `mayari`, `coac`, and `tma`.
4. Select parents with seeded lexicase selection. A random case order is drawn
   from the EA `random.Random` instance, and candidates are filtered to the
   best score for each case until one remains.
5. Apply crossover/copy and let the configured reflection-operator controller
   choose Strategy Reflection or Generate-Code Reflection.
6. Decode each child with its configured compile-guided attempt bound, using
   structured validation/javac evidence only after a complete source fails;
   promote the first validation+compilation success, then evaluate that single
   promoted phenotype through the complete pipeline. Integration/runtime
   failure never re-enters the decoder. `static` performs no credit update;
   `aos_opponent` reuses the seven normal opponent summaries;
   `aos_head2head` runs the configured direct parent-A matrix. Both adaptive
   modes feed one shared generation-level EMA updater.
7. From generation 1 onward, fill the fixed population from offspring with seeded lexicase selection,
   using parent fallback only when offspring are insufficient.
8. Persist the surviving population and generation metrics.

The implementation is in `eagle/search.py`, `eagle/selection.py`, and
`eagle/evaluation.py`.

## Objective contract

`Candidate.objective_vector()` in `eagle/candidate.py` contains exactly the seven
opponent cases. All are maximized. Missing or failed cases use `-1000.0` from
`eagle/opponent_cases.py`.

`code_quality` is retained in `Candidate.code_quality_result` as a diagnostic
and failure/implementation signal. It is not an evolutionary objective and is
not consulted by lexicase, survivor selection, or the opponent archive.

The weighted Game Performance aggregate is calculated with the fixed weights
in `eagle/opponent_cases.py` (weight sum `11.0`). It is used for reporting and
the convenient final representative only; it does not replace the seven cases.

## Evaluation matrix

Each candidate runs all seven opponents over three maps, three rounds, and both
player positions: `7 × 3 × 3 × 2 = 126` matches. There is no previous-generation
EAGLE opponent or dynamic opponent weight.

The generation-level `expected_match_count` and `completed_match_count` are sums
over every candidate in that generation, including zero completed matches for a
candidate blocked before runtime.

Only `aos_head2head` runs the separate `3 × 3 × 2 = 18` parent-vs-offspring
matrix for each runnable mutated child. It reuses the configured maps, round
indices, sides, and compiled classes. These matches never enter fitness, the
opponent archive, lexicase, weighted Game Performance, or final testing.
`aos_opponent` instead compares the existing seven normal opponent records;
`static` performs neither form of credit assignment.

## Archive and analysis

`runs/<run>/archives/opponents.json` keeps one best valid representative per
opponent case. Each generation JSON stores objective statistics for all
seven cases and `opponent_scores.by_opponent` stores reporting summaries. The
offline analysis writes `opponent_game_performance.csv` and one
`game_performance_by_generation_<opponent>.png` per opponent. It also writes
per-agent, per-opponent win-rate rows/plots and `match_game_performance.csv` for the
small, semi-transparent single-match violin distributions on aggregate
Game Performance plots. It also writes `aos_operator_statistics.csv` and an
AOS probability plot.

See [`../opponent-wise-lexicase.md`](../opponent-wise-lexicase.md) for
the complete data and artifact contract.
