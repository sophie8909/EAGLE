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
