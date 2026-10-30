# Experiment comparison, supplied 2026-10-29

Source: user-provided summary, described as based on immutable per-run config.yaml, manifest.json and summary.json. Run files were not independently retrieved for this deck update. This snapshot supersedes the historical completion claims in the retained historical slides without changing those historical pages.

| Variant | Generations × population | Completed seeds | Reflection |
|---|---|---|---|
| Nearest mating v1 | 20 × 10 | 8–13 | none |
| Whole framework | 20 × 10 | 8–13 | G6, G11, G16 |
| Whole framework extended | 50 × 10 | 8, 9 | G6 through G46, interval 5 |
| Options only | 50 × 10 | 8 | G6 through G46, interval 5 |

## Controlled 20-generation comparison

Initial framework b2daa… for both groups. Final-generation best training fitness:

| Seed | Nearest | Whole framework | Difference |
|---|---:|---:|---:|
| 8 | 2.068 | 8.540 | +6.472 |
| 9 | 23.514 | 26.632 | +3.118 |
| 10 | -14.280 | 5.388 | +19.669 |
| 11 | 17.450 | 14.541 | -2.909 |
| 12 | 13.635 | 2.420 | -11.216 |
| 13 | 21.738 | 29.915 | +8.177 |
| Mean | 10.688 | 14.573 | +3.885 |

Differences and means retain supplied precision; raw underlying precision was not supplied. Rounded inputs can differ in the last displayed digit.

600 final-test matches per run, 3600 per group:

| Variant | W | D | L | Win % | Score % |
|---|---:|---:|---:|---:|---:|
| Nearest | 1251 | 45 | 2304 | 34.75 | 35.38 |
| Whole framework | 1257 | 52 | 2291 | 34.92 | 35.64 |

Score = (W + 0.5 D) / matches. Reflection wins on fitness in 4 of 6 seeds. Eighteen reflection boundaries: 16 successful, 2 rollback. Final-test win-rate gain is 0.17 percentage points, with no established stable generalization gain.

## 50-generation results

| Variant | Seed | Final-generation best | Run peak | Final-test W–D–L | Win % | Reported hours |
|---|---:|---:|---|---|---:|---:|
| Whole framework | 8 | -4.484 | 25.281 @ G10 | 305–5–290 | 50.83 | 8.81 |
| Whole framework | 9 | -19.585 | 13.955 @ G20 | 215–4–381 | 35.83 | 9.09 |
| Options only | 8 | 16.893 | 30.030 @ G20 | 299–15–286 | 49.83 | 8.48 |

Initial framework: whole abb8b57…, options f674a58…. This is not a controlled A/B comparison of reflection scope. Supplied total-hour accounting boundary and G0/generation timing breakdown were not provided.

Incomplete: whole seed 10 stopped before G0; seeds 11–13 not created. Options seed 9 stopped at manifest G10 with no process remaining, best fitness 16.370, no final test, excluded; seeds 10–13 not created. Status reflects supplied snapshot only.

Next discriminating experiment: identical initial bundle and both methods completed on seeds 8–13.

Config locators (remote host):
- /home/mhlab/EAGLE/configs/experiments/1023_rich_framework_local_nearest_20x10_seed8_13_1run/qwen3_5_9b_rich_framework_local_nearest_20x10_seed8_13_1run.yaml
- /home/mhlab/EAGLE/configs/experiments/1027_rich_framework_reflection_50x10_seed8_13_shared_framework_1run/qwen3_5_9b_rich_framework_reflection_50x10_seed8_13_shared_framework_1run.yaml
- /home/mhlab/EAGLE/configs/experiments/1028_rich_framework_option_reflection_50x10_seed8_13_shared_framework_1run/qwen3_5_9b_rich_framework_option_reflection_50x10_seed8_13_shared_framework_1run.yaml

## Added comparison: farthest versus nearest mating

Updated in place on 2026-10-29, pages 55–58. No additional deliverable filename was created.

Historical farthest evidence: `Meeting/20261021_current_workflow/stability_report_data.json`, a 2026-10-22 remote-artifact snapshot. Both cohorts are complete six-seed batches (8–13), 20 generations × 10 individuals, the same frozen bundle `b2daa0d4baac80e446d46e5d32f6fd94a4300bec51f23b4816723c6d8f90939b`. Farthest-parent attribution uses pre-`28ea6606` selection code (maximum compatible semantic distance in the highest fitness tier) and the run dates. Historical reports call these cohorts “previous” and “current”; neither is a nearest cohort.

- Farthest A: runs 20261019_152601_037528, 20261019_182037_312877, 20261019_103405_871333, 20261020_135403_027378, 20261020_170514_392422, 20261020_195907_969170.
- Farthest B: runs 20261021_002848_496277, 20261021_034914_985024, 20261021_074505_348782, 20261021_131355_062329, 20261021_165442_013504, 20261021_202021_187555.
- Nearest: runs 20261023_151204_341358, 20261023_180405_787806, 20261023_212812_281819, 20261024_011410_881302, 20261024_042841_102310, 20261024_072749_959729.

Nearest full precision was recovered from the read-only remote chat “整理三版實驗數據” (`01a18364-c2a6-7f82-9103-a981d2cf4439`), whose command outputs list per-run `summary.json` and final-test aggregation. Raw remote run files were not fetched anew. Both farthest cohorts are retained separately rather than pooled as twelve independent seeds.

| Seed | Farthest A G20 best | Farthest B G20 best | Nearest G20 best | Nearest minus B |
|---|---:|---:|---:|---:|
| 8 | 5.592004 | -3.341748 | 2.068053 | 5.409801 |
| 9 | 25.732783 | 22.999510 | 23.514200 | 0.514690 |
| 10 | -32.036904 | -32.033214 | -14.280196 | 17.753018 |
| 11 | 10.988062 | 13.117691 | 17.449923 | 4.332232 |
| 12 | 6.760507 | 8.560747 | 13.635489 | 5.074742 |
| 13 | 18.267322 | 22.949003 | 21.738132 | -1.210871 |
| Mean | 5.883962 | 5.375332 | 10.687600 | 5.312269 |

| Cohort | W | D | L | Matches | Win % | Score % |
|---|---:|---:|---:|---:|---:|---:|
| Farthest A | 1164 | 152 | 2284 | 3600 | 32.33 | 34.44 |
| Farthest B | 1122 | 148 | 2330 | 3600 | 31.17 | 33.22 |
| Nearest | 1251 | 45 | 2304 | 3600 | 34.75 | 35.38 |

Nearest versus B: fitness +5.312269; 5/6 seeds improve; win rate +3.583333 percentage points; score rate +2.152778 percentage points. Versus A: fitness +4.803638; 4/6 improve; win rate +2.416667 percentage points; score rate +0.930556 percentage points.

These are cross-date observations, not a strict A/B that isolates every code/runtime difference. Self-play opponent snapshots diverge with the search; no new repeated nearest runs or uncertainty test was performed. Nearest search timing on the same accounting boundary is unavailable, so no cost-efficiency claim is made.
