# Opponent-wise fitness and lexicase selection

This is the focused current contract for the EAGLE evolutionary loop.

## Fixed evaluation cases

`eagle/opponent_cases.py` defines the canonical order:

```text
passive random randombias lightrush heavyrush workerrush allinbot mayari coac tma
```

For every candidate, `eagle/evaluation/pipeline.py` executes all ten cases on three
maps, for three rounds, with both p0 and p1 positions. The fixed matrix is
therefore 180 matches. `allibot` remains the historical GUI opponent ID;
the evolutionary case is `allinbot` in `eagle/opponents.py`.

`PassiveAI`, `RandomAI`, and `RandomBiasedAI` are active evolutionary cases,
using the canonical IDs `passive`, `random`, and `randombias`.

## Self-play cases

`evaluation.mode: self_play` uses the tournament-managed opponent pool. Four
top-tier built-ins are permanently protected; the other six built-ins and
generated agents are eligible. Novel entries fill available capacity, then
challenge one seeded sampled nonprotected incumbent in a complete 18-match
duel; replacement requires strictly more wins than losses. Incomplete/error
duels cannot promote an entrant. Generation zero evaluates all built-in sources
using protected actual case IDs and six `self_play_000`…`self_play_005` slots.
At generation one and each configured interval boundary, those six slots use
deterministically sampled nonprotected pool members. Context rows identify
built-ins by `source_opponent_id`. For capacity, resume, artifact, and failure
contracts, see the [canonical self-play contract](eagle_architecture_spec.md#9-evolution-evaluation).

At context refresh, parents receive fresh identities while preserving their
Java phenotype; they are reevaluated before selection without an LLM call.
Selection requires a single shared context ID. Self-play requires static
reflection and does not update the fixed-opponent archive.

## Fitness and reporting

In fixed-roster mode, `eagle/evaluation/objectives.py` returns exactly the ten case
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

`eagle/operators/selection.py:lexicase_select` uses the EA-seeded `random.Random`
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
anchor is not updated while forming a tier. A second parent prefers minimum
compatible semantic distance from the first, excluding the first parent when
another top-tier member exists (a singleton tier reuses its member). A survivor boundary uses seeded
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
  metric and detailed opponent/match summaries.

New search runs do not write `archives/opponents.json`. The explicit
`eagle analyze` command derives `analysis/opponent_representatives.json` from
all evaluated candidates, including nonsurvivors.

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
