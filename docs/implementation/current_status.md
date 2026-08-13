# Current implementation status

Snapshot: 2026-08-12. This file describes executable repository behavior.

## Active evolutionary contract

- The search roster is exactly seven fixed opponents: `lightrush`, `heavyrush`,
  `workerrush`, `allinbot`, `mayari`, `coac`, and `tma`. `PassiveAI`, `RandomAI`,
  and `RandomBiasedAI` remain available as definitions but are excluded from EA.
- Every candidate runs 126 matches: three maps × three rounds × both sides
  for each opponent.
- Candidate fitness is a seven-field opponent score mapping. Failed or
  incomplete candidates receive `-1000.0` for every case.
- Parent selection is seeded lexicase. Survivor selection fills the fixed-size
  population with seeded lexicase-selected offspring, using parent fallback only
  when offspring are insufficient; aggregate Game Performance is reporting-only.
- The weighted aggregate Game Performance uses weights `1` for the three rush
  cases and `2` for AllInBot/Mayari/COAC/TMA, with denominator `11.0`, for
  reporting only.
- `code_quality` is a diagnostic and failure-routing signal, not an objective.
- Previous-generation EAGLE self-play and dynamic opponent weights are absent
  from the active evaluation path.

## Active ownership

| Responsibility | Source |
| --- | --- |
| Fixed cases and reporting weights | `eagle/opponent_cases.py` |
| Candidate state and objective vector | `eagle/candidate.py` |
| Evaluation orchestration | `eagle/evaluation.py` |
| Match matrix | `evaluation/match_matrix.py` |
| Match aggregation | `evaluation/game_metrics.py` |
| Objective construction | `evaluation/objectives.py` |
| Parent and survivor selection | `eagle/selection.py` |
| Evolution loop | `eagle/search.py`, `eagle/resume.py` |
| Per-opponent archive | `eagle/opponent_archive.py` |
| Run/generation artifacts | `eagle/run_artifacts.py`, `eagle/artifacts.py` |
| Offline analysis | `eagle/analysis/report.py` |

## Persisted per-generation evidence

Each `generations/generation_*.json` candidate stores its seven
`fitness_objectives` and `game_eval_result.opponent_scores`. Each line in
`generation_metrics.jsonl` stores an objective-statistics object for every
opponent case and `opponent_scores.by_opponent` with generation-level means.
The analysis command turns these records into
`opponent_game_performance.csv` and per-opponent generation plots.

## Reflection boundary

Reflection receives the structured candidate context from
`eagle/reflection_context.py`. Gameplay evidence includes the aggregate
reporting metric and opponent-specific summaries; code evidence remains in
the separate diagnostics structure. Strategy Reflection and Code Reflection
share transport/parsing support but use separate prompt builders and role
pipelines.

## Verification

The required checks are:

```bash
python3 -m compileall eagle
python3 -m unittest discover -s tests
git diff --check
```

The test suite uses mocked generation/matches and does not constitute a full
MicroRTS evolutionary experiment.
