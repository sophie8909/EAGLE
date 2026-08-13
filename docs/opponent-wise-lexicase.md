# Opponent-wise fitness and lexicase selection

This is the focused current contract for the EAGLE evolutionary loop.

## Fixed evaluation cases

`eagle/opponent_cases.py` defines the canonical order:

```text
lightrush heavyrush workerrush allinbot mayari coac tma
```

For every candidate, `eagle/evaluation.py` executes all seven cases on three
maps, for three rounds, with both p0 and p1 positions. The fixed matrix is
therefore 126 matches. `allibot` remains the historical GUI opponent ID;
the evolutionary case is `allinbot` in `eagle/opponents.py`.

`PassiveAI`, `RandomAI`, and `RandomBiasedAI` remain defined for compatibility
and visual inspection, but are not in the EA search roster.

## Fitness and reporting

`evaluation/objectives.py` returns a mapping with exactly the seven case IDs.
This mapping is stored in `Candidate.fitness_objectives` and is the only
selection fitness. A failed or incomplete candidate gets `-1000.0` for all
seven cases.

`eagle/opponent_cases.py:aggregate_game_performance` computes a reporting-only
weighted mean. The weights are `1` for `lightrush`, `heavyrush`, and
`workerrush`, and `2` for `allinbot`, `mayari`, `coac`, and `tma`; the
denominator is `11.0`. Code quality is stored
under `Candidate.code_quality_result` and is not an objective.

## Selection

`eagle/selection.py:lexicase_select` uses the EA-seeded `random.Random`
instance. It shuffles the seven case order, filters the current survivors to
the best score for each case, and stops when one candidate remains. There is
no Pareto rank, crowding distance, dominance comparator, or code-quality
tie-break in the active selection path.

`select_next_generation` fills the fixed population with lexicase-selected
offspring, then uses lexicase-selected parents only if offspring are insufficient.
Aggregate Game Performance remains reporting-only and does not select survivors.

## Artifacts and analysis

The following records are written after each generation:

- `generations/generation_<n>.json`: surviving candidates and their seven
  `fitness_objectives`;
- `generation_metrics.jsonl`: seven objective statistics plus
  `opponent_scores.by_candidate` and `opponent_scores.by_opponent`;
- `candidates/<id>/evaluation/objectives.json`: seven-case objective mapping;
- `candidates/<id>/evaluation/game_performance.json`: aggregate reporting
  metric and detailed opponent/match summaries;
- `opponent_archive.json`: one best valid representative per opponent case.

`python -m eagle analyze --run-dir <run>` writes
`opponent_game_performance.csv` and one
`plots/game_performance_by_generation_<opponent>.png` for every opponent,
along with the aggregate and code-quality diagnostic plots.

## Removed behavior

The active path does not evaluate a previous-generation EAGLE candidate, does
not add a generation-dependent EAGLE weight, and does not use `code_quality` as
an evolutionary objective. Legacy artifact readers are not allowed to invent
missing opponent scores; old candidates are represented as incomplete data.
