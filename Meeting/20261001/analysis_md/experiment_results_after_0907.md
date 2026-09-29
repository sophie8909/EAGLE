# EAGLE 0907 後實驗結果分析

## 分析範圍

本文接續 [`version_summary_after_0907.md`](version_summary_after_0907.md)，分析 2026-09-08 起建立或執行的四個實驗 run。所有數字均直接讀取本機 `eagle-run-v2` artifacts；generation 指標以該代 survivor population snapshot 為準，candidate 的建立代數則由 `birth_generation`／candidate state 另行判讀。

Game Performance（GP）是加權報告指標，不是 lexicase selection objective。數值越高越好；因此本文可用 GP 描述整體趨勢，但不把它當成演化選擇必須單調上升的目標。

## 實驗狀態總覽

| 實驗 | Run | 模型配置 | 狀態 | 可分析範圍 |
| --- | --- | --- | --- | --- |
| Code assessment 5×3 | `20260908_084706_819288` | Ministral 3 8B | 完成 | generation 0–5 |
| Code assessment 20×10 | `20260908_101749_429776` | Ministral 3 8B | 中斷、不可續跑 | 尚無 atomic generation |
| Staged materialization 20×10 | `20260908_121222_306081` | Ministral reflection → Ministral generation | search 完成 | generation 0–20 |
| Staged materialization 20×10 | `20260909_032729_611766` | Ministral reflection → Qwen 3.5 9B generation | 中斷、可續跑 | atomic generation 0–10；另有未完成 generation 11 artifacts |

前兩個 run 由 assessment indexes 登錄；後兩個 run 由 `configs/experiments/0908_generation_model_comparison_20x10/experiment.yaml` 指向。這些 indexes 已納入 Git，但 raw run directories 並未提交；因此本文保留 run ID 以便在本機追查，單獨 clone repository 仍無法重建所有原始證據。

四個 run 都沒有 `final_test/` 結果。本文分析的是 evolutionary search 內部評估，不是獨立 holdout/final-test 結果。

## 主要結論

1. Ministral-only staged run 有明確且大幅的演化進展：survivor population 的平均 GP 從 generation 0 的 `-90.540` 提升到 generation 20 的 `-58.991`；全程最佳 candidate 達 `-47.518`、73 勝 7 和 100 敗。
2. 進展主要集中在 PassiveAI、RandomAI、RandomBiasedAI、LightRush 與 HeavyRush；TMA 沒有改善，仍是最明顯的共同弱點。
3. Ministral→Qwen run 到 generation 10 僅從平均 `-90.445` 提升至 `-88.873`。同一 generation-10 截面下，Ministral-only 的平均 GP 高 `29.478` 分，最佳 GP 高 `35.482` 分。
4. 目前不能把差距直接解釋成模型的因果優劣：兩個 run 的 LLM sampling 與 MicroRTS matches 都不是完全 deterministic，Qwen run 也尚未完成 20 代且沒有 final test。
5. 兩個 staged run 的所有 atomic survivor snapshots 都是 10/10 evaluated、1,800/1,800 matches complete；失敗集中在未被選入 survivor population 的 offspring。這表示搜尋流程可持續運作，但 generation/validation/compilation/runtime robustness 仍會消耗樣本。

## 5×3 Code Reflection assessment

Run：`runs/20260908_084706_819288`

### 完整性

- manifest：`complete`，完成 generation 5。
- 18 個 unique candidates，其中 15 個 evaluated、3 個在 validation 失敗。
- 2,700 份 canonical match results。
- 118 次 LLM requests；從第一個到最後一個 timing event 約 80 分 49 秒。
- 此 run 建立於 generation-wide materialization 改版之前，Code Reflection artifacts 使用 `eagle-code-reflection-v3`，不能直接當作 v4 staged pipeline 的驗證結果。

### GP 趨勢

| Generation | Survivor 最佳 GP | Survivor 平均 GP | Survivor 最差 GP |
| ---: | ---: | ---: | ---: |
| 0 | -90.504 | -90.738 | -90.948 |
| 1 | -90.444 | -90.640 | -90.948 |
| 2 | -89.961 | -90.406 | -90.728 |
| 3 | -89.961 | -90.250 | -90.516 |
| 4 | **-88.871** | **-89.886** | -90.516 |
| 5 | -90.272 | -90.359 | -90.516 |

最佳結果出現在 generation 4 的 Prompt Reflection candidate `gen_0004_cb2aad32e699`：GP `-88.871`，2 勝 50 和 128 敗。它相對 generation 0 最佳值改善 `1.633`，但沒有被保留到 generation 5。這並非資料矛盾：lexicase 依十個 opponent cases 選擇，aggregate GP 只負責報告。

### Operator 結果

- 實際 assignments：Strategy 4、Prompt 5、Code 6，符合小樣本下的 0.33 / 0.33 / 0.34 靜態抽樣。
- 5 個 Prompt Reflection 全部完成 mutation 並成功評估；其中 generation 4 產生本 run 的最佳 GP。
- 4 個 Strategy Reflection 中 2 個實際套用，另 2 個保留原 component；已套用的 candidates 都成功評估。
- 6 個 Code Reflection 中，3 個 candidates 成功評估、3 個在 validation 失敗。另有 1 次 diagnosis semantic failure，以及 1 次 revision 三次皆未產出合規完整 Java；兩者都保留原 Java 後完成評估。
- 三個 validation failures 均耗盡 5 次 Java generation/repair attempts，顯示 v3 Code Reflection 的修訂輸出與後續 repair chain 是此小型 run 的主要穩定性風險。

### 判讀

5×3 run 證明三種 operator 能在完整五代流程中共同運作，但樣本只有 15 個 offspring，且 Code Reflection 的 3/6 terminal failure rate 太高。它適合作為 pipeline assessment，不足以估計 operator 的一般化勝率或優劣。

## 20×10 Code Reflection assessment

Run：`runs/20260908_101749_429776`

- manifest：`interrupted`，`latest_generation: null`，`resumable: false`。
- 已建立 10 個 generation-zero candidate directories，並完成 9 次 `initial_policy_generation` LLM requests。
- 其中 9 個 candidates 已各自留下完整的 180-match evaluation；第 10 個 `gen_0000_0acf76bf48ab` 只有 7 場 partial matches，尚無 candidate/evaluation summary。
- 九個完整 partial candidates 的 provisional 平均 GP 是 `-90.616`；provisional 最佳為 `gen_0000_68506c8b76b3`，GP `-90.065`。
- 沒有 `generation_0000.json` 或 run `summary.json`。

因此這些數字只能標為 partial/provisional，不能稱為 survivor population、run best 或正式 generation-0 結果，也不能和 5×3 或 staged 20×10 run 做正式效能比較。這個區分遵守 `eagle-run-v2` 的 atomic-generation boundary：candidate 層 partial artifacts 是 audit evidence，不是已提交的 population snapshot。

## Ministral-only staged materialization 20×10

Run：`runs/20260908_121222_306081`

### 完整性與成本

- manifest：`complete`，完成 generation 20；共 210 個 candidates。
- 21 個 atomic generation snapshots 都有 10 個 evaluated survivors，且每代 snapshot 記錄 1,800/1,800 completed matches。
- 搜尋 timing 約 15 小時 15 分；記錄 1,630 次 LLM requests，request durations 合計約 10 小時 49 分。
- 沒有 final test，因此 `complete` 應解讀為 search 完成，而不是已有獨立測試集驗證。

### 演化趨勢

| Generation | Survivor 最佳 GP | Survivor 平均 GP | Survivor 最差 GP | 平均 Code Quality |
| ---: | ---: | ---: | ---: | ---: |
| 0 | -89.831 | -90.540 | -91.204 | 49.706 |
| 1 | -85.072 | -89.771 | -90.862 | 41.798 |
| 2 | -79.365 | -85.910 | -90.172 | 29.308 |
| 5 | -65.579 | -77.863 | -89.005 | 30.125 |
| 8 | -48.578 | -62.618 | -88.993 | 34.757 |
| 10 | -50.320 | -59.395 | -85.469 | 33.849 |
| 14 | -48.004 | **-53.760** | -66.138 | 29.021 |
| 20 | **-47.518** | -58.991 | -88.999 | 24.939 |

搜尋在前八代快速改善，generation 8 之後進入約 `-48` 至 `-50` 的最佳值平台。Population 平均值在 generation 14 最好，之後回落；同時 generation 20 仍找到新的全程最佳 candidate。這反映 opponent-wise lexicase 持續保留不同 case specialists，而非只最大化 aggregate GP。

Code Quality 平均值從 `49.706` 降至 `24.939`，與 GP 改善方向相反。Code Quality 只是 diagnostic，不參與 selection；目前結果顯示較強遊戲表現伴隨更高的程式複雜度，後續若重視 maintainability，需要另設約束或分析，而不能期待 lexicase 自動保留高品質程式。

### Opponent-wise 變化

| Opponent | Gen 0 平均 | Gen 20 平均 | 變化 |
| --- | ---: | ---: | ---: |
| PassiveAI | 3.399 | 93.278 | **+89.879** |
| RandomAI | -1.599 | 78.533 | **+80.131** |
| RandomBiasedAI | -38.189 | 30.302 | **+68.491** |
| LightRush | -100.842 | -32.491 | **+68.351** |
| HeavyRush | -101.096 | -18.244 | **+82.852** |
| WorkerRush | -100.251 | -77.771 | +22.479 |
| AllInBot | -99.707 | -76.144 | +23.562 |
| Mayari | -102.481 | -94.786 | +7.694 |
| COAC | -102.314 | -81.755 | +20.560 |
| TMA | -101.180 | -102.283 | **-1.103** |

進展不是均勻的。前三個 baseline opponents 與 Light/Heavy Rush 改善最大；Mayari 改善有限，TMA 甚至略退。若下一輪實驗目的是提升泛化，TMA、Mayari 與玩家側別不對稱應是優先診斷對象。

### 全程最佳 candidate

`gen_0020_f5bea1248ef6` 是 generation 20 的 Code Reflection candidate：

- GP：`-47.518`；73 勝、7 和、100 敗，win rate 40.56%。
- 對 PassiveAI、RandomAI：18/18 全勝。
- 對 RandomBiasedAI：13 勝、4 和、1 敗。
- 對 LightRush、HeavyRush：各 6 勝。
- 對 WorkerRush、AllInBot、Mayari、COAC：各 3 勝。
- 對 TMA：0 勝、0 和、18 敗。
- Code Quality：`34.066`；cyclomatic complexity 90、最大 nesting 5、logical LOC 151。
- Code Reflection v4 diagnosis 成功，revision 在第 2 次 attempt 成功，`java_changed: true`。
- 其 evidence parent `gen_0019_c925d51aaffa` 的 GP 為 `-48.660`，此 child 高 `1.142` 分；由於 matches 非 deterministic，這是觀察到的差值，不是單次 mutation 的無偏因果估計。

這個 candidate 有明顯 side asymmetry。例如對 HeavyRush 的 p0/p1 平均分為 `-32.318 / 1.658`，WorkerRush 為 `-102.931 / -33.825`，Mayari 則為 `-34.177 / -103.982`。Aggregate 改善掩蓋了依對手與玩家側別而異的策略脆弱性。

### Operator 與失敗分布

200 個 offspring assignments 為 Strategy 70、Prompt 72、Code 58，接近靜態設定比例。Terminal candidate failures 共 17 個：

| Operator assignment | 失敗 / 總數 | Failure stages |
| --- | ---: | --- |
| Strategy | 2 / 70（2.9%） | compilation 1、runtime 1 |
| Prompt | 6 / 72（8.3%） | compilation 3、validation 2、runtime 1 |
| Code | 9 / 58（15.5%） | compilation 4、validation 4、runtime 1 |

Code assignment 的 terminal failure rate 最高。另一方面，最後 population 中 6/10 candidates 來自 Code Reflection，且全程最佳也是 Code candidate。這表示 Code Reflection 呈現「高風險、高上限」特徵：產生較多無法進入 survivor pool 的失敗，也產生最強的保留個體。

逐 child 對 mutation-evidence parent 的 GP 差值多數為負；但這些 comparisons 同時受 crossover、其他 component provenance 與非 deterministic matches 影響，不能當作純 operator effect。較可信的結論是 selection 從大量多數退步的 offspring 中保留少數 case-wise improvements，累積成整體 population 進展。

## Ministral→Qwen staged materialization 20×10

Run：`runs/20260909_032729_611766`

### 完整性

- manifest：`interrupted`、`resumable: true`，最新 atomic generation 為 10。
- generation 0–10 都有 10 個 evaluated survivors 與 1,800/1,800 completed matches。
- generation 11 已有 partial candidate/timing artifacts，但依 schema 不納入結果分析。
- 到 generation 10 的搜尋 timing 約 9 小時 4 分。

### 趨勢

| Generation | Survivor 最佳 GP | Survivor 平均 GP | Survivor 最差 GP | 平均 Code Quality |
| ---: | ---: | ---: | ---: | ---: |
| 0 | -89.838 | -90.445 | -91.181 | 49.706 |
| 2 | -89.534 | -89.933 | -90.699 | 29.555 |
| 5 | -86.686 | -89.305 | -89.915 | 16.113 |
| 8 | **-85.802** | -88.867 | -90.199 | 18.776 |
| 10 | **-85.802** | **-88.873** | -90.194 | 18.669 |

到 generation 10 為止，平均 GP 只改善 `1.572`，最佳 GP 改善 `4.036`。改善主要來自 RandomBiasedAI（平均 `+13.741`）、WorkerRush（`+6.482`）與 RandomAI（`+5.314`）；rush/advanced opponents 的大部分分數仍接近約 `-100`。

全程最佳 `gen_0008_867a2025b1eb` 的 GP 為 `-85.802`，5 勝、53 和、122 敗。它被記為成功 Code Reflection，但 parent 與 child Java SHA-256 相同、`java_changed: false`；因此它相對 evidence parent 的小幅 GP 改善不能歸因於 Qwen 實際修改了 Java。

## 同代模型比較：generation 10

這是目前最可比的截面，但仍不是 deterministic paired trial。

| 指標 | Ministral→Ministral | Ministral→Qwen | 差值（前者－後者） |
| --- | ---: | ---: | ---: |
| Survivor 最佳 GP | -50.320 | -85.802 | **+35.482** |
| Survivor 平均 GP | -59.395 | -88.873 | **+29.478** |
| Survivor 最差 GP | -85.469 | -90.194 | +4.725 |
| 最佳 Code Quality | 37.122 | 27.735 | +9.387 |
| 平均 Code Quality | 33.849 | 18.669 | +15.180 |
| 全程最佳 candidate W/D/L | 69 / 11 / 100 | 5 / 53 / 122 | — |

Opponent-wise generation-10 survivor mean 中，Ministral-only 在 9/10 cases 較高：Passive `+98.685`、HeavyRush `+79.687`、Random `+77.740`、LightRush `+69.073`、RandomBiased `+33.711`、COAC `+23.133`、AllInBot `+19.999`、Mayari `+12.874`、WorkerRush `+5.515`。只有 TMA 是 Qwen run 高 `1.440`。

Timing 顯示 Ministral-only 到 generation 10 約 7 小時 27 分，Qwen run 約 9 小時 4 分。Qwen run 的 LLM request duration 合計反而較短，但 evaluation duration 約 4 小時 34 分，明顯高於 Ministral-only 的約 2 小時 28 分；目前觀察到的總時間差主要落在 MicroRTS evaluation，而不是 LLM request 本身。這不排除 model switching overhead，也不能單憑 timing 判定模型效率。

## 限制與下一步

- 每個模型配置目前只有一個 run，沒有 replicate 或 confidence interval。
- LLM sampling 不 deterministic；MicroRTS matches 也未使用有效 match seed，因此小幅差值可能來自抽樣波動。
- Qwen run 尚未完成 20 代，generation 11 partial artifacts 不能作為 population 結果。
- 所有 run 都缺少 final test；search population 表現可能高估對同一 evaluation matrix 的泛化能力。
- Aggregate GP 不是 selection objective，應搭配十個 opponent cases、W/D/L 與 side-specific scores 解讀。

建議優先順序：

1. 從 atomic generation 10 續跑 Qwen run 到 generation 20，保留既有 run ID 與 resume contract。
2. 對兩個完成的 20×10 run 執行同一版 final test，再比較 holdout 結果。
3. 至少各增加 3 個獨立 replicates，報告 generation-10／20 的 mean、standard deviation 與 confidence interval。
4. 針對 TMA、Mayari 與 side asymmetry 建立 opponent/map/side 分解；不要只看 aggregate GP。
5. 對 Code Reflection 的 validation/compilation failures 做分類，優先降低其 10–16% terminal failure rate，再評估高上限是否能以更低成本保留。

## 查核來源

- `runs/<run_id>/manifest.json`：run 狀態與最新 atomic generation。
- `runs/<run_id>/summary.json`：完成 run 的 final population references。
- `runs/<run_id>/generations/generation_*.json`：survivor snapshot、十個 objectives、GP、Code Quality 與 match completeness。
- `runs/<run_id>/candidates/<id>/candidate.json`：candidate identity、birth generation、lineage、operator 與 failure stage。
- `runs/<run_id>/candidates/<id>/evaluation/game_performance.json`：W/D/L、opponent/map/side scores。
- `runs/<run_id>/candidates/<id>/evaluation/code_quality.json`：complexity diagnostics。
- `runs/<run_id>/timing.jsonl`：generation 與 LLM request timing。
