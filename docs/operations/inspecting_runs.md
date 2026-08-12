# Inspecting EAGLE runs

Use `./analyze.sh` to select the latest valid direct child of the configured
run root, or pass one explicit relative or absolute canonical run folder:

```bash
./analyze.sh
./analyze.sh runs/20260728_143000_eagle
./analyze.sh ~/EAGLE/runs/20260728_143000_eagle
```

A canonical run is identified by a supported `manifest.json`, a supported
resolved configuration, and either a completed generation or an initialized
run status. Latest selection prefers `manifest.last_update_time` and falls
back to directory mtime.

Derived Markdown, JSON, CSV, and static Matplotlib plots are written under
`RUN_DIR/analysis/`. The canonical loader reads compact generation, final
population, timing, and error artifacts. It never reads `results.jsonl`.

Individual agent Game Performance is written to
`analysis/agent_game_performance.csv` and plotted in
`analysis/plots/agent_game_performance.png`. To print one agent's score by
generation, use:

```bash
./analyze.sh --agent <candidate_id>
./analyze.sh --run-dir <run_dir> --agent <candidate_id>
```

Per-opponent Game Performance is recorded for every completed generation in
`analysis/opponent_game_performance.csv`. The plot set contains
`code_quality_by_generation.png`, `game_performance_by_generation.png`,
`agent_game_performance.png`, and one
`game_performance_by_generation_<opponent>.png` for each opponent present in
the generation metrics. The per-opponent values are the mean raw Game
Performance score across that generation's surviving population; the main
aggregate Game Performance objective remains weighted as recorded by the
evaluation artifact.

Historical layouts are rejected. The canonical command surface intentionally has
no migration subcommand; migrate or inspect old data outside the EAGLE runtime
before presenting it to `./analyze.sh`.

## Candidate debugging order

1. Confirm the manifest and resolved configuration schema versions.
   The resolved configuration records the direct GGUF model path used by the
   run together with population, generation, crossover, and mutation settings.
2. Inspect the compact generation record and final-population entry.
3. Follow the candidate's lineage and stage artifact references.
4. Compare generation request, raw response, extracted source, and normalized source.
5. Read validation and compiler diagnostics before integration or match failures.
6. Verify all integration checks before interpreting runtime evidence.
7. Count match results and verify that source and class hashes remain stable.
8. Recompute objective components from persisted inputs using the recorded formula version.
9. Compare timing and attempt counts with the corresponding request/response artifacts.

Missing evidence must remain missing. Analysis must not infer fields or silently
activate a historical artifact layout.

## Failure triage

| Symptom | Inspect first | Do not misclassify as |
| --- | --- | --- |
| no backend response or extractable Java | generation attempts and raw responses | validation or compilation |
| complete source rejected before `javac` | validation result | generation transport failure |
| `javac` returns nonzero | compiler diagnostics | integration |
| class, constructor, or method cannot load | integration checks | compilation or runtime match |
| process starts but result is missing or partial | match output, result, and timing | valid loss or draw |
| fewer than 10 valid matches | completed match evidence | successful aggregate |
| objective looks inconsistent | formula/schema versions and ten-case component payload | lexicase selection before recomputation |

## Artifact boundary

- Canonical analysis consumes only versioned compact artifacts.
- Runs with legacy Java layouts, objective names, or unversioned formulas require explicit migration.
- Old runs are not architecture-compliance evidence.
- Analysis outputs are derived evidence and never feed back into evolution.
