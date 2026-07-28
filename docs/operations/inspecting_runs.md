# Inspecting EAGLE runs

Use `./analyze.sh` to select the latest valid direct child of the configured
run root, or pass one explicit relative or absolute canonical run folder:

```bash
./analyze.sh
./analyze.sh runs/20260728_143000_eagle
./analyze.sh /home/mhlab/EAGLE/runs/20260728_143000_eagle
```

A canonical run is identified by a supported `manifest.json`, a supported
resolved configuration, and either a completed generation or an initialized
run status. Latest selection prefers `manifest.last_update_time` and falls
back to directory mtime.

Derived Markdown, JSON, CSV, and static Matplotlib plots are written under
`RUN_DIR/analysis/`. The canonical loader reads compact generation, final
population, timing, and error artifacts. It never reads `results.jsonl`.

Historical layouts are rejected. They require an explicit migration command:

```bash
python -m eagle migrate-run RUN_DIR
```

## Candidate debugging order

1. Confirm the manifest and resolved configuration schema versions.
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
| objective looks inconsistent | formula/schema versions and component payload | NSGA-II before recomputation |

## Artifact boundary

- Canonical analysis consumes only versioned compact artifacts.
- Runs with legacy Java layouts, objective names, or unversioned formulas require explicit migration.
- Old runs are not architecture-compliance evidence.
- Analysis outputs are derived evidence and never feed back into evolution.
