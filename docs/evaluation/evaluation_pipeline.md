# Evaluation pipeline

`eagle/evaluation.py` owns the candidate evaluation boundary. It performs Java
generation, validation, compilation, integration, the complete MicroRTS
matrix, diagnostics, objective construction, and candidate artifact writing.

## Active stages

| Stage | Success output | Failure evidence |
| --- | --- | --- |
| Java generation | complete `CandidateAgent.java` | generation response and validation failure |
| Source validation | validated source | validation diagnostics |
| Compilation | isolated class directory | compiler stdout/stderr and structured errors |
| Integration | loadable MicroRTS agent | seven integration checks |
| Match execution | 180 matches across ten opponents | retained match results and runtime failure |
| Objective construction | ten opponent scores | ten `-1000.0` case scores on failure |

## Match protocol

The fixed roster is defined by `eagle/opponent_cases.py` and resolved by
`eagle/opponents.py`. Each opponent receives three configured maps, three
rounds, and both candidate player positions. The matrix is owned by
`evaluation/match_matrix.py`; execution is owned by
`evaluation/microrts_runner.py`.

The evaluator groups match results by opponent in
`evaluation/game_metrics.py`. It retains per-opponent, per-map, per-side, and
per-match summaries, then computes the weighted aggregate only for reporting.
The aggregate denominator is the fixed weight sum `12.5`.

## Objective and diagnostics

`evaluation/objectives.py` returns exactly one evolutionary score for each of
the ten cases. `code_quality`, compiler diagnostics, function coverage,
strategy alignment, and runtime failure details remain in their diagnostic
artifacts and reflection context; none is inserted into the evolutionary
objective vector.

## Artifacts

Per-candidate evaluation artifacts include:

- `evaluation/game_performance.json`: aggregate Game Performance, opponent
  score mapping, opponent summaries, map/side summaries, and match summaries;
- `evaluation/objectives.json`: ten-case objective mapping;
- `evaluation/code_quality.json`: code-quality diagnostics;
- `evaluation/matches.json`: compact individual match records.

Run-level `generation_metrics.jsonl` stores objective statistics for every
opponent case and the per-opponent reporting summaries used by analysis.
