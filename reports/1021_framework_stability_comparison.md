# EAGLE framework stability comparison

> 分析日期：2026-10-21 13:35（Asia/Taipei）
> 本報告比較上次六個 seed 與本次 `1021_rich_framework_stability_20x10_seed8_13_1run` 批次。
> 本次 seed 13 尚未完成，因此所有「本次完成批次」統計只包含 seed 8–12。

## 1. 批次與設定

兩批都使用相同的核心架構與評估協定：

- `java_materialization_mode: framework_slots`
- `framework.evolution_mode: local`
- 相同 frozen framework bundle：`b2daa0d4baac80e446d46e5d32f6fd94a4300bec51f23b4816723c6d8f90939b`
- `population_size: 10`、`generations: 20`
- self-play、`tournament-v1`、三張地圖、每個 candidate 每代 180 matches
- final test：10 opponents × 3 maps × 10 games/side = 600 matches
- static operator controller；framework local mode 不呼叫 candidate-time LLM

本次 resolved config 相對上次 seed 8 的實質差異只有 experiment name、批次 seed 清單，以及 run-owned bundle 路徑；bundle bytes 與 bundle hash 相同。

## 2. 完成狀態與執行可靠性

| 批次 | seed | run | generations | final test | 結果 |
|---|---:|---|---:|---:|---|
| 上次 | 8 | `20261019_152601_037528` | 20/20 | 600/600 | complete |
| 上次 | 9 | `20261019_182037_312877` | 20/20 | 600/600 | complete |
| 上次 | 10 | `20261019_103405_871333` | 20/20 | 600/600 | complete |
| 上次 | 11 | `20261020_135403_027378` | 20/20 | 600/600 | complete |
| 上次 | 12 | `20261020_170514_392422` | 20/20 | 600/600 | complete |
| 上次 | 13 | `20261020_195907_969170` | 20/20 | 600/600 | complete |
| 本次 | 8 | `20261021_002848_496277` | 20/20 | 600/600 | complete |
| 本次 | 9 | `20261021_034914_985024` | 20/20 | 600/600 | complete |
| 本次 | 10 | `20261021_074505_348782` | 20/20 | 600/600 | complete |
| 本次 | 11 | `20261021_131355_062329` | 20/20 | 600/600 | complete |
| 本次 | 12 | `20261021_165442_013504` | 20/20 | 600/600 | complete |
| 本次 | 13 | `20261021_202021_187555` | 4/20 | 尚未開始 | running |

截至本報告：

- 已完成 11 個 run，全部正常完成 20 代。
- 每個已完成 run 的 generation 20 都是 `1800/1800` matches、`failure_count=0`。
- 已完成的 11 個 final test 都是 600 matches、Integration success、0 errors。
- 尚未看到 run failure、interruption 或 artifact corruption。
- seed 13 generation 0–4 也都是 `1800/1800`、`failure_count=0`；目前仍在執行，不應視為完成結果。

**判定：執行管線、framework materialization、Java Integration 與 MicroRTS evaluation 已呈現很強的穩定性。**

## 3. generation 20 表現

`game_performance` 是 self-play 的 search objective；數值越高越好。以下的 mean 是 generation 20 population 的平均，不是跨 seed 平均。

### 上次六 seed

| seed | best | population mean | population sd | semantic unique / 10 |
|---:|---:|---:|---:|---:|
| 8 | 5.592 | 4.307 | 0.675 | 1 |
| 9 | 25.733 | 24.711 | 0.691 | 2 |
| 10 | -32.037 | -38.789 | 3.609 | 2 |
| 11 | 10.988 | 9.419 | 0.696 | 1 |
| 12 | 6.761 | 5.639 | 0.698 | 1 |
| 13 | 18.267 | 15.719 | 1.029 | 4 |
| **跨 seed 平均** | **5.884** | — | — | — |

### 本次已完成五 seed

| seed | best | population mean | population sd | semantic unique / 10 |
|---:|---:|---:|---:|---:|
| 8 | -3.342 | -5.262 | 0.801 | 3 |
| 9 | 23.000 | 21.126 | 1.073 | 1 |
| 10 | -32.033 | -38.788 | 3.613 | 2 |
| 11 | 13.118 | 12.466 | 0.307 | 1 |
| 12 | 8.561 | 7.886 | 0.410 | 1 |
| **跨 seed 平均** | **1.861** | — | — | — |

本次 seed 13 尚未完成；目前 generation 4 的 best/mean 為 `-11.475 / -12.435`，不可與 generation 20 直接比較。

### 同 seed 重跑差異

| seed | 本次 best − 上次 best | 觀察 |
|---:|---:|---|
| 8 | -8.934 | 本次較弱，仍為可完成但未突破的 run |
| 9 | -2.733 | 本次略弱，仍是高表現 seed |
| 10 | +0.004 | 幾乎完全一致的低表現 basin |
| 11 | +2.130 | 本次改善 |
| 12 | +1.800 | 本次改善 |

目前本次五 seed 的 best 平均比上次六 seed 平均低 `4.023`，但這不是同樣樣本數的比較，且缺少 seed 13。更重要的是 seed 10 幾乎完全重現（`-32.037` vs `-32.033`），顯示差異主要來自 seed-dependent search trajectory，而不是架構或 runtime 不穩定。

整體跨 seed 的 spread 也相近：上次 best 範圍 `-32.037..25.733`，本次已完成 seed 8–12 為 `-32.033..23.000`。因此目前證據支持「穩定但表現高度依賴 seed」，不支持「架構退化」。

## 4. 表現軌跡

下表是各 seed 在 generation 0、5、10、15、20 的 population best。這能區分早期進步、後期收斂與最後回落。

| seed | 批次 | g0 | g5 | g10 | g15 | g20 |
|---:|---|---:|---:|---:|---:|---:|
| 8 | 上次 | -57.328 | -1.360 | 6.184 | 5.124 | 5.592 |
| 8 | 本次 | -57.338 | -1.108 | 5.643 | 5.716 | -3.342 |
| 9 | 上次 | -71.714 | -58.547 | -18.482 | 22.950 | 25.733 |
| 9 | 本次 | -71.713 | -58.572 | -19.243 | 22.496 | 23.000 |
| 10 | 上次 | -70.592 | -49.131 | -41.481 | -14.999 | -32.037 |
| 10 | 本次 | -70.590 | -49.136 | -41.493 | -15.003 | -32.033 |
| 11 | 上次 | -69.304 | 4.586 | 24.210 | 22.450 | 10.988 |
| 11 | 本次 | -69.300 | 7.340 | 20.633 | 24.229 | 13.118 |
| 12 | 上次 | -70.457 | 0.010 | 9.678 | 23.498 | 6.761 |
| 12 | 本次 | -70.451 | 0.007 | 12.555 | 24.649 | 8.561 |
| 13 | 上次 | -70.967 | -11.476 | -2.799 | -5.855 | 18.267 |

共同模式是 generation 0 幾乎一致、前 5–15 代會快速改善，之後進入 seed-specific basin。seed 10 在兩次實驗都於後期回落到約 `-32`，是最明顯的可重現低表現路徑；這比較像搜尋/評估 landscape 的穩定特徵，而非偶發 runtime 問題。

## 5. final-test 對手剖面

已完成 run 的 final test 都通過 600-match protocol。跨已完成 run 的 W/D/L/E 總結如下：

| 批次 | runs | wins | losses | draws | errors | aggregate win rate |
|---|---:|---:|---:|---:|---:|---:|
| 上次六 seed | 6 | 1164 | 2284 | 152 | 0 | 32.33% |
| 本次已完成五 seed | 5 | 905 | 1950 | 145 | 0 | 30.17% |

本次五個完成 seed 的共通能力剖面：

- PassiveAI / RandomAI：穩定取勝或打平，說明基本行為與執行鏈正常。
- RandomBiasedAI：仍有大量勝場，但 seed 間差異明顯。
- LightRush、HeavyRush、WorkerRush：表現高度 seed-dependent，尚未形成一致的 rush counter。
- AllInBot：本次合計只有 1 勝、3 draws、296 losses；仍是明顯弱點，但沒有 evaluation error。
- Mayari：0 勝、11 draws、289 losses。
- COAC：10 勝、290 losses，10 勝集中於 seed 11。
- TMA：0 勝、300 losses。

因此 framework 已穩定地把「合法 Java、可 Integration、可完成完整 match matrix」維持住，但穩定性不等於策略能力已經穩定解決所有 hard opponents。

## 6. 多樣性與收斂

`framework_slots` 沒有 Strategy DSL niche，因此 `strategy_diversity` 的 `known_signature_count` 為 0 不能解讀成「沒有 framework 行為多樣性」。應看 `semantic_library` 的九狀態行為 signature。

generation 20 的 semantic unique counts：

- 上次：`[1, 2, 2, 1, 1, 4] / 10`
- 本次已完成：`[3, 1, 2, 1, 1] / 10`

大多數 run 的 final population 已收斂到 1–2 個行為等價類，最大等價類通常為 9–10 個 candidate。這與低 population standard deviation、固定 framework bundle、local operator 設定一致：系統是穩定收斂，但探索寬度窄。

## 7. 結論與建議

### 結論

1. **架構/執行穩定性：通過。** 已完成的 11 個 run 全部跑滿 20 generations；generation-level evaluation 全部 1800/1800、0 failures；final test 全部 600 matches、Integration success、0 errors。
2. **跨 seed 可重現性：部分通過。** seed 10 幾乎完全重現；其他 seed 的 trajectory 與 final score 有合理的 stochastic variation。這表示 runtime contract 穩定，但 outcome 仍受 seed 影響。
3. **搜尋穩定性：表現穩定但容易收斂。** 大多數 final population 的 semantic unique count 只有 1–2/10，說明架構不會崩，但探索多樣性不足。
4. **能力穩定性：尚未通過 hard-opponent robustness。** AllInBot、Mayari、COAC、TMA 仍普遍是 loss；目前不能把「所有 run 完成」誤認為「策略品質已穩定」。
5. **本次批次尚未完結。** seed 13 仍在 generation 4，應待其 final test 完成後再更新六 seed aggregate 結論。

### 建議下一步

- 先讓 seed 13 完成，再更新六 seed 的完整 aggregate。
- 若目標是驗證 architecture，這批結果已足以支持目前 framework/evaluation pipeline 可用。
- 若目標是提升策略品質，下一輪應優先處理 semantic convergence 與 hard-opponent coverage，而不是先修改 runtime/framework materialization。
- 建議另做固定 final-test snapshot 或跨 seed representative comparison，避免只用 self-play search fitness 判定架構優劣。

## 8. 主要 artifact 索引

### 上次六 seed

- `runs/20261019_152601_037528`
- `runs/20261019_182037_312877`
- `runs/20261019_103405_871333`
- `runs/20261020_135403_027378`
- `runs/20261020_170514_392422`
- `runs/20261020_195907_969170`

### 本次批次

- batch index：`configs/experiments/1021_rich_framework_stability_20x10_seed8_13_1run/experiment.yaml`
- config：`configs/experiments/1021_rich_framework_stability_20x10_seed8_13_1run/qwen3_5_9b_rich_framework_stability_20x10_seed8_13_1run.yaml`
- completed seed 8–12：`runs/20261021_002848_496277`, `runs/20261021_034914_985024`, `runs/20261021_074505_348782`, `runs/20261021_131355_062329`, `runs/20261021_165442_013504`
- active seed 13：`runs/20261021_202021_187555`
