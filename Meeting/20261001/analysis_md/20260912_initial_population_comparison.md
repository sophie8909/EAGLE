# EAGLE 初始族群比較實驗簡報內容

日期：2026-09-12
主題：全 Worker Rush 起始族群 vs. 1 個 Worker Rush 加 9 個 LLM policies
形式：投影片內容草稿，不含簡報版面製作

---

## Slide 1｜初始族群設計比較

### 標題

初始 policy 多樣性與 Java seed 對 EAGLE 演化的影響

### 副標題

20 代、族群大小 10、Ministral 3 8B、opponent-wise lexicase

### 講者備註

本次比較包含兩個完整 run。核心問題是：相同 Worker Rush policy 起始，與混合 LLM policies 起始，哪一種方案更能產生有競爭力的 MicroRTS agent。

---

## Slide 2｜兩組比較的是完整初始化方案

### 投影片文字

| 條件 | Policy 初始族群 | Generation 0 Java |
|---|---|---|
| 全 Worker Rush | 10 個相同 Worker Rush policy | 由 no-op Java seed 出發，執行 10 次獨立 Java generation |
| Mixed policies | 1 個 Worker Rush policy，加 9 個 LLM-generated policies | 10 個 candidate 共用 checked-in WorkerRush Java，不執行 Java generation |

共同設定：

- 20 代，每代 10 個 offspring，族群大小 10
- `mu_plus_lambda` survivor selection
- 10 個 opponent cases，使用 lexicase selection
- Strategy、Prompt、Code reflection 機率分別為 0.33、0.33、0.34
- 3 張地圖，每個 candidate 完成 180 場搜尋評估

### 頁面結論

這是兩種完整初始化方案的比較，沒有單獨控制 policy 多樣性。

### 講者備註

兩組除了 policy 組成不同，Java seed 與 generation 0 materialization 也不同。因此後續結果可以判斷哪個方案整體較好，但不能直接證明差異全部來自 LLM policy 多樣性。

---

## Slide 3｜Mixed 初始化方案取得明顯優勢

### 投影片文字

分數越高越好。

| 指標 | 全 Worker Rush | Mixed policies | Mixed 優勢 |
|---|---:|---:|---:|
| 最終最佳 Game Performance | -87.78 | **-50.51** | +37.27 |
| 最終族群平均 | -88.89 | **-65.35** | +23.54 |
| 最終族群中位數 | -89.09 | **-67.67** | +21.42 |
| Final test 勝率 | 4.0% | **42.7%** | +38.7 個百分點 |
| Final test W/D/L | 24 / 141 / 435 | **256 / 12 / 332** | 多 232 勝 |

### 頁面結論

Mixed 方案只增加約 10% 搜尋時間，卻將 final-test 勝率提高超過十倍。

### 建議視覺

以大字呈現 `4.0%` 與 `42.7%`，下方保留完整 W/D/L，避免只用勝率掩蓋和局與敗局。

### 講者備註

兩組 final test 都完成 600 場且沒有執行錯誤。Mixed 的優勢不只存在於 aggregate score，也反映在實際勝場。

---

## Slide 4｜兩組從相近起點快速分化

### 投影片文字

| Generation | 全 Worker Rush best | Mixed best | Mixed 領先 |
|---:|---:|---:|---:|
| 0 | -89.46 | -90.29 | -0.83 |
| 1 | -88.96 | -81.96 | +7.00 |
| 5 | -88.31 | -78.26 | +10.05 |
| 10 | -89.25 | -69.34 | +19.91 |
| 12 | -89.13 | -52.10 | +37.03 |
| 20 | -87.78 | -50.51 | +37.27 |

### 頁面結論

Generation 0 表現幾乎相同。兩種初始化方案從 generation 1 開始拉開差距，Mixed 在 generation 12 出現主要突破。

### 建議圖表

- [全 Worker Rush 演化曲線](../../runs/20260910_160655_907573/analysis/plots/game_performance_by_generation.png)
- [Mixed policies 演化曲線](../../runs/20260911_072610_382082/analysis/plots/game_performance_by_generation.png)

### 講者備註

Mixed 的最佳值在 generation 12 從 -68.43 跳到 -52.10，generation 18 到達 -50.51，之後沒有再突破。全 Worker Rush 在 20 代內大致停留於 -90 附近。

---

## Slide 5｜Mixed 的進步集中在基礎與中階對手

### 投影片文字

Final test，每個 opponent 60 場，數字為 W/D/L。

| Opponent | 全 Worker Rush | Mixed policies |
|---|---:|---:|
| Passive | 0 / 60 / 0 | **60 / 0 / 0** |
| Random | 22 / 38 / 0 | **59 / 1 / 0** |
| RandomBiased | 2 / 43 / 15 | **57 / 1 / 2** |
| LightRush | 0 / 0 / 60 | **30 / 10 / 20** |
| HeavyRush | 0 / 0 / 60 | **40 / 0 / 20** |
| WorkerRush | 0 / 0 / 60 | 0 / 0 / 60 |
| AllInBot | 0 / 0 / 60 | 0 / 0 / 60 |
| Mayari | 0 / 0 / 60 | 0 / 0 / 60 |
| COAC | 0 / 0 / 60 | **10 / 0 / 50** |
| TMA | 0 / 0 / 60 | 0 / 0 / 60 |

### 頁面結論

Mixed 已能穩定擊敗基礎對手，並對 LightRush、HeavyRush 與 COAC 取得實質勝場。WorkerRush 與高階對手仍是主要瓶頸。

### 講者備註

全 Worker Rush 最佳 agent 的主要能力是把 Passive 與 Random 類對手拖成和局。Mixed 則真正將和局轉為勝局，但尚未突破 WorkerRush、AllInBot、Mayari 和 TMA。

---

## Slide 6｜Mixed 在大地圖上的泛化能力下降

### 投影片文字

Mixed final test：

| 地圖 | W/D/L | 勝率 |
|---|---:|---:|
| 8×8 | 98 / 0 / 102 | 49% |
| 16×16 | 90 / 10 / 100 | 45% |
| 24×24 | 68 / 2 / 130 | 34% |

Player side：

- p0：128 勝、1 和、171 敗
- p1：128 勝、11 和、161 敗

### 頁面結論

整體勝場沒有 side bias，但地圖擴大後勝率明顯下降，顯示長距離經濟、移動與進攻決策仍不足。

### 講者備註

部分 matchup 仍有局部 side dependency。例如 LightRush 在 24×24 上只於 p0 取勝，COAC 在 16×16 上只於 p1 取勝。整體平衡不代表每個 matchup 都穩定。

---

## Slide 7｜主要突破來自重組與重新 materialization

### 投影片文字

Mixed 最終族群：

- 10 個 survivor 中，只有 1 個真的成功套用 mutation
- Generation 12 的主要突破 candidate，其 Strategy mutation 被拒絕
- 該 candidate 仍因 crossover 組合及重新 materialization，將最佳分數提升到 -52.10
- 最佳 candidate 標記為 Code Reflection，但三次 Java revision 都失敗
- 最佳 candidate 實際沿用父代 Java，只有結尾換行造成檔案 hash 差異

### 頁面結論

這次的性能提升主要由 component crossover 與 Generator 重新解碼帶動，reflection mutation 並非主要來源。

### 講者備註

候選人的 operator 標籤代表被分配的操作，不代表操作一定成功改變 genotype 或 phenotype。分析 operator 成效時必須同時查看 `applied`、revision status 與 Java diff。

---

## Slide 8｜Static reflection 的投入沒有轉成穩定收益

### 投影片文字

Mixed run：

| Operator | 分配次數 | 實際套用 | Candidate 失敗 | 套用且可執行後，平均 GP 變化 |
|---|---:|---:|---:|---:|
| Strategy | 70 | 46 | 4 | -9.87 |
| Prompt | 72 | 40 | 7 | -3.74 |
| Code | 58 | 39 | 12 | -5.59 |

補充：

- 三種 operator 中，實際套用且可執行的 child 只有約四分之一優於 evidence parent
- Code operator 的 candidate failure rate 最高，為 12/58
- Strategy commentator、Coach 與 contract rewrite 共消耗約 4.6 小時 LLM 時間
- 沒有任何成功套用的 Strategy mutation 留在最終族群

### 頁面結論

固定 0.33 / 0.33 / 0.34 的分配沒有反映 operator 的實際成功率與成本。

### 講者備註

GP 變化以各 operator 的 evidence parent 為基準。因為 child 也可能包含 crossover 成分，這不是純粹的 mutation 因果估計，但方向仍顯示 static schedule 效率偏低。

---

## Slide 9｜Mixed 提升戰力，也提高 pipeline 風險

### 投影片文字

| 指標 | 全 Worker Rush | Mixed policies |
|---|---:|---:|
| 成功評估 candidate | 207 / 210 | 187 / 210 |
| Candidate failures | 3 | 23 |
| Generation-stage 成功 | 209 / 210 | 183 / 200 |
| 第一次 Java attempt 成功 | 153 | 140 |
| LLM requests | 1,538 | 1,659 |
| LLM request 累積時間 | 9.61 小時 | 10.98 小時 |
| 搜尋時間 | 15.21 小時 | 16.72 小時 |

Mixed 的 23 個失敗：

- Validation：7
- Runtime：6
- Generation：5
- Compilation：5

### 頁面結論

Policy 多樣性增加了可搜尋空間，也讓 Java decoding、repair 與 runtime 行為更不穩定。

### 講者備註

Mixed 有 43 個 Java materialization 在 retry 後成功，另有 17 個耗盡五次 attempt。性能提升很大，但目前仍以更高的失敗率與運算成本交換。

---

## Slide 10｜最佳 agent 仍有明確語義錯誤

### 投影片文字

最佳 Mixed agent：

- Game Performance：-50.51
- Function Capability：100/100
- Strategy Alignment：4/10
- Code Quality：26.14

Java 中的關鍵問題：

- 多處以 `enemy.getPlayer() < 0` 尋找敵人，實際選到 neutral/resource
- `commandHarvest(worker, null, base)` 必然被 action helper 拒絕
- 嘗試讓 Base 呼叫只能由 Worker 執行的 `commandBuild`
- Heavy 與 Ranged 防禦條件因此很少真正觸發

### 頁面結論

現有 validation 能確認結構與 API 安全，仍不足以驗證策略語義。這也解釋了 WorkerRush 與高階對手的全敗。

### 講者備註

Function Capability 只證明程式包含經濟、生產、戰鬥、目標選擇和狀態判斷能力，不代表每個條件都使用正確的 player ownership，也不代表策略忠實或有效。

---

## Slide 11｜策略多樣性數量不等於有效行為多樣性

### 投影片文字

| 最終族群指標 | 全 Worker Rush | Mixed policies |
|---|---:|---:|
| Strategy niches | 8 | 3 |
| Dominant niche ratio | 20% | 60% |
| Unique Java hashes | 10 | 9 |
| Mean Strategy Alignment | 6.2/10 | 5.7/10 |
| Mean Code Quality | 27.85 | 23.65 |

### 頁面結論

全 Worker Rush 保留更多 niche，也有較高 alignment 與 code quality，但遊戲表現幾乎沒有改善。Mixed 收斂到較少的有效方向，戰力反而顯著較高。

### 講者備註

這個結果符合目前的架構設計。Niche、alignment 與 code quality 都是診斷，不是 optimizer fitness cases。它們適合解釋結果，不能代替實際 opponent-wise evaluation。

---

## Slide 12｜目前只能確認 Mixed 方案整體較好

### 投影片文字

目前證據支持：

- Mixed 初始化方案在本次 run 明顯勝過全 Worker Rush 方案
- Final test 支持搜尋階段觀察到的性能差距
- Mixed 的收益大於額外約 10% 的搜尋時間

目前證據不能支持：

- 將全部差異歸因於 LLM-generated policy diversity
- 推論任何 random seed 都會得到相同結果
- 宣稱 agent 已能泛化到新的地圖或 holdout opponents

### 講者備註

每個條件只有一個 evolutionary run。600 場 final test 提高了同一 phenotype 的 matchup 測量穩定度，但不能取代跨 evolutionary seed 的重複實驗。Deterministic opponent 的重複場次也不是完全獨立樣本。

---

## Slide 13｜下一輪實驗設計

### 投影片文字

第一優先：2×2 初始化實驗

| | 共用 fixed WorkerRush Java | 由 no-op seed 生成 Java |
|---|---|---|
| 10 個相同 Worker Rush policies | 條件 A | 條件 B，現有全 Worker Rush 方案 |
| 1 Worker Rush + 9 LLM policies | 條件 C，現有 Mixed 方案 | 條件 D |

執行原則：

- 每個條件至少 3 個 evolutionary seeds
- 保持 model、selection、operator 配比與 evaluation matrix 相同
- 保留完整 20 代，因為本次主要突破發生在 generation 12
- 另外加入未參與演化的 holdout maps 或 opponents

第二優先：提高搜尋效率

- 比較 `static` 與 `aos_opponent`
- 測試將 Strategy Commentator sample count 從 10 降低
- 加入 enemy ownership、null target、非法 builder 的 semantic validation

### 頁面結論

下一輪必須分離 policy diversity 與 Java seed 品質，才能判斷真正的因果來源。

---

## Slide 14｜決策建議

### 投影片文字

近期實驗基線：採用 Mixed 初始化方案

原因：

- Final-test 勝率由 4.0% 提高到 42.7%
- 已能擊敗基礎對手及部分 LightRush、HeavyRush、COAC
- 額外搜尋時間約 1.5 小時，性能收益明顯更大

同時保留三項限制：

- 不將目前結果表述為 policy diversity 的單因子因果證明
- 不將 static reflection 的 operator 標籤直接視為有效 mutation
- 下一輪優先處理 semantic validation 與跨 seed replication

### 收尾句

Mixed 初始化已找到可行方向。下一個問題是釐清性能來源，並降低 materialization 與 reflection 的浪費。

---

## 附錄｜資料來源

### 實驗設定

- [Batch index](../../configs/experiments/0910_initial_population_comparison_20x10/experiment.yaml)
- [全 Worker Rush config](../../configs/experiments/0910_initial_population_comparison_20x10/01_all_worker_rush_20x10.yaml)
- [Mixed policies config](../../configs/experiments/0910_initial_population_comparison_20x10/02_one_worker_rush_llm_policies_20x10.yaml)

### Run artifacts

- [全 Worker Rush summary](../../runs/20260910_160655_907573/summary.json)
- [全 Worker Rush final test](../../runs/20260910_160655_907573/final_test/final_test_results.md)
- [Mixed policies summary](../../runs/20260911_072610_382082/summary.json)
- [Mixed policies final test](../../runs/20260911_072610_382082/final_test/final_test_results.md)
- [Mixed 最佳 candidate Java](../../runs/20260911_072610_382082/candidates/gen_0018_bae77764b1d1/phenotype/CandidateAgent.java)
- [Mixed 最佳 candidate alignment](../../runs/20260911_072610_382082/candidates/gen_0018_bae77764b1d1/strategy_alignment/result.json)

### 分析產物注意事項

Canonical analysis 的 `summary.md` 目前會將 completed generations 顯示為 0，並只統計 final population failures。實驗原始 artifacts 顯示兩組皆完成 generation 20，歷史 candidate failures 分別為 3 與 23。本簡報內容使用 generation、candidate、timing 與 final-test artifacts 重新計算。
