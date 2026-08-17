# Current implementation status

Snapshot: 2026-08-17. This file describes executable repository behavior.

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
- AOS selects between `strategy_reflection` and `generate_code_reflection`.
  It starts at `0.20/0.80`, has a `0.10` exploration floor, and updates once
  per generation with EMA alpha `0.20`. After normal evaluation, each runnable
  mutated child plays parent A over the configured 18 map/round/side matches;
  `(wins + 0.5 × draws) / valid matches` is the AOS reward. Failed offspring
  skip direct matches and receive `0.0`. Lexicase remains the parent selector,
  and its seven opponent scores no longer determine AOS reward.
- The weighted aggregate Game Performance uses weights `1` for the three rush
  cases and `2` for AllInBot/Mayari/COAC/TMA, with denominator `11.0`, for
  reporting only.
- `code_quality` is a diagnostic and mutation-evidence signal, not an objective
  and not an AOS operator schedule.
- Previous-generation EAGLE self-play and dynamic opponent weights are absent
  from the active evaluation path.

## Active ownership

| Responsibility | Source |
| --- | --- |
| Fixed cases and reporting weights | `eagle/opponent_cases.py` |
| Candidate state and objective vector | `eagle/candidate.py` |
| Evaluation orchestration | `eagle/evaluation.py` |
| Match matrix | `evaluation/match_matrix.py` |
| AOS parent-vs-offspring evaluation | `evaluation/parent_offspring.py` |
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
`agent_win_rate.csv`, `match_game_performance.csv`,
`opponent_game_performance.csv`, individual-agent per-opponent win-rate/Game
Performance plots, per-opponent generation plots with single-match score
overlays, and AOS operator statistics/probability plots.

## Reflection boundary

Reflection receives the structured candidate context from
`eagle/reflection_context.py`. Gameplay evidence includes the aggregate
reporting metric and opponent-specific summaries; code evidence remains in
the separate diagnostics structure. Strategy Reflection and Code Reflection
share transport/parsing support but use separate prompt builders and role
pipelines. Strategy Reflection samples up to 10 matches with opponent/map-aware
coverage, calls one Commentator per selected log, and gives the Coach a
deterministic all-match global summary. Coverage and fully-beaten diagnostics are
stored under candidate reflection artifacts; this does not add a fitness objective
or change AOS.

## Verification

The required checks are:

```bash
python3 -m compileall eagle
python3 -m unittest discover -s tests
git diff --check
```

The test suite uses mocked generation/matches and does not constitute a full
MicroRTS evolutionary experiment.
