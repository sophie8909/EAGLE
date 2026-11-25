# Committed experiment results

| Published experiment | Completed seeds | Final Test per candidate |
| --- | --- | ---: |
| [10 Qwen 初始＋純 EA](1114_qwen_gen0_local_evolution_50x10_seed8_12/) | 8–12, using the Nov 21 WSL rerun for seed 8 | 600 |
| [1 GPT＋9 Qwen 初始＋純 EA](1122_1gpt_9qwen_gen0_local_evolution_50x10_seed8_12/) | 8–12, using the Nov 23 complete rerun for seed 8 | 300 |
| [GPT baseline（單一 GPT，無演化）](gpt_baseline_gen0/) | 8, G0 only | 600 |

`runs/` contains the full local experiment evidence and is intentionally ignored
by Git. Each `results/<experiment-id>/` directory is a portable analysis package.
The single GPT baseline preserves the G0 scores and outcomes from the historical
report.

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
