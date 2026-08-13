# Current EAGLE design

Snapshot: 2026-08-12. This is a repository-reality summary; executable code is
the final authority.

## Scope

EAGLE evolves prompts that generate complete modular Java MicroRTS agents. The
active user-facing workflow is `run_env.sh`, `run.sh`, `analysis.sh`, and the
independent local-network `watchdog.sh`. The EA uses one runtime-configured
llama.cpp model for all LLM roles.

## Evolutionary evaluation

The canonical experiment is `configs/experiments/microrts.yaml`. Every
candidate is evaluated against exactly these seven cases:

```text
lightrush heavyrush workerrush allinbot mayari coac tma
```

Each case runs on three maps, three rounds, and both p0/p1 positions, for 126
matches per candidate. No previous-generation EAGLE opponent is appended.

`Candidate.fitness_objectives` contains the seven opponent scores. These are the
only evolutionary dimensions and are consumed by seeded lexicase selection.
Code quality is retained under `code_quality_result` as diagnostics and is not
an objective.

The reporting-only aggregate uses weights `1` for Light/Heavy/Worker Rush and
`2` for AllInBot/Mayari/COAC/TMA. Its denominator is `11.0`.

## Evolution flow

```text
seed candidates
  -> generate/validate/compile/integrate
  -> evaluate 126 matches
  -> persist seven opponent scores and reporting aggregate
  -> seeded lexicase parent selection
  -> crossover/copy and optional mutation
  -> evaluate children
  -> lexicase offspring survivors with parent fallback
  -> persist generation snapshot and metrics
```

The live implementation is split by ownership:

| Responsibility | Source |
| --- | --- |
| Cases and weights | `eagle/opponent_cases.py` |
| Candidate state | `eagle/candidate.py` |
| Evaluation boundary | `eagle/evaluation.py` |
| Matrix and aggregation | `evaluation/match_matrix.py`, `evaluation/game_metrics.py` |
| Objective construction | `evaluation/objectives.py` |
| Selection | `eagle/selection.py` |
| Search/resume | `eagle/search.py`, `eagle/resume.py` |
| Artifacts | `eagle/artifacts.py`, `eagle/run_artifacts.py` |
| Analysis | `eagle/analysis/report.py` |

## Run artifacts and analysis

Each generation snapshot persists seven `fitness_objectives` per surviving
candidate. `generation_metrics.jsonl` stores per-case best/mean/median/worst
statistics and `opponent_scores.by_opponent` generation means. The analysis
command writes `opponent_game_performance.csv`, aggregate/diagnostic plots,
and one `game_performance_by_generation_<opponent>.png` per case.

## Reflection and diagnostics

Strategy Reflection and Code Reflection use separate prompt builders and
structured contexts. Gameplay context contains opponent-specific summaries;
code context contains compilation, validation, function, alignment, and
runtime diagnostics. Match artifacts remain owned by evaluation and are not
reinterpreted by selection.

For the detailed current contract, see
[`opponent-wise-lexicase.md`](opponent-wise-lexicase.md).
