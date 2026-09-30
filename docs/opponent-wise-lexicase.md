# Opponent-wise fitness and lexicase selection

This is the focused current contract for the EAGLE evolutionary loop.

## Fixed evaluation cases

`eagle/opponent_cases.py` defines the canonical order:

```text
passive random randombias lightrush heavyrush workerrush allinbot mayari coac tma
```

For every candidate, `eagle/evaluation.py` executes all ten cases on three
maps, for three rounds, with both p0 and p1 positions. The fixed matrix is
therefore 180 matches. `allibot` remains the historical GUI opponent ID;
the evolutionary case is `allinbot` in `eagle/opponents.py`.

`PassiveAI`, `RandomAI`, and `RandomBiasedAI` are active evolutionary cases,
using the canonical IDs `passive`, `random`, and `randombias`.

## Self-play cases

`evaluation.mode: self_play` uses a bounded cross-generation opponent library.
Generation zero seeds the library; every configured refresh boundary appends
runnable current parents, FIFO-evicts entries beyond
`self_play_opponent_library_capacity`, and deterministically rotates up to ten
stored phenotypes into the next immutable context. The selected candidates are
cycled in stable order into `self_play_000` through `self_play_009`, all with
weight `1.0`; self-matches remain valid. The refresh interval defaults to five
generations.

At refresh, parents receive fresh identities but preserve their Java phenotype
and make no LLM call. They are evaluated against the new context before
reflection and offspring planning. Selection rejects a pool unless every
candidate has the same context ID. Self-play requires static reflection and
does not update the fixed-opponent archive.

## Fitness and reporting

In fixed-roster mode, `evaluation/objectives.py` returns exactly the ten case
scores, stored in `Candidate.fitness_objectives`. In self-play, those slot
scores remain evaluation diagnostics and `Candidate.fitness_objectives` stores
only the unweighted aggregate `game_performance`. A failed or incomplete
self-play candidate gets `-1000.0` for that scalar objective.

`eagle/opponent_cases.py:aggregate_game_performance` computes a reporting-only
weighted mean. The weights are `0.5` for `passive`, `random`, and `randombias`,
`1` for `lightrush`, `heavyrush`, and `workerrush`, and `2` for `allinbot`,
`mayari`, `coac`, and `tma`; the denominator is `12.5`. Code quality is stored
under `Candidate.code_quality_result` and is not an objective.

## Selection

`eagle/selection.py:lexicase_select` uses the EA-seeded `random.Random`
instance. It shuffles the ten case order, filters the current survivors to
the best score for each case, and stops when one candidate remains. There is
no Pareto rank, crowding distance, dominance comparator, or code-quality
tie-break in the active selection path.

For fixed roster, `select_next_generation` combines parents and offspring, then fills the fixed
population by repeated lexicase selection without replacement from that joint
`mu_plus_lambda` pool. Parents receive no age bonus and offspring receive no
preference. Aggregate Game Performance remains reporting-only and does not
select survivors.

For self-play, parent and survivor selection maximize `game_performance`.
Candidates within `1.0` inclusive of the current tier maximum are tied. The
anchor is not updated while forming a tier. A second parent prefers maximum
semantic distance from the first, and a survivor boundary uses seeded
farthest-first selection over compatible nine-probe signatures. Semantic
evidence cannot promote a candidate from a lower fitness tier.

Reflection operator selection is a separate credit path. `static` has no
reward; `aos_opponent` compares the existing ten case W/D/L ranks with the
recorded mutation-evidence parent; `aos_head2head` uses the offspring
win-plus-half-draw rate over configured direct matches against that same
parent. Neither reward becomes a lexicase case.

## Artifacts and analysis

The following records are written after each generation:

- `generations/generation_<n>.json`: surviving candidates, active-mode
  `fitness_objectives`, semantic summaries, and semantic-library metrics;
- `generations/generation_*.json`: ten objective statistics plus
  `opponent_scores.by_candidate` and `opponent_scores.by_opponent`;
- `archives/self_play_opponents.json`: bounded library entries and Java hashes;
- `generations/generation_<n>_self_play_snapshot.json`: active context, library
  provenance, ten slots, and context hash;
- `candidates/<id>/evaluation/objectives.json`: active-mode objective mapping;
- `candidates/<id>/evaluation/game_performance.json`: aggregate reporting
  metric and detailed opponent/match summaries;
- `archives/opponents.json`: one best valid representative per opponent case.

`python -m eagle analyze --run-dir <run>` writes
`opponent_game_performance.csv` and one
`plots/game_performance_by_generation_<opponent>.png` for every opponent,
along with the aggregate and code-quality diagnostic plots.

## Removed behavior

The active path never adds a generation-dependent opponent weight and does not
use `code_quality` as an evolutionary objective. Self-play exists only behind
its explicit config mode and immutable library-context contract. Legacy artifact
readers are not allowed to invent missing scores; old candidates are
represented as incomplete data.
