# Champion final-test protocol

This document owns the post-evolution final-test contract. It does not alter the canonical Evolution Evaluation described in [`evaluation_pipeline.md`](evaluation_pipeline.md).

## Two evaluation contexts

EAGLE has exactly two evaluation contexts:

1. **Evolution Evaluation** runs inside the EA, uses the fixed ten-match `ai.abstraction.LightRush` protocol, produces `game_performance` and `code_quality`, and may affect selection and variation.
2. **Final Test** runs only after a completed EA run, selects already evaluated Java using evolution artifacts alone, and measures gameplay against external champions.

There is no validation split or validation stage. Final Test never invokes an LLM, generation, repair, Reflection, Rewrite, crossover, mutation, or NSGA-II. Its results are descriptive and cannot affect candidate selection or evolutionary fitness. Operational source compilation and class-loading checks are prerequisites, not a model-selection stage.

## Opponent provenance

The committed manifest `third_party/final_test_opponents/manifest.toml` pins exactly:

| ID | Competition reference | Upstream | Pinned commit | Detected class | Prepared JAR |
| --- | --- | --- | --- | --- | --- |
| `tma` | 2024 CoG Classic Track winner | `https://github.com/MazzaAlessandro/TMA` | `7eee64e20deceaa19a65d06b7935a7c1ec7cffa6` | `ai.tma.TMA` | `third_party/final_test_opponents/jars/tma.jar` |
| `mayari` | 2021 CoG Classic Track winner | `https://github.com/barvazkrav/mayariBot` | `df5de837032e251323d11a2113d2e0179f83fe90` | `mayariBot.mayari` | `third_party/final_test_opponents/jars/mayari.jar` |
| `coac` | 2020 CoG Classic Track winner | `https://github.com/Coac/coac-ai-microrts` | `0c992fd1aa0d59867dfbd4ad8fe445c62e733f62` | `ai.coac.CoacAI` | `third_party/final_test_opponents/jars/coac.jar` |

The setup command clones only these pinned revisions, rebuilds source with the vendored MicroRTS classpath, detects concrete `AI` subclasses, checks the `UnitTypeTable` constructor, verifies class loading, hashes sources/JARs, and writes `resolved_manifest.json`:

```bash
python3 scripts/setup_final_test_opponents.py
```

The pinned upstream revisions contain no repository-level `LICENSE`, `COPYING`, or `NOTICE` file. Champion source and generated JARs therefore remain ignored local dependencies and are not redistributed by EAGLE. The resolved manifest records detected license files and any inspected upstream prebuilt JAR hash. COAC and Mayari are source-built directly; Mayari's upstream prebuilt JAR is hashed but not selected. TMA is source-built from its unchanged entrypoint and README-designated active `strategiesV2` sources. A committed behavior-free package marker satisfies TMA's stale wildcard import of the README-deprecated `strategies` package; its path and hash are explicit in the resolved manifest. RAISocketAI is intentionally excluded because it requires a separate Python/PyTorch/model runtime. An unavailable champion is a setup failure and is never replaced with a baseline.

## Candidate selection

Selection completes before any final-test match and reads only `summary.json`, `final_population`, `pareto_fronts`, and canonical candidate artifacts:

- `--candidate-id ID` selects that exact evaluated candidate.
- `--selector best-game-performance` maximizes evolution `game_performance`, then evolution `code_quality`, then ascending candidate ID.
- `--selector balanced` considers only the final Pareto front. Each objective is min-max normalized over that front; the unweighted Euclidean distance to ideal point `(1,1)` is minimized. Ties use game performance descending, code quality descending, then candidate ID ascending.
- `--selector pareto` tests every valid final-front candidate in ascending candidate-ID order.

`selection.json` records objectives, canonical source paths, tie decisions, timestamp, Git commit, and `no_final_test_result_used: true`.

## Match protocol

`configs/final_test_champions.yaml` is independent of evolution configuration. It uses three canonical vendored base/worker maps to cover multiple sizes without adding custom maps:

- `maps/8x8/basesWorkers8x8.xml`, 3000 cycles;
- `maps/16x16/basesWorkers16x16.xml`, 4000 cycles;
- `maps/24x24/basesWorkers24x24.xml`, 5000 cycles.

Seeds are `104729`, `130363`, and `155921`. Every selected candidate plays every champion, map, and seed as both player 0 and player 1. This produces `3 opponents * 3 maps * 3 seeds * 2 sides = 54` matches per candidate. The same schedule is used for every compared method/run.

The selected canonical Java source is copied with hash verification, compiled once into final-test-specific classes, and integration-checked once. Every match reuses the same source/class hashes and the canonical MicroRTS process launcher, result validation, telemetry parser, replay/round-state handling, timing, and terminal failure classification. Formal execution continues through its schedule to preserve all evidence, then exits non-zero if any match is incomplete or invalid.

## Artifacts and aggregation

Each execution writes beneath the completed run without changing evolution artifacts:

```text
runs/<run_id>/final_tests/<final_test_id>/
  config.yaml
  resolved_config.json
  selection.json
  opponents.json
  candidate_sources/<candidate_id>/
  candidate_classes/<candidate_id>/
  matches/<candidate_id>/<opponent_id>/<map_id>/player_<side>/seed_<seed>/
  results.jsonl
  summary.json
  failures.json
  timing.json
```

The schema is `eagle-final-test-v1`. Per-match evidence includes the command, stdout/stderr, parsed result, replay and round-state paths, telemetry, timing, side, opponent provenance, map, seed, cycle limit, source/class/JAR hashes, and terminal failure classification.

For completed matches:

```text
competition_points = wins + 0.5 * draws
final_test_competition_score = competition_points / completed_matches
final_test_win_rate = wins / completed_matches
non_loss_rate = (wins + draws) / completed_matches
```

Incomplete matches are counted explicitly and excluded from rate/score denominators. Summary breakdowns are aggregate, by opponent, by map, by candidate side, and by opponent-map pair. `evolution_game_performance` remains separate from final-test metrics.

## Reproduction

From the repository's WSL environment with Git, a JDK, Java, and the vendored MicroRTS runtime available:

```bash
python3 scripts/setup_final_test_opponents.py
python3 scripts/run_final_test.py \
  --run-dir runs/<run_id> \
  --selector best-game-performance \
  --config configs/final_test_champions.yaml
```

For the bounded compatibility check across all three champions, one map, one seed, and both sides:

```bash
python3 scripts/run_final_test.py \
  --run-dir runs/<run_id> \
  --candidate-id <candidate_id> \
  --config configs/final_test_champions.yaml \
  --smoke
```

The smoke flag produces six matches and is not a formal final test. A successful real smoke requires all six Java matches to complete; mock-only tests are not compatibility proof. Saved summaries are readable through `scripts/analyze_run.py` and the existing Runs & Candidates GUI Final Tests tab.
