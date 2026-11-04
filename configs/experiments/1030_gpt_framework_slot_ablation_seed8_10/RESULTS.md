# GPT framework slot-selection ablation：三種方法與目前結果

更新日期：2026-11-03（Asia/Taipei）

## 摘要

這組 ablation 要回答的問題是：**在完全相同的 GPT 設計 framework 下，只改變 generation 0 的 slot genome 初始化方式，是否會影響起始品質與後續 local evolution？**

目前結果顯示：

1. **方法 1（GPT 一次選 slot）**產生的單一 genome 在 generation 0 明顯優於同 seed 的純 local 初始候選，但對高強度對手仍不夠穩定。其完整固定評估為 265 勝、10 和、325 敗，勝率 44.17%，平均 match score 為 -9.505。
2. **方法 2（純 local evolution）**的 seed 8、9、10 都完成 100 代，三組內部 self-play 最佳分數都由負值提升為正值；但族群語意多樣性由 generation 0 的 100% 降到 generation 100 平均 13.3%。
3. **方法 3（GPT seed + local evolution）**的 seed 8、9、10 也都完成 100 代。GPT genome 在三個 seeds 都是 generation 0 最佳候選；相較方法 2，generation 0 best 平均提升 37.748，population mean 平均提升 6.311。
4. 到 generation 100，方法 3 對 AllInBot、Mayari、COAC、TMA 的三-seed族群平均都高於方法 2，改善分別為 +46.317、+8.024、+74.274、+24.092。不過 seed 9 並非全面改善，而且方法 2/3 尚未跑相同 checkpoints 的十對手 fixed evaluation，因此目前結論是「GPT seed 平均有效，但效果依演化 trajectory 而異」。

## 三種方法在做什麼

三種方法共用同一份 immutable framework bundle：

- bundle：`configs/framework_bundles/gpt_finite_rule_market_v1/bundle.json`
- SHA-256：`f674a580f0db088bd3436232d2dd36d071a231c9886f480a7aaed25669203e2b`
- Java materialization：`framework_slots`
- framework evolution：`local`
- 評估：self-play `tournament-v1`
- 地圖：8×8、16×16、24×24
- 每個正常 search candidate：10 個 opponent slots × 3 張地圖 × 3 rounds × 2 sides = 180 場
- self-play 中 AllInBot、Mayari、COAC、TMA 是永久固定對手；另外 6 個 slots 每 5 代更新一次

| 方法 | Generation 0 | 後續演化 | 設計目的 |
| --- | --- | --- | --- |
| 1. GPT slot once | GPT 透過一次 provider request 選出 1 個完整 genome | 不演化；只跑 generation 0 | 單獨量測 GPT 直接選 slot 的品質 |
| 2. Local evolution | 10 個 seeded local genomes | population 10，演化 100 代；seeds 8、9、10 | 純 local EA baseline |
| 3. GPT seed + local evolution | 第 0 個是方法 1 的 frozen GPT genome；第 1–9 個是與方法 2 相同的 local genomes | 與方法 2 完全相同的 local evolution；規劃 seeds 8、9、10 | 隔離「只加入一個 GPT 初始 seed」的影響 |

方法 3 不會再次呼叫 GPT。它將方法 1 已驗證的 24-slot genome 直接 frozen 在 config 內，因此方法 2 與方法 3 的刻意差異只有 generation 0 的 index 0。

## 執行完成度

| 方法 | Seed | Run | 狀態 |
| --- | ---: | --- | --- |
| 1 | 8 | `runs/20261030_120346_658325` | 完成 generation 0；600 場 fixed evaluation 也完成 |
| 2 | 8 | `runs/20261030_121958_452560` | 完成 generation 100 |
| 2 | 9 | `runs/20261031_052530_554403` | 完成 generation 100 |
| 2 | 10 | `runs/20261031_213830_001183` | 完成 generation 100 |
| 3 | 8 | `runs/20261101_211038_286628` | 完成 generation 100 |
| 3 | 9 | `runs/20261102_131719_965893` | 完成 generation 100 |
| 3 | 10 | `runs/20261103_043534_423377` | 完成 generation 100 |

所有已完成的 search generations 都沒有 evaluation failure。方法 2 與方法 3 各有 3,630 個 evaluated candidates、653,400 場 search matches；兩種演化方法合計完成 1,306,800 場 search matches。

## 方法 1：GPT 一次選 slot

方法 1 的唯一候選是 run-qualified candidate `runs/20261030_120346_658325:gen_0000_d1bf70074e31`。

- generation 0 search Game Performance：**-9.001**
- fixed evaluation：**600/600 場完成，0 errors**
- W/D/L：**265 / 10 / 325**
- 勝率：**44.17%**
- mean match score：**-9.505**

每個固定對手有 60 場（3 maps × 10 games × 2 sides）：

| 對手 | 勝 | 和 | 敗 | 勝率 |
| --- | ---: | ---: | ---: | ---: |
| PassiveAI | 50 | 10 | 0 | 83.3% |
| RandomAI | 60 | 0 | 0 | 100.0% |
| RandomBiasedAI | 60 | 0 | 0 | 100.0% |
| LightRush | 10 | 0 | 50 | 16.7% |
| HeavyRush | 30 | 0 | 30 | 50.0% |
| WorkerRush | 40 | 0 | 20 | 66.7% |
| AllInBot | 14 | 0 | 46 | 23.3% |
| Mayari | 1 | 0 | 59 | 1.7% |
| COAC | 0 | 0 | 60 | 0.0% |
| TMA | 0 | 0 | 60 | 0.0% |

解讀：GPT genome 能穩定擊敗三個簡單 baseline，對 HeavyRush/WorkerRush 有部分能力，但對 Mayari、COAC、TMA 幾乎沒有競爭力。因此方法 1 證明的是「GPT 能提供比隨機 local sample 更好的起點」，不是「一次 GPT 選擇已經得到完整強策略」。

## 方法 2：純 local evolution

以下 Game Performance 是各 run 當代 self-play context 的內部分數。因為 6 個動態 opponent slots 每 5 代更新，這些分數適合看單一 run 的收斂，不適合直接當作跨 run 的固定 benchmark。

| Seed | G0 best | G100 best | G100 population mean | G100 semantic unique | G100 mean pair distance |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 8 | -46.322 | 18.938 | 13.097 | 2/10 | 0.0222 |
| 9 | -57.007 | 28.432 | 27.400 | 1/10 | 0.0000 |
| 10 | -36.902 | 11.798 | 11.095 | 1/10 | 0.0000 |
| 平均 | -46.743 | 19.722 | 17.197 | 1.33/10 | 0.0074 |

三個 seeds 都從負的 generation 0 best 提升為正的 generation 100 best，表示 local evolution 在各自的 self-play context 中確實收斂並改善。不過 diversity collapse 很明顯：

- generation 0 三個 seeds 都是 10/10 unique，平均 pair distance 約 0.918；
- generation 100 平均只剩 1.33/10 unique，平均 pair distance 0.0074；
- seed 9 與 seed 10 的最終 10 個 survivors 在九個 semantic probes 上完全相同。

Generation 100 對四個永久固定對手的**族群平均**：

| Seed | AllInBot | Mayari | COAC | TMA |
| ---: | ---: | ---: | ---: | ---: |
| 8 | 13.725 | -36.131 | -98.064 | -71.458 |
| 9 | 16.534 | -65.229 | -83.220 | -67.108 |
| 10 | 26.244 | -100.925 | -102.205 | -102.164 |
| 平均 | 18.835 | -67.428 | -94.497 | -80.243 |

解讀：純 local evolution 可以改善內部 self-play objective，但跨 seed 差異大，而且對 COAC、TMA 等強固定對手的泛化仍弱。seed 10 尤其明顯：雖然內部 best 已變成正值，但對 Mayari、COAC、TMA 的族群平均仍接近全敗區間。

## 方法 3：GPT seed + local evolution

三個 seeds 都完成 100 代：

| Seed | G0 best | G100 best | G100 population mean | G100 semantic unique | G100 mean pair distance |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 8 | -10.649 | 38.828 | 36.207 | 2/10 | 0.0667 |
| 9 | -7.864 | 5.707 | 2.305 | 2/10 | 0.0444 |
| 10 | -8.472 | 23.818 | 21.943 | 1/10 | 0.0000 |
| 平均 | -8.995 | 22.784 | 20.152 | 1.67/10 | 0.0370 |

三個 seeds 的 generation 100 best 都高於自己的 generation 0 best，表示加入 GPT seed 後的 local evolution 仍有進一步改善，而不是只保留初始 GPT genome。

Generation 100 對四個永久固定對手的族群平均：

| Seed | AllInBot | Mayari | COAC | TMA |
| ---: | ---: | ---: | ---: | ---: |
| 8 | 56.154 | -13.563 | 26.695 | -66.938 |
| 9 | 72.717 | -86.554 | -51.707 | -102.048 |
| 10 | 66.583 | -78.096 | -35.657 | 0.532 |
| 平均 | 65.151 | -59.404 | -20.223 | -56.151 |

各 seed 最終 best candidate 對四個永久固定對手的 18-match 結果：

| Seed | Best candidate | AllInBot | Mayari | COAC | TMA |
| ---: | --- | --- | --- | --- | --- |
| 8 | `gen_0099_e9f0b7330367` | 67.792（15/0/3） | -21.600（6/2/10） | 23.898（11/0/7） | -66.906（3/0/15） |
| 9 | `gen_0096_34dd8f5a14b6` | 84.424（15/3/0） | -74.662（1/3/14） | -44.777（5/0/13） | -102.065（0/0/18） |
| 10 | `gen_0100_544b1d94ff1e` | 73.264（14/3/1） | -68.193（3/0/15） | -33.485（6/0/12） | 0.532（9/0/9） |

方法 3 對 AllInBot 的表現跨 seed 最穩定；對 Mayari、COAC、TMA 仍有明顯 seed variance。尤其 TMA 從 seed 9 的全敗到 seed 10 的 9 勝 9 敗，顯示不同演化 trajectory 會導向不同 matchup specialization。

方法 3 也出現 diversity collapse：generation 0 三個 seeds 都是 10/10 unique，平均 pair distance 約 0.927；generation 100 平均只剩 1.67/10 unique，平均 pair distance 0.0370。這比方法 2 的 1.33/10 與 0.0074 稍高，但仍不能視為保留了充分多樣性。

## 方法 2 與方法 3 的同 seed 對照

這是乾淨的 ablation：兩種方法使用相同 framework、相同 seed、相同 9 個 local genomes、相同演化設定，唯一差異是方法 3 用 GPT genome 替換 index 0。

### Generation 0 的直接初始化效果

| Seed | 方法 2 best | 方法 3 best | Best 差值 | 方法 2 mean | 方法 3 mean | Mean 差值 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 8 | -46.322 | -10.649 | **+35.673** | -68.829 | -62.628 | **+6.201** |
| 9 | -57.007 | -7.864 | **+49.143** | -71.660 | -65.442 | **+6.218** |
| 10 | -36.902 | -8.472 | **+28.429** | -67.632 | -61.116 | **+6.516** |
| 平均 | -46.743 | -8.995 | **+37.748** | -69.373 | -63.062 | **+6.311** |

GPT genome 在方法 3 的三個 seeds 都是 generation 0 全族群最佳候選。這是最一致的實驗結果：GPT seed 對初始 best 與 population mean 都有明確正效果。

### Generation 100

| 指標 | 方法 2 三-seed平均 | 方法 3 三-seed平均 | 差值 |
| --- | ---: | ---: | ---: |
| best self-play score | 19.722 | 22.784 | +3.062 |
| population mean | 17.197 | 20.152 | +2.955 |
| AllInBot population mean | 18.835 | 65.151 | **+46.317** |
| Mayari population mean | -67.428 | -59.404 | **+8.024** |
| COAC population mean | -94.497 | -20.223 | **+74.274** |
| TMA population mean | -80.243 | -56.151 | **+24.092** |
| semantic uniqueness ratio | 0.133 | 0.167 | +0.033 |
| mean pair distance | 0.0074 | 0.0370 | +0.0296 |

四個永久固定對手上的平均改善比 self-play aggregate 更具有跨 run 解讀價值。最明顯的是 COAC，三-seed族群平均由 -94.497 提升到 -20.223；AllInBot 也由 18.835 提升到 65.151。

效果並非每個 seed 都一致。相較方法 2 的同 seed 結果：

- seed 8：六個主要分數（best、population mean、四個固定對手）全部改善；
- seed 9：AllInBot、COAC 改善，但 best、population mean、Mayari、TMA 退步；
- seed 10：六個主要分數全部改善，TMA 族群平均由 -102.164 提升到 0.532。

因此，GPT seed 提升的是整體起點與平均結果，不保證每一條 stochastic evolution trajectory 都優於純 local evolution。Self-play best/mean 仍受各 run 動態 opponent context 影響，不能當作嚴格固定 benchmark。

## 結論與限制

目前最合理的結論是：

- **一次 GPT 選 slot 找到的 genome 在三個 seeds 都是 generation 0 最佳候選，初始化優勢高度一致。**
- **演化到 generation 100 後，方法 3 對四個永久固定對手的三-seed平均全部高於方法 2，尤其改善 COAC 與 AllInBot。**
- **GPT seed 不是穩定支配解：seed 9 的部分指標退步，顯示後續 local evolution 仍高度受 trajectory 影響。**
- **兩種 local evolution 方法都快速失去語意多樣性；GPT seed 只能稍微減緩，沒有解決 diversity collapse。**

目前不能做最終方法排名，原因如下：

1. self-play 的 6 個動態 opponent slots 每 5 代更新；不同 run 的 generation 100 aggregate score 不是完全相同的測量環境。
2. 方法 2 與方法 3 尚未完成 README 規劃的 generation 20、30、40、50、75、100 十對手 fixed evaluation。
3. 搜尋期間真正永久固定的只有 AllInBot、Mayari、COAC、TMA；若要比較 PassiveAI 到 TMA 的完整十對手收斂，必須另跑 fixed evaluation。

要完成正式結論，下一步應對方法 2/3 的六個完整 runs 使用相同 seed scheme 執行六個 checkpoints 的 fixed evaluation；共需 21,600 場額外 matches。

## Artifact 來源

- 實驗說明與 configs：[`README.md`](README.md)、[`01_gpt_framework_gpt_slot_once.yaml`](01_gpt_framework_gpt_slot_once.yaml)、[`02_gpt_framework_local_evolution.yaml`](02_gpt_framework_local_evolution.yaml)、[`03_gpt_framework_gpt_seed_local_evolution.yaml`](03_gpt_framework_gpt_seed_local_evolution.yaml)、[`03_gpt_framework_gpt_seed_local_evolution_seed10.yaml`](03_gpt_framework_gpt_seed_local_evolution_seed10.yaml)
- 方法 1 fixed evaluation：[`runs/20261030_120346_658325/fixed_evaluation/fixed_evaluation_summary.json`](../../../runs/20261030_120346_658325/fixed_evaluation/fixed_evaluation_summary.json)
- 方法 2 summaries：[`seed 8`](../../../runs/20261030_121958_452560/summary.json)、[`seed 9`](../../../runs/20261031_052530_554403/summary.json)、[`seed 10`](../../../runs/20261031_213830_001183/summary.json)
- 方法 3 summaries：[`seed 8`](../../../runs/20261101_211038_286628/summary.json)、[`seed 9`](../../../runs/20261102_131719_965893/summary.json)、[`seed 10`](../../../runs/20261103_043534_423377/summary.json)
