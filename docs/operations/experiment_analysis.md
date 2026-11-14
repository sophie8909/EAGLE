# Experiment Analysis

Open **實驗分析** in the local GUI started by `gui.cmd`, `./gui.sh`, or
`python -m eagle gui --open`. Pick an experiment, select treatments and seeds,
and choose a run attempt where a seed was restarted. Refresh rebuilds the
catalog from current sources. The dashboard reads committed generation snapshots
and evaluation summaries. Analysis and export leave the launcher index and run
artifacts in place.

The default hierarchy comes from each batch's `experiment.yaml` and the exact
config filenames in it. The resolved run config supplies the effective seed.
The index position is recorded separately as the replicate index. If a run
has several attempts, the dashboard prefers the indexed attempt and uses only
one attempt per treatment and seed.

## Archive locations and treatment labels

Create `logs/experiment-analysis.yaml` on the machine running the GUI.
Repository-relative paths resolve from the checkout. Path mappings match
directory prefixes, with the longest match taking precedence. The local settings
file lives under the ignored `logs/` directory.

```yaml
schema_version: eagle-analysis-settings-v1
path_mappings:
  /home/mhlab/EAGLE/runs: D:/EAGLE-archive/runs
batches:
  configs/experiments/1108_gpt_vs_local_50x10_seed8_9/experiment.yaml:
    experiment: november-initialization
    treatments:
      10_gpt_initial_seed8_9.yaml:
        id: all-gpt
        label: 10 GPT initial
      1_gpt_9_local_seed8_9.yaml:
        id: one-gpt
        label: 1 GPT + 9 local
runs:
  - path: D:/EAGLE-archive/old/20261109_072720_479146
    experiment: november-initialization
    treatment: one-gpt
    benchmarks:
      - path: D:/EAGLE-archive/evaluation/fixed_evaluation_summary.json
```

Use the same experiment and treatment IDs to group matching conditions across
batches. IDs accept ASCII letters, digits, underscores and hyphens. A run
registration can also resolve ambiguous assignments or attach benchmark evidence
to an indexed run. Give the GUI access to the original `manifest.json`,
`config.yaml`, and the artifacts for the metrics you want to see. Diagnostics
list missing, ambiguous, unassigned, or unreadable sources.

For an archive that retained only a candidate-level fixed-evaluation CSV,
supply the historical `run_id` and integer `seed` on the run registration.
Set the benchmark `path` to the CSV, `label` to its exact treatment label, and
`population_size` to the expected population. A benchmark can also name a
recorded `protocol` JSON. Without it, the GUI shows the imported seed curve
individually.

## Interpret comparisons

Each convergence mean gives each contributing seed equal weight at that
generation. The band is the observed minimum–maximum for two or more seeds.
The fixed cohort option uses seeds with observations at every observed checkpoint
in the selected range. Changing opponents affect the interpretation of self-play
scores. The default fixed-benchmark population mean requires complete coverage
of the committed population at the checkpoint. Representative and population-best
views use distinct selection rules. Diversity curves require compatible metric
definitions.

Paired mode uses common seeds and a common observed generation horizon. Deltas
subtract the baseline value for the same seed and generation. Final-test endpoints
can come from different generations. Their per-seed rows identify requested and
evaluated generations, including fallback selection. A same-generation delta
requires compatible observations at a shared checkpoint.

Benchmark aggregates and paired deltas require recorded protocol identity.
Old final-test evidence can still show individual scores and match outcomes
when hashes or scoring provenance are missing. Pooled win rate divides wins by
counted wins, draws and losses. Mean seed win rate averages each seed's defined
rate. Errors and contained opponent faults have their own columns.

## Share results

Use **匯出 Git 結果包** to write the selected results under
`results/<experiment-id>/`. This is the portable, committed analysis layer;
the source `runs/` tree remains local and is ignored by Git. Each result package
contains a small `manifest.json`, CSV tables (`points`, `aggregates`, `deltas`,
`opponents`, `fixed_coverage`) and PNG charts. `points.csv` includes self-play,
final-test, all-opponent aggregates, and one fixed-opponent cross-generation
curve per recorded opponent. `opponents.csv` contains per-seed and pooled
final-test W/D/L, win rate, and mean match score.

The GUI reads committed packages from `results/` directly, so another machine
only needs the repository checkout to inspect them. It still reads `runs/` only
for live experiment status, resume, candidate browsing, and MicroRTS observation.
Existing packages under `reports/experiments/` remain readable for migration.
Use the source runs to export a different scope.
