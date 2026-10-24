# EAGLE 實驗總索引

整理日期：2026-10-24

本索引統一整理 `runs/` 下的 48 個 manifest-backed runs，以及 4 個非標準資料目錄。既有 run 目錄不搬移，避免破壞 artifact 內的相對路徑、resume 參照與 provenance。

## 狀態總覽

| 類別 | 數量 | 說明 |
|---|---:|---|
| manifest-backed runs | 48 | 可由 `manifest.json`、`config.yaml`、`summary.json` 追蹤 |
| complete | 42 | 有完整 generation checkpoint |
| running | 2 | `20261018_111217_933817`、`20261020_004608_464397` |
| initialized | 3 | 尚未產生完整 generation |
| interrupted | 1 | `20261023_151144_972582` |
| 非標準目錄 | 4 | framework bootstrap、LLM stability、reflection inspection 資料 |

## 實驗組別

| 實驗名稱 | Runs | 完成 | generations | best fitness 平均 | 備註 |
|---|---:|---:|---:|---:|---|
| `ministral3_8b_deterministic_dsl_3x2_seed8_3runs` | 2 | 2 | 3 / 20 | 31.742 | deterministic DSL 早期基準 |
| `fixed_worker_combat_framework_fixed_init_coach_20x10_seed8_1run` | 1 | 1 | 20 | 0.248 | framework coach |
| `qwen3_5_9b_framework_coach_tournament_pool_20x10_seed8_1run` | 1 | 1 | 20 | -61.810 | framework coach tournament pool |
| `qwen3_5_9b_gen2_pop3_smoke` | 1 | 1 | 2 | -46.903 | smoke run |
| `qwen3_5_9b_gen2_pop3_seed8_13_2run` | 4 | 4 | 2 | -49.548 | population 3、generation 2 |
| `qwen3_5_9b_rich_framework_local_20x10_seed8_1run` | 2 | 2 | 20 | 1.272 | seed 8 重複 run |
| `qwen3_5_9b_rich_framework_local_20x10_seed9_1run` | 1 | 1 | 20 | 25.733 | seed 9 |
| `qwen3_5_9b_rich_framework_local_20x10_seed10_1run` | 1 | 1 | 20 | -32.037 | seed 10 |
| `qwen3_5_9b_rich_framework_local_20x10_seed11_1run` | 3 | 1 | 9 / 20 | 10.988 | 1 complete、1 running、1 initialized |
| `qwen3_5_9b_rich_framework_local_20x10_seed12_1run` | 1 | 1 | 20 | 6.761 | seed 12 |
| `qwen3_5_9b_rich_framework_local_20x10_seed13_1run` | 1 | 1 | 20 | 18.267 | seed 13 |
| `qwen3_5_9b_rich_framework_local_20x20_seed8_1run` | 1 | 0 | 14 | — | running、population 20 |
| `qwen3_5_9b_rich_framework_stability_20x10_seed8_13_1run` | 13 | 12 | 20 | 4.758 | stability 重複試驗 |
| `qwen3_5_9b_rich_framework_stability_20x10_seed8_13_2run` | 5 | 4 | 20 | 12.488 | seed 8 / 13 重複試驗 |
| `qwen3_5_9b_rich_framework_stability_20x10_seed14_17_1run` | 4 | 4 | 20 | -8.499 | seed 14–17 |
| `qwen3_5_9b_rich_framework_local_nearest_20x10_seed8_13_1run` | 7 | 6 | 20 | 10.688 | 最新主實驗；另有 1 interrupted |

## Run 對照表

### Deterministic / framework / smoke

| Run | 狀態 | Seed | Latest generation | Best fitness |
|---|---|---:|---:|---:|
| `20261015_002808_801634` | complete | 8 | 3 | 1.000 |
| `20261015_003919_084002` | complete | 8 | 20 | 62.484 |
| `20261016_164627_002786` | complete | 8 | 20 | 0.248 |
| `20261017_204454_103571` | complete | 8 | 20 | -61.810 |
| `20261023_114130_876274` | complete | 8 | 2 | -46.903 |
| `20261023_121202_353868` | complete | 8 | 2 | -46.902 |
| `20261023_122938_462298` | complete | 8 | 2 | -46.909 |
| `20261023_124713_922225` | complete | 13 | 2 | -52.190 |
| `20261023_130629_120085` | complete | 13 | 2 | -52.189 |

### Rich framework local runs

| Run | 狀態 | Seed | Latest generation | Best fitness |
|---|---|---:|---:|---:|
| `20261018_111217_933817` | running | 8 | 14 | — |
| `20261018_221813_144537` | complete | 8 | 20 | -3.049 |
| `20261019_103405_871333` | complete | 10 | 20 | -32.037 |
| `20261019_152601_037528` | complete | 8 | 20 | 5.592 |
| `20261019_182037_312877` | complete | 9 | 20 | 25.733 |
| `20261020_004608_464397` | running | 11 | 9 | — |
| `20261020_135305_553916` | initialized | 11 | — | — |
| `20261020_135403_027378` | complete | 11 | 20 | 10.988 |
| `20261020_170514_392422` | complete | 12 | 20 | 6.761 |
| `20261020_195907_969170` | complete | 13 | 20 | 18.267 |

### Stability runs

| Run | 狀態 | Seed | Best fitness |
|---|---|---:|---:|
| `20261021_000802_079435` | complete | 8 | -3.340 |
| `20261021_000858_164126` | initialized | 8 | — |
| `20261021_002848_496277` | complete | 8 | -3.342 |
| `20261021_032835_200412` | complete | 9 | 22.144 |
| `20261021_034914_985024` | complete | 9 | 23.000 |
| `20261021_072155_634143` | complete | 10 | -32.023 |
| `20261021_074505_348782` | complete | 10 | -32.033 |
| `20261021_125407_989371` | complete | 11 | 8.062 |
| `20261021_131355_062329` | complete | 11 | 13.118 |
| `20261021_163608_762480` | complete | 12 | 7.050 |
| `20261021_165442_013504` | complete | 12 | 8.561 |
| `20261021_200241_561743` | complete | 13 | 22.947 |
| `20261021_202021_187555` | complete | 13 | 22.949 |
| `20261022_015253_469117` | complete | 14 | 6.448 |
| `20261022_050957_656912` | complete | 15 | -49.480 |
| `20261022_094546_883680` | complete | 16 | -14.165 |
| `20261022_130947_147866` | complete | 17 | 23.201 |
| `20261022_165926_955459` | complete | 8 | 1.489 |
| `20261022_195201_240568` | complete | 8 | 3.373 |
| `20261022_224427_107383` | complete | 13 | 22.109 |
| `20261023_021814_646736` | complete | 13 | 22.981 |
| `20261023_114039_170495` | initialized | 8 | — |

### 最新 nearest runs

| Run | 狀態 | Seed | Best fitness |
|---|---|---:|---:|
| `20261023_151144_972582` | interrupted | 8 | — |
| `20261023_151204_341358` | complete | 8 | 2.068 |
| `20261023_180405_787806` | complete | 9 | 23.514 |
| `20261023_212812_281819` | complete | 10 | -14.280 |
| `20261024_011410_881302` | complete | 11 | 17.450 |
| `20261024_042841_102310` | complete | 12 | 13.635 |
| `20261024_072749_959729` | complete | 13 | 21.738 |

## 非標準資料目錄

| 目錄 | 用途 |
|---|---|
| `runs/framework_bootstrap/` | framework bundle/bootstrap 輸入與報告 |
| `runs/llm_stability/` | LLM stability report |
| `runs/llm_stability_restart/` | stability restart matrix |
| `runs/reflection_inspections/` | reflection inspection 實驗摘要與 timing |

## Artifact 保留與清理策略

保留：

- `manifest.json`、`config.yaml`、`summary.json`
- generation snapshots、policy records、lineage、genotype、phenotype
- candidate/evaluation/objective/game-performance 摘要
- compilation/integration 結果與 command metadata
- match `result.json`、`raw_result.json`、`performance_breakdown.json`、`match_metadata.json`
- `timing.jsonl` 與必要的 raw LLM artifacts

清理：

- 逐場 `telemetry.json.gz`
- 逐場 `match_trace.jsonl.gz`
- 逐場及 integration/compilation 的 `stdout.txt`、`stderr.txt`
- match commentary 目錄

清理不影響 generation summary、fitness、W/L/D 統計或 final-test summary；但不再保留逐場 trace、telemetry 與 process console 輸出。
