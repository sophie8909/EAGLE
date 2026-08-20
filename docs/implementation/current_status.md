# Current implementation status

Snapshot: 2026-08-18. This file describes executable repository behavior.

## Active evolutionary contract

- The search roster is exactly seven fixed opponents: `lightrush`, `heavyrush`,
  `workerrush`, `allinbot`, `mayari`, `coac`, and `tma`. `PassiveAI`, `RandomAI`,
  and `RandomBiasedAI` remain available as definitions but are excluded from EA.
- Every candidate runs 126 matches: three maps × three rounds × both sides
  for each opponent.
- Match repetitions are identified by `round_index`. The obsolete
  `match_seeds` field, unread `eagle.match.seed` JVM property, and match-level
  seed artifacts are removed; MicroRTS matches do not claim seeded
  reproducibility.
- Candidate fitness is a seven-field opponent score mapping. Failed or
  incomplete candidates receive `-1000.0` for every case.
- Parent selection is seeded lexicase. Survivor selection fills the fixed-size
  population with seeded lexicase-selected offspring, using parent fallback only
  when offspring are insufficient; aggregate Game Performance is reporting-only.
- The reflection-operator controller supports exactly `static`, `aos_opponent`,
  and `aos_head2head`. Strategy/Code probabilities mean fixed probabilities in
  static mode and initial probabilities in AOS modes. Static performs no reward
  work. Opponent AOS restores execution-first seven-case W/D/L-rank change.
  Head-to-head AOS preserves the configured direct parent-A matrix and
  `(wins + 0.5 × draws) / valid matches`. Both adaptive modes share the alpha
  `0.20` EMA/probability-matching updater and configured minimum floor.
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
| Reflection selection, reward providers, shared AOS updater | `eagle/aos.py` |
| Head-to-head-only parent-vs-offspring evaluation | `evaluation/parent_offspring.py` |
| Match aggregation | `evaluation/game_metrics.py` |
| Objective construction | `evaluation/objectives.py` |
| Parent and survivor selection | `eagle/selection.py` |
| Evolution loop | `eagle/search.py`, `eagle/resume.py` |
| Experiment/model lifecycle | `eagle/experiment.py`, `eagle/runtime/processes.py` |
| Fully resolved experiment schema | `eagle/config.py`, run-local `config.yaml` |
| Per-opponent archive | `eagle/opponent_archive.py` |
| Run/generation artifacts | `eagle/run_artifacts.py`, `eagle/artifacts.py` |
| Offline analysis | `eagle/analysis/report.py` |

## Persisted per-generation evidence

Each `generations/generation_*.json` stores candidate IDs with seven-case
fitness vectors, one aggregate `metrics` object, and the generation AOS record.
Candidate state lives once in `candidates/<id>/candidate.json`; specialized
opponent evidence remains in `evaluation/game_performance.json`.
The analysis command turns these records into
`agent_win_rate.csv`, `match_game_performance.csv`,
`opponent_game_performance.csv`, individual-agent per-opponent win-rate/Game
Performance plots, per-opponent generation plots with single-match score
violin distributions, and AOS operator statistics/probability plots. The v2 loader
materializes bounded candidate analysis views from referenced candidate and
evaluation artifacts, so compact v3 generation snapshots do not discard the
single-match distributions.

## Experiment lifecycle and run schema

`./experiment.sh CONFIG_TARGET [OPTIONS...]` translates its positional target
to Python `--config-dir`. Python discovers sorted top-level YAML files exactly
once, loads each exactly once, and invokes one batch owner that validates and starts the configured llama.cpp model,
waits for health, runs search and the production final test, and stops only its
owned process. Folder batches start an identical resolved runtime once and reuse
it directly for later configs using every launch-critical field; a changed runtime profile is stopped and replaced. Mock mode never constructs the runtime manager or inspects a port. Runtime state records PID plus process start time, exact executable/command, launcher, owner token, and resolved spec; foreign port owners are never killed.
Separate runtime/run compatibility commands are not part of production. The
dispatcher exposes only `experiment` and `analyze`.

Directory batches also maintain an atomic `experiment.yaml` index in the
selected config directory. Each entry maps the config filename to its absolute
run folder at run-creation time; the generated index is excluded from later
config discovery. A legacy `experiment-v2` config with that filename is
preserved rather than replaced.

New `eagle-run-v2` runs persist one fully resolved `config.yaml`. The root has
only manifest/config/summary/timing plus canonical directories. Candidate,
generation, match, archive, and config compatibility duplicates have been
removed. Analysis and resume both require v2 and use the run-local model and
experiment definition.

## Prompt ownership

All executable prompt bodies live under `prompts/`, with exactly one UTF-8
`.txt` file per prompt. `prompts/manifest.toml` stores only prompt metadata and
placeholder contracts. This includes the initial EA individual's strategy and
generation prompts, Code Reflection, the library Strategy Reflection/Rewrite
path, Match Commentator, all four Coach intents, generation, Strategy Alignment,
the action-API guide, and endpoint preflight. Experiment YAML files reference
`prompts/initial_strategy.txt` and `prompts/initial_generation.txt`; inline
prompt/template fields are rejected. Python modules only load, render, bound,
transport, and validate these resources.

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
