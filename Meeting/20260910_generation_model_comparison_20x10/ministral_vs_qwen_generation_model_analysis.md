# 20×10 生成模型比較實驗完整分析

分析日期：2026-09-10

比較條件：純 Ministral 3 8B vs. Ministral 反思 + Qwen3.5 9B 最終 Java 生成

實驗規模：20 代 × 每代 10 個 offspring；族群大小 10

## 一、結論摘要

這次兩項實驗的端到端結果很清楚：**純 Ministral 版本目前較適合作為正式演化流程**。它不只在最終族群的 aggregate game performance 大幅領先，也真正把策略轉成能贏比賽的 Java。雙模型版本的 Qwen3.5 9B 則有較高的生成、驗證與編譯成功率，也保留較多策略 niche，但這些優勢沒有轉成遊戲表現。

最重要的結果如下：

- 最終最佳 game performance：純 Ministral `-47.52`，雙模型 `-81.91`；純 Ministral 領先 `34.39` 分。
- 最終族群平均 game performance：純 Ministral `-58.99`，雙模型 `-87.62`；純 Ministral 領先 `28.63` 分。
- 最終 1,800 場族群對戰：純 Ministral `542 勝 / 202 和 / 1,056 敗`；雙模型只有 `5 勝 / 511 和 / 1,284 敗`。
- Java 生成成功率：純 Ministral `186/200 = 93.0%`，雙模型 `195/200 = 97.5%`；雙模型較穩定。
- 第一次生成即成功：純 Ministral `140/200 = 70.0%`，雙模型 `183/200 = 91.5%`。
- 最終策略 niche：純 Ministral 2 種，雙模型 4 種；但最終 Java hash 數為純 Ministral 10 種、雙模型只有 5 種。
- 最終族群 strategy-alignment 診斷平均：純 Ministral `6.2/10`，雙模型 `2.0/10`。
- Qwen 的 generation LLM 階段比較快，但雙模型個體更常把比賽拖長或拖成和局，導致整體演化反而較慢。

不過，**這不是嚴格控制的模型因果 A/B test**：兩次實驗分別用 LLM 重新產生初始 policy，10 個初始 policy 中只有 1 個 hash 相同。因此本報告能確定「這兩次完整流程的結果差很多」，但不能只用這一組實驗斷言差異全部由 Qwen3.5 9B 造成。

## 二、實驗與資料來源

### 2.1 Run

| 條件 | Run | 反思／分析模型 | 最終 Java 生成模型 | 狀態 |
|---|---|---|---|---|
| 純 Ministral | [`20260908_121222_306081`](../../runs/20260908_121222_306081/) | `ministral3_8b` | `ministral3_8b` | complete，20 代 |
| 雙模型 | [`20260909_032729_611766`](../../runs/20260909_032729_611766/) | `ministral3_8b` | `qwen3_5_9b` | complete，20 代；中途曾中斷並 resume |

對應 config：

- [`01_ministral3_8b_only_20x10.yaml`](../../configs/experiments/0908_generation_model_comparison_20x10/01_ministral3_8b_only_20x10.yaml)
- [`02_ministral3_8b_to_qwen3_5_9b_20x10.yaml`](../../configs/experiments/0908_generation_model_comparison_20x10/02_ministral3_8b_to_qwen3_5_9b_20x10.yaml)
- [`experiment.yaml`](../../configs/experiments/0908_generation_model_comparison_20x10/experiment.yaml)

### 2.2 共同設定

| 項目 | 設定 |
|---|---|
| survivor selection | `mu_plus_lambda` + opponent-wise lexicase |
| generations / population | 20 / 10 |
| crossover / mutation rate | 0.75 / 1.0 |
| mutation probabilities | Strategy 0.33、Prompt 0.33、Code 0.34 |
| random seed | 7 |
| candidate Java mode | `inherited_genotype` |
| initial population | 1 個 WorkerRush seed + 9 個 LLM-generated policy |
| maps | 8×8、16×16、24×24 |
| 每個對手的場數 | 3 maps × 3 rounds × 2 sides = 18 |
| opponents | Passive、Random、RandomBiased、LightRush、HeavyRush、WorkerRush、AllInBot、Mayari、COAC、TMA |
| 每個完整候選人的總場數 | 10 opponents × 18 = 180 |
| 一個 10 人族群的總場數 | 1,800 |

aggregate game performance 是依對手權重計算的報告指標，權重總和為 12.5；實際 survivor selection 使用 10 個 opponent cases 做 lexicase，**不是直接最大化 aggregate game performance**。因此某一代的 aggregate 最佳值或平均值下降，不等於父代一定被錯誤重生，也不必然代表 selection bug。

### 2.3 比較有效性限制

兩份 config 的主要實驗變因確實是最終 Java generation model，但仍有以下限制：

1. 兩次實驗都獨立執行 `llm_generated_policies`。兩邊各有 10 個不同的初始 policy hash，交集只有 1 個，也就是共同 seed；其餘 9 個 LLM policy 並未配對。
2. 兩邊 generation 0 的 Java 都只有 1 個唯一 hash，仍是相同 WorkerRush Java seed，所以 generation 0 表現接近；policy 的差異要等後續 materialization 才會顯現。
3. 每個條件只跑 1 次，沒有跨 seed 估計變異。
4. 雙模型 run 曾中斷並 resume。功能結果完整，但 wall-clock 不適合直接與未中斷 run 比較；本報告採 committed generation timing 加總。
5. 沒有額外獨立 holdout 對手／地圖結果；最終結果仍來自演化期間使用的固定 evaluation matrix。

因此，以下模型比較應解讀為**兩個完整 pipeline instance 的觀察性比較**，而不是已排除所有混淆因子的模型能力定論。

## 三、最終結果總覽

| 指標 | 純 Ministral | 雙模型 | 判讀 |
|---|---:|---:|---|
| final best GP | -47.52 | -81.91 | 純 Ministral +34.39 |
| final mean GP | -58.99 | -87.62 | 純 Ministral +28.63 |
| final median GP | -53.61 | -87.61 | 純 Ministral +34.00 |
| final worst GP | -89.00 | -90.36 | 純 Ministral +1.36 |
| gen0 → final mean GP | +31.55 | +2.83 | 純 Ministral 有實質演化；雙模型改善有限 |
| final mean code quality | 24.94 | 23.69 | 純 Ministral +1.25 |
| final mean strategy alignment | 6.2/10 | 2.0/10 | 純 Ministral 明顯較忠實 |
| final function score mean | 100.0 | 96.0 | 兩者大多具備基本功能 |
| final unique strategy niches | 2 | 4 | 雙模型策略描述較多樣 |
| final unique policy hashes | 3 | 4 | 雙模型略多 |
| final unique Java hashes | 10 | 5 | 純 Ministral 實作較多樣 |
| final completed matches | 1,800/1,800 | 1,800/1,800 | 兩者最終族群皆完整 |
| final failures | 0 | 0 | survivor 皆可執行 |

純 Ministral 的 mean GP 在 generation 14 達到本 run 最佳平均 `-53.76`，之後回落到 `-58.99`；但 best GP 最終仍進步到 `-47.52`。雙模型的 mean GP 在 generation 19 達到 `-84.85`，generation 20 回落到 `-87.62`；best GP 的 run 內最高點為 generation 12–15 的 `-81.58`，final best 為 `-81.91`。這種回落與 opponent-wise lexicase 的多目標保留行為一致。

## 四、完整逐代變化

### 4.1 純 Ministral

| Gen | GP best | GP mean | CQ mean | niches | 時間（min） |
|---:|---:|---:|---:|---:|---:|
| 0 | -89.83 | -90.54 | 49.71 | 0 | 17.9 |
| 1 | -85.07 | -89.77 | 41.80 | 2 | 41.2 |
| 2 | -79.37 | -85.91 | 29.31 | 1 | 50.1 |
| 3 | -79.37 | -86.90 | 27.73 | 3 | 55.3 |
| 4 | -70.57 | -84.78 | 28.45 | 3 | 50.5 |
| 5 | -65.58 | -77.86 | 30.12 | 1 | 28.3 |
| 6 | -57.06 | -73.35 | 33.83 | 4 | 47.8 |
| 7 | -49.41 | -71.23 | 35.08 | 4 | 37.1 |
| 8 | -48.58 | -62.62 | 34.76 | 3 | 37.2 |
| 9 | -48.58 | -63.23 | 35.14 | 3 | 38.5 |
| 10 | -50.32 | -59.39 | 33.85 | 4 | 42.9 |
| 11 | -48.73 | -56.77 | 31.61 | 3 | 54.4 |
| 12 | -48.73 | -55.21 | 30.52 | 2 | 45.1 |
| 13 | -49.11 | -54.86 | 30.33 | 2 | 45.8 |
| 14 | -48.00 | -53.76 | 29.02 | 1 | 43.8 |
| 15 | -48.00 | -54.58 | 25.24 | 1 | 42.1 |
| 16 | -48.99 | -56.50 | 23.53 | 2 | 47.7 |
| 17 | -49.24 | -56.41 | 26.54 | 3 | 53.4 |
| 18 | -49.24 | -57.68 | 24.26 | 3 | 36.4 |
| 19 | -48.66 | -57.98 | 22.55 | 3 | 44.4 |
| 20 | -47.52 | -58.99 | 24.94 | 2 | 55.2 |

觀察：generation 1–8 是主要躍升期，平均 GP 從 `-90.54` 改善到 `-62.62`；generation 10–14 進一步收斂到約 `-54`。後六代平均值回落，但保留了少數更強個體。Code quality 從相同 WorkerRush seed 的 `49.71` 降到 `24.94`，顯示演化取得戰力時增加了實作複雜度或降低了對齊度。

### 4.2 Ministral → Qwen3.5 9B

| Gen | GP best | GP mean | CQ mean | niches | 時間（min） |
|---:|---:|---:|---:|---:|---:|
| 0 | -89.84 | -90.44 | 49.71 | 0 | 17.9 |
| 1 | -89.84 | -90.45 | 40.48 | 0 | 39.6 |
| 2 | -89.53 | -89.93 | 29.56 | 0 | 52.5 |
| 3 | -89.53 | -89.83 | 15.55 | 0 | 73.6 |
| 4 | -89.34 | -89.69 | 14.82 | 1 | 68.5 |
| 5 | -86.69 | -89.31 | 16.11 | 1 | 41.1 |
| 6 | -86.46 | -88.63 | 19.97 | 4 | 58.7 |
| 7 | -86.46 | -89.15 | 17.48 | 2 | 44.6 |
| 8 | -85.80 | -88.87 | 18.78 | 4 | 51.1 |
| 9 | -85.80 | -89.09 | 17.48 | 2 | 42.0 |
| 10 | -85.80 | -88.87 | 18.67 | 5 | 54.3 |
| 11 | -82.29 | -87.32 | 23.28 | 4 | 53.9 |
| 12 | -81.58 | -85.48 | 24.70 | 2 | 45.6 |
| 13 | -81.58 | -86.85 | 22.42 | 3 | 43.0 |
| 14 | -81.58 | -85.00 | 25.07 | 4 | 45.3 |
| 15 | -81.58 | -85.75 | 25.58 | 5 | 37.9 |
| 16 | -82.47 | -87.46 | 24.15 | 4 | 38.5 |
| 17 | -82.04 | -87.00 | 24.11 | 5 | 43.0 |
| 18 | -82.04 | -86.63 | 24.34 | 3 | 33.7 |
| 19 | -81.91 | -84.85 | 24.17 | 4 | 33.0 |
| 20 | -81.91 | -87.62 | 23.69 | 4 | 34.0 |

觀察：前 10 代幾乎停在 `-90` 到 `-86` 區間，真正改善主要出現在 generation 11–12，但之後沒有再突破 `-81.58`。niche 數較高，卻沒有伴隨 GP 提升，表示策略描述的分化未被可靠地 materialize 成有效行為。

## 五、最終族群對各對手的表現

分數越高越好。W-D-L 是最終 10 個 survivor 對該對手的 180 場合計。

| Opponent | 純 Ministral mean | 雙模型 mean | 純－雙 | 純 W-D-L | 雙 W-D-L |
|---|---:|---:|---:|---:|---:|
| Passive | 93.28 | 5.79 | +87.49 | 162-18-0 | 0-180-0 |
| Random | 78.53 | 2.42 | +76.12 | 135-44-1 | 3-171-6 |
| RandomBiased | 30.30 | -14.50 | +44.80 | 73-86-21 | 2-148-30 |
| LightRush | -32.49 | -97.23 | +64.74 | 54-12-114 | 0-3-177 |
| HeavyRush | -18.24 | -97.25 | +79.01 | 54-36-90 | 0-3-177 |
| WorkerRush | -77.77 | -96.05 | +18.28 | 21-0-159 | 0-6-174 |
| AllInBot | -76.14 | -99.61 | +23.47 | 21-0-159 | 0-0-180 |
| Mayari | -94.79 | -100.90 | +6.11 | 7-0-173 | 0-0-180 |
| COAC | -81.75 | -100.45 | +18.70 | 15-6-159 | 0-0-180 |
| TMA | -102.28 | -99.81 | -2.47 | 0-0-180 | 0-0-180 |
| **總計** | — | — | — | **542-202-1056** | **5-511-1284** |

純 Ministral 的優勢不是只來自 Passive/Random；對 LightRush、HeavyRush、WorkerRush、AllInBot、COAC 也都有明顯改善。雙模型只有在 TMA 平均分略高 2.47，但雙方對 TMA 都是 180 場全敗，不能視為實質競爭力優勢。

雙模型的主要行為不是取勝，而是把簡單對手拖成和局：Passive 180 場全和、Random 171 和、RandomBiased 148 和。這與其防守、經濟優先但進攻能力不足的最終策略相符。

換算全部 1,800 場，純 Ministral 的勝／和／敗率為 `30.11% / 11.22% / 58.67%`；雙模型為 `0.28% / 28.39% / 71.33%`。

## 六、生成、驗證與失敗情況

### 6.1 全部 210 個 candidate 狀態

| 指標 | 純 Ministral | 雙模型 |
|---|---:|---:|
| evaluated | 193 | 204 |
| failed | 17 | 6 |
| validation failure | 6 | 2 |
| compilation failure | 8 | 3 |
| runtime failure | 3 | 1 |
| compile success | 196 | 205 |
| compile failed | 8 | 3 |
| compile not run | 6 | 2 |

雙模型在工程可靠度上明顯較好：candidate failure rate 從 `17/210 = 8.1%` 降到 `6/210 = 2.9%`。兩者 generation 20 的 survivor 都沒有 failure，且都完成 1,800/1,800 場。

### 6.2 200 個 offspring 的 Java generation records

| 指標 | 純 Ministral | 雙模型 |
|---|---:|---:|
| generation record success | 186/200（93.0%） | 195/200（97.5%） |
| first-attempt selected | 140/200（70.0%） | 183/200（91.5%） |
| total attempts | 323 | 235 |
| 一般 materialization success | 136/142（95.8%） | 136/138（98.6%） |
| Code Reflection direct generation success | 50/58（86.2%） | 59/62（95.2%） |

Qwen 的核心優點是更常在第一次就產生可通過 validation/compilation 的 Java，顯著減少 repair attempts。但是「能編譯」和「忠實、有效」是不同層次；後續 strategy-alignment 與遊戲結果顯示它在語意 materialization 上較弱。

`generation/result.json` 的 direct-generation status 與 mutation metadata 的 `revision_status` 是不同 checkpoint：前者記錄 generator attempt 的結果，後者記錄 mutation operator 最後是否提交／套用 revision，之後還有 validation、compilation、integration 與 evaluation。因此第六節與第八節的成功數不要求完全相等。

## 七、三種 mutation operator 的觀察結果

下表的 survivor rate 是該 mutation 產生的 candidate 在出生當代進入 survivor population 的比例。`positive ΔGP` 和 median ΔGP 是與 artifact 記錄的 comparison parent 比較 aggregate GP；只納入雙方皆 evaluated 的 pair。

| Run | Mutation | 數量 | applied | evaluated | 當代 survivor rate | positive ΔGP | median ΔGP |
|---|---|---:|---:|---:|---:|---:|---:|
| 純 | Strategy | 46 | 46 | 45 | 34.8% | 11/45（24.4%） | -8.03 |
| 純 | Prompt | 72 | 58 | 66 | 55.6% | 25/66（37.9%） | -0.67 |
| 純 | Code | 58 | 47 | 49 | 43.1% | 19/49（38.8%） | -0.27 |
| 雙 | Strategy | 46 | 46 | 45 | 41.3% | 13/45（28.9%） | -0.43 |
| 雙 | Prompt | 71 | 35 | 70 | 39.4% | 27/70（38.6%） | -0.19 |
| 雙 | Code | 62 | 60 | 58 | 51.6% | 16/58（27.6%） | -0.42 |

解讀限制：aggregate GP 不是 lexicase 的直接 selection objective，所以 positive ΔGP 不等於 operator reward，也不能只用這欄判定 operator 好壞。較穩健的觀察是：

- 純 Ministral 中 Prompt Reflection 的當代留存率最高（55.6%），Code Reflection 次之（43.1%）。
- 雙模型中 Code Reflection 留存率最高（51.6%），但其 aggregate GP 正向 pair 比例只有 27.6%。這表示它可能保留某些 opponent-specific case，卻沒有改善整體加權表現。
- 純 Ministral 的 Strategy Reflection 變異幅度最大，median ΔGP 為 -8.03；它能創造大幅不同策略，也較容易產生破壞性變化。

## 八、Code Reflection 專項分析

### 8.1 三項反思結論

Code Reflection 的 diagnosis 由 Ministral 執行；雙模型只把最後 Java revision/materialization 交給 Qwen。

| 結論維度 | 純 Ministral | 雙模型 |
|---|---:|---:|
| reflection success | 57/58 | 60/62 |
| strategy faithful | 11/57（19.3%） | 7/60（11.7%） |
| strategy unfaithful | 46/57（80.7%） | 53/60（88.3%） |
| code concise | 2/57（3.5%） | 0/60（0%） |
| needs simplification | 55/57（96.5%） | 60/60（100%） |
| game compliant | 56/57（98.2%） | 59/60（98.3%） |
| game noncompliant | 1/57（1.8%） | 1/60（1.7%） |

這組結果支持目前 Code Reflection 的修改方向：它確實常辨識出「程式可編譯，但不忠實或過度複雜」的情況，而不是只做勝負優化。另一方面，`compliant` 比例接近 98% 只代表 LLM diagnosis 的自我判斷，不能當作獨立形式驗證。

### 8.2 Revision 結果

| 指標 | 純 Ministral revision | Qwen revision |
|---|---:|---:|
| revision required | 57 | 60 |
| revision success | 47 | 60 |
| revision failed | 10 | 0 |
| not run | 1 | 2 |
| applied | 47/58（81.0%） | 60/62（96.8%） |
| Java hash changed | 47 | 49 |

Qwen revision 的流程成功率較高，但 60 次成功 revision 中只有 49 次 Java hash 改變，表示 11 次成功沒有形成不同 Java。純 Ministral 的成功 revision 全部造成 Java 變更。

### 8.3 Evidence isolation

抽查兩個 run 保存的 `code_reflection/reflector_request.txt` 與 `prompt_reflection/reflector_request.txt`：

- 都明確禁止使用 game performance、opponent scores、W/D/L、match results、traces、logs 或 aggregate fitness。
- Code Reflection 收到 strategy prompt、parent Java、gameplay contract、Java scaffold／介面，以及 structural/compile evidence。
- Prompt Reflection 收到 policy、editable Java strategy region、gameplay contract／generation prompt，以及 structural/compile evidence。
- Strategy Reflection 仍可使用比賽評論與 opponent evidence，這是其設計目的。

因此本次 artifact 顯示 Code/Prompt Reflection 的輸入隔離方向正確；它們沒有直接拿勝負表現來改 code/prompt。

### 8.4 反思結論與最終實作品質並不等價

純 Ministral 最佳個體的最後一次 Code Reflection 結論是：`faithful`、`needs_simplification`、`compliant`，revision 第二次嘗試成功且 Java 有改變。但最終 code-quality evaluator 仍只給 strategy alignment `7/10`；人工抽查也發現 Worker attack 規則用 `nearestEnemy`，未先驗證 policy 指定的 range 1，就直接交給抽象 attack 行為，實際可追擊遠距敵人。這代表 Code Reflection 的結論仍可能漏掉語意差異。

雙模型最佳個體不是 Code Reflection offspring，而是 Strategy Reflection offspring。其最終 alignment 只有 `2/10`，且 policy 中「Base 無相鄰空格時，在 distance 2 的格子訓練 Worker」本身不符合 MicroRTS 只能在相鄰格生產的規則；生成 Java 也沒有忠實實作這條 fallback。這顯示只讓 Code Reflection candidate 接受 compliance diagnosis 不夠，Strategy/Prompt offspring 在最後 materialization 後也需要共同的 deterministic legality 與 alignment gate。

此外，strategy-alignment 分數本身也是 LLM diagnostic；其理由文字中可見至少一項與 gameplay contract 不完全一致的距離判斷敘述。因此本報告把它視為支持證據，而不是 ground truth。

## 九、Prompt Reflection 與 Strategy Reflection

| 指標 | 純 Ministral | 雙模型 |
|---|---:|---:|
| Strategy Reflection count / applied | 46 / 46 | 46 / 46 |
| Prompt Reflection count | 72 | 71 |
| Prompt reflection success | 72 | 70；另 1 failed |
| Prompt rewrite success | 58 | 35 |
| Prompt rewrite failed | 14 | 35；另 1 無結果 |

雙模型的 Prompt rewrite 成功率只有 `35/71 = 49.3%`，明顯低於純 Ministral 的 `58/72 = 80.6%`。但此 rewrite 階段仍由 Ministral 執行，所以不能直接把差異歸因於 Qwen；較可能是兩個 run 的 parent/policy 分布、LLM 隨機輸出與 retry path 不同。

Strategy Reflection 在兩邊都完整執行，但最後 Java 的品質取決於後置 materialization。雙模型較多 niche、較低 alignment 的組合顯示 Qwen 能接受多樣策略輸入，卻沒有穩定保留其完整行為。

## 十、多樣性與 materialization

| 指標 | 純 Ministral | 雙模型 |
|---|---:|---:|
| offspring unique Java hashes | 171 | 72 |
| final unique policy hashes | 3 | 4 |
| final unique Java hashes | 10 | 5 |
| final unique strategy niches | 2 | 4 |
| final recognized niche signatures | 4/10 | 10/10 |
| final mean strategy distance | 0.50 | 0.71 |

雙模型在文字策略空間較多樣，但 Java 空間反而更集中。換句話說，**Qwen 把不同策略壓縮成較少數的程式行為**；這與 final alignment `2.0/10` 及低戰力一致。純 Ministral 的文字 niche 較集中，卻保留 10/10 不同 Java hash，且實際對戰行為差異更有用。

## 十一、代表個體與 lineage

### 11.1 純 Ministral 最佳個體

- Candidate：[`gen_0020_f5bea1248ef6`](../../runs/20260908_121222_306081/candidates/gen_0020_f5bea1248ef6/)
- 出生：generation 20，`crossover+mutation` + Code Reflection；兩個 parent slot 都指向 `gen_0019_c925d51aaffa`。
- Aggregate GP：`-47.518094`。
- 最佳 matchup：Random `103.986318`。
- 最差 matchup：TMA `-103.179530`。
- Code quality：`34.07`；strategy alignment `7/10`；Java 525 行。
- 策略重點：Worker 經濟、最多兩座 Barracks、Heavy/Ranged 生產，以及低 HP Worker 的主動攻擊。
- Java lineage 的主要 GP 路徑：gen0 `-89.83` → gen2 `-79.37` → gen4 `-70.57` → gen6 `-57.06` → gen7 `-49.41` → gen8 `-48.58` → gen14 `-48.00` → gen20 `-47.52`。中間因 crossover、prompt/code mutation 與 lexicase 保留而有上下波動。

這個 lineage 顯示實質突破在 generation 2–8 完成，後段主要是維持與局部調整，而不是持續線性上升。

### 11.2 雙模型最佳個體

- Candidate：[`gen_0019_887ced275cde`](../../runs/20260909_032729_611766/candidates/gen_0019_887ced275cde/)
- 出生：generation 19，copy path 上套用 Strategy Reflection，parent 為 `gen_0017_f9a7b5d7bcf7`。
- Aggregate GP：`-81.908586`。
- 最佳 matchup：Random `11.259077`。
- 最差 matchup：Mayari `-102.017707`。
- Code quality：`26.87`；strategy alignment `2/10`；Java 438 行。
- 策略重點：經濟與防守優先，Light 作為防線、Heavy 反制，進攻條件有限。
- Java lineage 的主要 GP 路徑：gen0 `-90.31` → gen2 `-89.53` → gen5 `-86.69` → gen8 `-85.80` → gen11 `-82.29` → gen12 `-81.58` → gen19 `-81.91`。

它的進步較慢，且大量勝負被轉成和局。Strategy Reflection 產生的策略語意沒有被 Qwen 完整轉成有效 Java，是目前最需要處理的問題。

## 十二、時間與效率

### 12.1 Generation timing

| 指標 | 純 Ministral | 雙模型 |
|---|---:|---:|
| generation 0 | 1,074.95 s | 1,075.19 s |
| generations 1–20 合計 | 53,830.59 s（14.95 h） | 56,028.46 s（15.56 h） |
| 每代 median | 2,683.54 s（44.73 min） | 2,627.84 s（43.80 min） |
| 每代 mean | 2,691.53 s（44.86 min） | 2,801.42 s（46.69 min） |

雙模型的 generation median 略低，但總 evolutionary time 高 `2,197.87 s`，約多 36.6 分鐘／4.1%。

### 12.2 Offspring phase 累積時間

以下欄位各自加總，不應再次彼此相加；`child_total` 已涵蓋主要子階段。

| Phase | 純 Ministral | 雙模型 | 差異解讀 |
|---|---:|---:|---|
| child total | 47,048.63 s | 53,162.44 s | 雙模型 +13.0% |
| candidate generation_llm stage | 13,213.65 s | 7,728.09 s | Qwen 約快 41.5% |
| all logged LLM requests | 38,928.74 s | 28,570.96 s | 雙模型少 26.6% |
| evaluation | 14,752.32 s | 27,379.74 s | 雙模型多 85.6% |
| MicroRTS matches | 10,379.43 s | 21,948.55 s | 雙模型多 111.5% |

因此，Qwen 並不是推論太慢；它的 Java 生成其實更快、更少 retry。整體實驗變慢的主要來源是 MicroRTS matches。結合最終大量和局，合理推論是雙模型產生的保守或無效行為更常把比賽跑到較高 tick limit，抵銷了 LLM generation 的節省。

## 十三、整體判斷

### 13.1 可以下的結論

1. 這次純 Ministral pipeline 的 competitive performance 明顯優於雙模型 pipeline。
2. Qwen3.5 9B 的 syntactic/compilation reliability 較高，第一次成功率也高。
3. Qwen 產生的 Java 對 strategy prompt 的忠實度不足，最終族群 alignment 顯著較低。
4. 雙模型增加文字策略 diversity，卻沒有增加 Java diversity 或勝率。
5. Code Reflection diagnosis 能辨識不忠實、過度複雜與少數不合規案例，方向正確；但 LLM 自評不能保證 revision 後真的忠實。
6. Code/Prompt Reflection 的 archived request 符合 evidence isolation：未使用 game performance。

### 13.2 目前不能下的結論

1. 不能斷言 Qwen3.5 9B 在所有條件下一定比 Ministral 差，因為初始 LLM policy 沒有凍結配對。
2. 不能用 aggregate GP 的單代下降推論 survivor selection 或 Java inheritance 有錯；lexicase 並不直接保證 aggregate 單調。
3. 不能把 `compliant`、validation passed 或 compilation success 當成策略忠實度證明。
4. 不能把這一次的時間差視為純模型吞吐差異；策略行為造成的 match length 是更大的因素。

## 十四、建議的下一步

依優先順序建議：

1. **目前正式長跑先使用純 Ministral materialization。** 它是唯一在這次 run 中把演化轉成大量勝場的版本。
2. **建立真正配對的模型 A/B。** 先固定一份完整 generation-0 population（policy、generation prompt、Java、hash），兩邊直接從同一份 artifact 開始；至少跑 3–5 個 EA seed。
3. **所有 mutation 類型在最終 Java materialization 後通過同一個 gate。** 不只 Code Reflection；Strategy/Prompt offspring 也要檢查 policy legality、Java action legality、rule coverage 與 policy-code alignment。
4. **把 deterministic checks 放在 LLM diagnosis 前後。** 例如 production 必須相鄰、actor/unit capability 必須合法、attack range/target ownership、每條 policy rule 是否有對應 reachable code path。LLM 負責解釋與修正，程式檢查負責判定硬規則。
5. **針對 Qwen prompt 做最小化適配。** 優先測試較短的 generation prompt、明確逐條 rule-to-code checklist、禁止省略規則、輸出後逐條自查；不要先增加更多 performance context。
6. **新增獨立 holdout evaluation。** 最終 survivor 再用未參與 selection 的地圖、不同 rounds/seed 或額外 opponent 測一次，避免只對固定十個 cases 過度適應。
7. **報告分開呈現四層指標：** decode/compile success、mechanical compliance、strategy alignment、game performance。任何單層成功都不能代替下一層。

## 十五、資料完整性與計算方式

本報告直接讀取兩個 run 的：

- `manifest.json`、`config.yaml`、`summary.json`
- `generations/generation_0000.json` 至 `generation_0020.json`
- 420 份 `candidates/*/candidate.json` 與 lineage、generation、mutation、validation、compilation、integration、evaluation artifacts
- `timing.jsonl` 與 candidate `timing.json`
- Code/Prompt/Strategy Reflection 保存的 request、response 與 metadata

所有表格中的 GP、CQ、opponent mean、W-D-L、failure count 與 timing 都由 committed artifacts 彙整；未以終端文字推測。數值顯示至小數點後兩位時採四捨五入，計算仍使用原始精度。
