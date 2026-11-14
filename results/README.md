# Committed experiment results

`runs/` contains the full local experiment evidence and is intentionally ignored
by Git. Each `results/<experiment-id>/` directory is a portable analysis package
created by the GUI's **匯出 Git 結果包** action.

| File | Purpose |
| --- | --- |
| `manifest.json` | Schema, selected runs, filters, protocols, and file map |
| `points.csv` | Self-play, final-test, aggregate fixed, and per-opponent cross-generation points |
| `aggregates.csv` | Equal-weight seed summaries and ranges |
| `deltas.csv` | Same-seed treatment-minus-baseline comparisons |
| `opponents.csv` | Per-seed and pooled final-test W/D/L, win rate, and mean match score |
| `fixed_coverage.csv` | Candidate coverage for cross-generation fixed evaluation |
| `*.png` | Human-readable plots corresponding to the CSV data |

The GUI reads these packages directly, so a clone containing `results/` can
analyze experiments without the original `runs/` directory or local model and
MicroRTS runtime assets.
