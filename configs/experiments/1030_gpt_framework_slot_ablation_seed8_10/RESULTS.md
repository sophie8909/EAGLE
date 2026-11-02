# GPT framework slot-selection ablation：三種方法與目前結果

更新日期：2026-11-02（Asia/Taipei）

## 摘要

這組 ablation 要回答的問題是：**在完全相同的 GPT 設計 framework 下，只改變 generation 0 的 slot genome 初始化方式，是否會影響起始品質與後續 local evolution？**

目前結果顯示：

1. **方法 1（GPT 一次選 slot）**產生的單一 genome 在 generation 0 明顯優於同 seed 的純 local 初始候選，但對高強度對手仍不夠穩定。其完整固定評估為 265 勝、10 和、325 敗，勝率 44.17%，平均 match score 為 -9.505。
2. **方法 2（純 local evolution）**的 seed 8、9、10 都完成 100 代，三組內部 self-play 最佳分數都由負值提升為正值；但族群語意多樣性由 generation 0 的 100% 降到 generation 100 平均 13.3%。
3. **方法 3（GPT seed + local evolution）**目前只有 seed 8 完成。與方法 2 的 seed 8 相比，它只替換 generation 0 的第 0 個 genome，其餘 9 個 local genomes 相同；替換後 generation 0 最佳分數由 -46.322 提升到 -10.649，generation 100 對四個永久固定對手的族群平均分數也全部較高。
4. 目前只能說 **GPT seed 在 seed 8 上提供了明顯而且持續到 generation 100 的優勢**。由於方法 3 的 seed 9 未完成、seed 10 尚未執行，而且方法 2/3 尚未跑相同 checkpoints 的十對手 fixed evaluation，現在還不能做跨 seed 的最終方法排名。

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
| 3 | 9 | `runs/20261102_131719_965893` | 未完成；manifest 仍為 `running`，但記錄的 PID 已不存在，latest generation 為 0 |
| 3 | 10 | — | 尚未找到 run artifact |

所有已完成的 search generations 都沒有 evaluation failure。方法 2 三個 seeds 合計完成 653,400 場 search matches。

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

目前唯一完整資料是 seed 8：

| 指標 | Generation 0 | Generation 100 |
| --- | ---: | ---: |
| best self-play Game Performance | -10.649 | 38.828 |
| population mean | -62.628 | 36.207 |
| semantic unique | 10/10 | 2/10 |
| mean pair distance | 0.9210 | 0.0667 |

Generation 100 對四個永久固定對手的族群平均：

| AllInBot | Mayari | COAC | TMA |
| ---: | ---: | ---: | ---: |
| 56.154 | -13.563 | 26.695 | -66.938 |

最終 best candidate `runs/20261101_211038_286628:gen_0099_e9f0b7330367` 對這四個對手的 18-match 結果為：

| 對手 | Score | W/D/L |
| --- | ---: | ---: |
| AllInBot | 67.792 | 15/0/3 |
| Mayari | -21.600 | 6/2/10 |
| COAC | 23.898 | 11/0/7 |
| TMA | -66.906 | 3/0/15 |

方法 3 仍然出現 diversity collapse，但 seed 8 的最終 mean pair distance 0.0667 高於方法 2 seed 8 的 0.0222。

## 方法 2 與方法 3 的同 seed 8 對照

這是目前最乾淨的 ablation：兩者使用相同 framework、相同 seed、相同 9 個 local genomes、相同演化設定，唯一差異是方法 3 用 GPT genome 替換 index 0。

### Generation 0 的直接初始化效果

| 指標 | 方法 2：純 local | 方法 3：GPT seed | 差值 |
| --- | ---: | ---: | ---: |
| best Game Performance | -46.322 | -10.649 | **+35.673** |
| population mean | -68.829 | -62.628 | **+6.201** |

GPT genome 在方法 3 的 generation 0 是全族群最佳候選，因此這裡可以直接確認 GPT seed 提供了更強的起點。

### Generation 100

| 指標 | 方法 2：純 local | 方法 3：GPT seed | 差值 |
| --- | ---: | ---: | ---: |
| best self-play score | 18.938 | 38.828 | +19.890 |
| population mean | 13.097 | 36.207 | +23.111 |
| AllInBot population mean | 13.725 | 56.154 | **+42.429** |
| Mayari population mean | -36.131 | -13.563 | **+22.567** |
| COAC population mean | -98.064 | 26.695 | **+124.760** |
| TMA population mean | -71.458 | -66.938 | **+4.521** |

四個永久固定對手上的改善比 self-play aggregate 更具有跨 run 解讀價值。最明顯的是 COAC：方法 2 seed 8 的族群平均為 -98.064，方法 3 seed 8 則為 +26.695。

不過，方法 3 目前只有一個完整 seed，因此這個結果可能仍包含 seed-specific trajectory；還不能斷言 GPT seed 在 seeds 9、10 也會產生相同幅度的提升。

## 結論與限制

目前最合理的結論是：

- **一次 GPT 選 slot 確實找到比同 seed local initialization 更強的 genome。**
- **在 seed 8 中，將這個 genome 放入初始族群的優勢不只出現在 generation 0，也延續到 generation 100，尤其改善了對 COAC 與 AllInBot 的表現。**
- **純 local evolution 本身可以提升 search objective，但三個 seeds 都快速失去語意多樣性，且對強固定對手的泛化不穩定。**

目前不能做最終方法排名，原因如下：

1. 方法 3 的 seed 9、10 尚未形成與方法 2 對稱的三個 seed 結果。
2. self-play 的 6 個動態 opponent slots 每 5 代更新；不同 run 的 generation 100 aggregate score 不是完全相同的測量環境。
3. 方法 2 與方法 3 尚未完成 README 規劃的 generation 20、30、40、50、75、100 十對手 fixed evaluation。
4. 搜尋期間真正永久固定的只有 AllInBot、Mayari、COAC、TMA；若要比較 PassiveAI 到 TMA 的完整十對手收斂，必須另跑 fixed evaluation。

要完成正式結論，下一步應先恢復或重跑方法 3 的 seeds 9、10，再對方法 2/3 的每個完整 run 使用相同 seed scheme 執行六個 checkpoints 的 fixed evaluation。

## Artifact 來源

- 實驗說明與 configs：[`README.md`](README.md)、[`01_gpt_framework_gpt_slot_once.yaml`](01_gpt_framework_gpt_slot_once.yaml)、[`02_gpt_framework_local_evolution.yaml`](02_gpt_framework_local_evolution.yaml)、[`03_gpt_framework_gpt_seed_local_evolution.yaml`](03_gpt_framework_gpt_seed_local_evolution.yaml)、[`03_gpt_framework_gpt_seed_local_evolution_seed10.yaml`](03_gpt_framework_gpt_seed_local_evolution_seed10.yaml)
- 方法 1 fixed evaluation：[`runs/20261030_120346_658325/fixed_evaluation/fixed_evaluation_summary.json`](../../../runs/20261030_120346_658325/fixed_evaluation/fixed_evaluation_summary.json)
- 方法 2 summaries：[`seed 8`](../../../runs/20261030_121958_452560/summary.json)、[`seed 9`](../../../runs/20261031_052530_554403/summary.json)、[`seed 10`](../../../runs/20261031_213830_001183/summary.json)
- 方法 3 seed 8 summary：[`runs/20261101_211038_286628/summary.json`](../../../runs/20261101_211038_286628/summary.json)
- 方法 3 seed 9 manifest：[`runs/20261102_131719_965893/manifest.json`](../../../runs/20261102_131719_965893/manifest.json)
