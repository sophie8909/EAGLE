# EAGLE evolutionary flow

This document describes the active implementation. The ten opponent cases are
the evolutionary fitness dimensions; the weighted aggregate is reporting-only.

## Population lifecycle

1. Create seed candidates.
2. Generate, validate, compile, integrate, and evaluate every candidate.
3. Store one score for each fixed opponent case:
   `passive`, `random`, `randombias`, `lightrush`, `heavyrush`, `workerrush`,
   `allinbot`, `mayari`, `coac`, and `tma`.
4. Select parents with seeded lexicase selection. A random case order is drawn
   from the EA `random.Random` instance, and candidates are filtered to the
   best score for each case until one remains.
5. Apply crossover/copy and at most one mutation to each child.
6. Evaluate every child through the same complete pipeline.
7. Keep the aggregate-reporting elite and fill the fixed population from
   offspring with seeded lexicase selection.
8. Persist the surviving population and generation metrics.

The implementation is in `eagle/search.py`, `eagle/selection.py`, and
`eagle/evaluation.py`.

## Objective contract

`Candidate.objective_vector()` in `eagle/candidate.py` contains exactly the ten
opponent cases. All are maximized. Missing or failed cases use `-1000.0` from
`eagle/opponent_cases.py`.

`code_quality` is retained in `Candidate.code_quality_result` as a diagnostic
and failure/implementation signal. It is not an evolutionary objective and is
not consulted by lexicase, survivor selection, or the opponent archive.

The weighted Game Performance aggregate is calculated with the fixed weights
in `eagle/opponent_cases.py` (weight sum `12.5`). It is used for reporting and
the convenient final representative only; it does not replace the ten cases.

## Evaluation matrix

Each candidate runs all ten opponents over three maps, three rounds, and both
player positions: `10 × 3 × 3 × 2 = 180` matches. There is no previous-generation
EAGLE opponent or dynamic opponent weight.

## Archive and analysis

`runs/<run>/opponent_archive.json` keeps one best valid representative per
opponent case. `generation_metrics.jsonl` stores objective statistics for all
ten cases and `opponent_scores.by_opponent` stores reporting summaries. The
offline analysis writes `opponent_game_performance.csv` and one
`game_performance_by_generation_<opponent>.png` per opponent.

See [`../../opponent-wise-lexicase.md`](../../opponent-wise-lexicase.md) for
the complete data and artifact contract.
