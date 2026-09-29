# EAGLE Self-play 兩版與 fixed-roster 基準比較簡報內容

日期：2026-09-26

比較 runs：

- Fixed-roster 10×20 基準：`20260911_072610_382082`
- Self-play 10×20：`20260923_134743_200030`
- Self-play 5×40：`20260925_134245_911171`

主題：比較兩版 self-play 與「eval 過程對多個固定對手」的 10×20 基準

形式：投影片內容草稿，不含簡報版面製作

建議長度：12 張主簡報，加 3 張附錄，約 12 至 18 分鐘

---

## Slide 1｜Self-play 有明顯進步，但仍未超越固定對手基準

### 標題

5×40 self-play 將外部勝率從 0% 提升到 32.8%

### 副標題

與 fixed-roster 10×20 基準的搜尋結果、泛化能力與成本比較

### 投影片文字

| 實驗 | Final-test 勝率 | W / D / L |
|---|---:|---:|
| Fixed-roster 10×20 基準 | **42.7%** | 256 / 12 / 332 |
| Self-play 5×40 | **32.8%** | 197 / 11 / 392 |
| Self-play 10×20 | **0%** | 0 / 151 / 449 |

### 頁面結論

新版 5×40 self-play 修復了舊版「只會和局、不會取勝」的主要問題，但仍落後固定對手基準 **9.8 個百分點**。

### 建議視覺

用三根水平長條顯示勝率。由上到下依序為基準、5×40、10×20；在 5×40 與基準之間標示 `-9.8 pp`。

### 講者備註

本簡報的「基準」依本次指定，採用搜尋期間對多個固定 opponent 評估的 10×20 run。三個 run 的 final test 都是同一套 600 場測試，因此外部勝率是最可靠的橫向比較指標。

資料來源：[baseline final test](../../runs/20260911_072610_382082/final_test/final_test_results.md)、[self-play 10×20 final test](../../runs/20260923_134743_200030/final_test/final_test_results.md)、[self-play 5×40 final test](../../runs/20260925_134245_911171/final_test/final_test_results.md)

---

## Slide 2｜三組實驗的比較口徑

### 投影片文字

| 項目 | Fixed-roster 基準 | Self-play 10×20 | Self-play 5×40 |
|---|---:|---:|---:|
| Run | `20260911...` | `20260923...` | `20260925...` |
| Generations | 20 | 20 | 40 |
| Population size | 10 | 10 | 5 |
| 搜尋評估對手 | 多個固定對手 | 10-slot snapshot | 5-slot snapshot |
| Snapshot refresh | 不適用 | 每 5 代 | 每 5 代 |
| 約略 regular candidate budget | 210 | 210 | 205 |
| Final test | 10 opponents × 3 maps × 2 sides × 10 games | 相同 | 相同 |
| Final-test 場數 | 600 | 600 | 600 |

三組實驗使用相同的 Ministral 3 8B、三張地圖、mutation 機率與 final-test opponent roster。兩版 self-play 只改變 generations 與 population size。

### 頁面結論

5×40 不是單純增加總 candidate 數，而是把相近的搜尋預算分配到更多代、更小族群，並經歷更多次 snapshot 更新。

### 建議視覺

畫三條等長 budget bar。基準與 10×20 標成約 210 個 regular candidates，5×40 標成約 205 個；再在 self-play bar 上標示 snapshot refresh 次數。

### 講者備註

5×40 有 40 次 refresh candidate records，故磁碟上的 candidate 目錄數會高於 regular candidate budget。此處用 regular births 說明搜尋規模，而不是直接拿 artifact 數量當作計算預算。

資料來源：[baseline config](../../runs/20260911_072610_382082/config.yaml)、[self-play 10×20 config](../../runs/20260923_134743_200030/config.yaml)、[self-play 5×40 config](../../runs/20260925_134245_911171/config.yaml)

---

## Slide 3｜結論摘要

### 投影片文字

1. **Fixed-roster 基準仍然最好**：256 勝，勝率 42.7%。
2. **5×40 self-play 大幅改善**：197 勝，勝率 32.8%，比 10×20 增加 197 勝。
3. **改善來自真正的取勝能力**：5×40 不再靠 timeout draws 撐住結果。
4. **能力仍偏窄**：勝場主要來自 Passive、Random、RandomBiased，對五個強對手仍是 60 場全敗。
5. **關鍵轉折可追溯到 G17**：Code Reflection 讓單位從「只攻擊射程內敵人」變成會尋找並追擊最近敵人。
6. **比較限制**：fixed-roster 基準來自較早的 repository state，不是完全同 commit 的 controlled ablation。

### 頁面結論

Self-play 機制已證明能找到可泛化的攻擊行為；下一步應補上固定 anchors 或 holdout probes，避免能力只對當期 snapshot 成立。

### 建議視覺

使用三段式訊息：`0%`、`32.8%`、`42.7%`。在 0% 到 32.8% 標示「已修復主要失敗模式」，在 32.8% 到 42.7% 標示「仍有 9.8 pp 差距」。

---

## Slide 4｜總體 final-test 結果

### 投影片文字

| 指標 | Fixed-roster 10×20 | Self-play 10×20 | Self-play 5×40 |
|---|---:|---:|---:|
| Wins | **256** | 0 | 197 |
| Draws | 12 | **151** | 11 |
| Losses | **332** | 449 | 392 |
| Errors | 0 | 0 | 0 |
| Win rate | **42.67%** | 0% | 32.83% |
| Non-loss rate | **44.67%** | 25.17% | 34.67% |

5×40 相對 10×20：

- 勝場增加 **197** 場
- 和局減少 **140** 場
- 敗場減少 **57** 場
- 勝率增加 **32.83 個百分點**

5×40 相對 fixed-roster 基準：

- 少 **59** 勝
- 多 **60** 敗
- 勝率少 **9.83 個百分點**

### 頁面結論

5×40 的進步不是把敗場換成和局，而是把舊版的和局與敗場轉成 197 個真實勝場。

### 建議視覺

以三條 100% stacked bar 呈現 W/D/L。10×20 的 draw 區塊使用中性色，5×40 與基準的 win 區塊使用同一強調色。

### 講者備註

三組 final test 都沒有 candidate error，因此差異是策略能力差異，不是測試失敗或缺失資料造成。

資料來源：[baseline summary](../../runs/20260911_072610_382082/final_test/final_test_summary.json)、[self-play 10×20 summary](../../runs/20260923_134743_200030/final_test/final_test_summary.json)、[self-play 5×40 summary](../../runs/20260925_134245_911171/final_test/final_test_summary.json)

---

## Slide 5｜5×40 恢復基礎對手能力，但 rush 與強對手仍是缺口

### 投影片文字

每個 opponent 共 60 場，數字為 W / D / L。

| Opponent | Fixed-roster 10×20 | Self-play 10×20 | Self-play 5×40 |
|---|---:|---:|---:|
| PassiveAI | 60 / 0 / 0 | 0 / 60 / 0 | 60 / 0 / 0 |
| RandomAI | 59 / 1 / 0 | 0 / 53 / 7 | **60 / 0 / 0** |
| RandomBiasedAI | 57 / 1 / 2 | 0 / 38 / 22 | 57 / 1 / 2 |
| LightRush | **30 / 10 / 20** | 0 / 0 / 60 | 10 / 0 / 50 |
| HeavyRush | **40 / 0 / 20** | 0 / 0 / 60 | 10 / 10 / 40 |
| WorkerRush | 0 / 0 / 60 | 0 / 0 / 60 | 0 / 0 / 60 |
| AllInBot | 0 / 0 / 60 | 0 / 0 / 60 | 0 / 0 / 60 |
| Mayari | 0 / 0 / 60 | 0 / 0 / 60 | 0 / 0 / 60 |
| COAC | **10 / 0 / 50** | 0 / 0 / 60 | 0 / 0 / 60 |
| TMA | 0 / 0 / 60 | 0 / 0 / 60 | 0 / 0 / 60 |

### 頁面結論

5×40 幾乎完全追回三個基礎對手的能力，也開始擊敗 LightRush 與 HeavyRush；與基準的 59 勝差距，主要就是 LightRush、HeavyRush 與 COAC。

### 建議視覺

只畫每個 opponent 的 wins grouped bars。前三個基礎對手、兩個 rush 對手、五個高難度對手分成三個區塊。

### 講者備註

與基準相比，5×40 在 RandomAI 多 1 勝，但在 LightRush 少 20 勝、HeavyRush 少 30 勝、COAC 少 10 勝，合計淨少 59 勝。這讓後續改進目標非常具體。

資料來源：[baseline final test](../../runs/20260911_072610_382082/final_test/final_test_results.md)、[self-play 10×20 final test](../../runs/20260923_134743_200030/final_test/final_test_results.md)、[self-play 5×40 final test](../../runs/20260925_134245_911171/final_test/final_test_results.md)

---

## Slide 6｜5×40 的勝場能跨地圖與雙方位出現

### 投影片文字

按地圖：

| 地圖 | Fixed-roster W / D / L | Self-play 10×20 | Self-play 5×40 |
|---|---:|---:|---:|
| 8×8 | 98 / 0 / 102 | 0 / 35 / 165 | 67 / 11 / 122 |
| 16×16 | 90 / 10 / 100 | 0 / 57 / 143 | 60 / 0 / 140 |
| 24×24 | 68 / 2 / 130 | 0 / 59 / 141 | 70 / 0 / 130 |

按 player side：

| Side | Fixed-roster W / D / L | Self-play 10×20 | Self-play 5×40 |
|---|---:|---:|---:|
| p0 | 128 / 1 / 171 | 0 / 78 / 222 | 97 / 11 / 192 |
| p1 | 128 / 11 / 161 | 0 / 73 / 227 | 100 / 0 / 200 |

### 頁面結論

5×40 在三張地圖與兩個 player side 都有勝場，改善不是單一地圖或先後手偏差；24×24 的勝場甚至略高於基準。

### 建議視覺

上半部畫三張地圖的 win count grouped bars；下半部用 p0 與 p1 兩個小卡顯示 97 與 100 勝。

### 講者備註

24×24 的 70 勝高於基準的 68 勝，但不能解讀為整體已超越基準，因為差距集中在 8×8 與 16×16。5×40 的 side 差只有 3 勝，沒有明顯單側依賴。

---

## Slide 7｜10×20 self-play 的失敗模式是「穩定和局」

### 投影片文字

| 證據 | Self-play 10×20 結果 |
|---|---:|
| Final snapshot search evaluation | **0 勝 / 180 和 / 0 敗** |
| Fixed-roster final test | **0 勝 / 151 和 / 449 敗** |
| Final population 最高 fitness 同分 | 7 / 10 |
| Unique objective vectors | 4 |
| Strategy niches | 4 |

最終 Java 行為的主要限制：

- 只攻擊附近的 enemy Workers
- 沒有一般化的敵人追擊邏輯
- 沒有有效控制 Heavy units
- 找不到目標時大量單位維持 idle

### 頁面結論

搜尋成功適應當期 snapshot，卻把「不輸給相似對手」當成主要訊號，最終收斂到無法終結比賽的和局策略。

### 建議視覺

用一個循環圖表示：相似 opponent snapshot、彼此難以擊殺、180 場和局、微小 shaping score、同類策略繼續被選中。

### 講者備註

Final snapshot 的正 fitness 來自 material 與 resource shaping，不代表任何勝場。跨 run 比較時不能把這個 self-play GP 與 fixed-roster GP 直接放在同一條尺度上。

資料來源：[self-play 10×20 tested candidate evaluation](../../runs/20260923_134743_200030/candidates/gen_0020_ee9b19ad3dc8/evaluation/game_performance.json)、[self-play 10×20 candidate Java](../../runs/20260923_134743_200030/candidates/gen_0020_ee9b19ad3dc8/phenotype/CandidateAgent.java)

---

## Slide 8｜5×40 的關鍵轉折發生在 Generation 17

### 投影片文字

| Generation | 當期 best W / D / L | Best GP | 解讀 |
|---:|---:|---:|---|
| G0 至 G2 | 0 / 180 / 0 | 0.000 | 初期全部和局 |
| G5 | 0 / 174 / 6 | 1.243 | 尚無勝場 |
| G10 至 G14 | 0 / 180 / 0 | 0.424 | 新 snapshot 後回到和局 |
| G16 | 0 / 180 / 0 | 0.161 | 突破前一代 |
| **G17** | **180 / 0 / 0** | **102.804** | Code Reflection 產生決定性突破 |
| G20 | 120 / 0 / 60 | 35.040 | Refresh 後仍保留勝場能力 |
| G40 | 114 / 24 / 42 | 40.523 | 最終 snapshot 仍可取勝 |

### 頁面結論

G17 首次讓搜尋訊號從「和局 shaping」變成真正的 win/loss 訊號，而且能力跨過後續 snapshot refresh 保留下來。

### 建議視覺

使用 snapshot 分段時間軸。每個 refresh boundary 以垂直虛線切開，G17 用強調色標示 `0 wins → 180 wins`。不要把不同 snapshot 的 GP 畫成連續可比較曲線。

### 講者備註

GP 只能在同一 opponent snapshot 內比較。這張投影片的重點是每個 generation 的 W/D/L 狀態，以及 G17 後在新 snapshot 仍能產生勝場，不是宣稱 GP 跨 snapshot 單調上升。

資料來源：[self-play 5×40 generation artifacts](../../runs/20260925_134245_911171/generations/)、[G17 evaluation](../../runs/20260925_134245_911171/candidates/gen_0017_a4bee4778e92/evaluation/game_performance.json)

---

## Slide 9｜Code Reflection 補上了「主動找敵人」的能力

### 投影片文字

G17 candidate：`gen_0017_a4bee4778e92`

Mutation：`crossover+mutation`，Code Reflection

核心行為改變：

| 修改前 | 修改後 |
|---|---|
| 只尋找目前攻擊範圍內的敵人 | 尋找全地圖最近的敵人 |
| 沒有射程內目標時容易 idle | 對最近敵人下達 `commandAttack` |
| 難以終結對稱或被動局面 | 單位會追擊並建立實際勝負 |

這條 lineage 延續到 final-test candidate `gen_0040_c02a137db168`。最終 Java 也保留「若攻擊單位仍 idle，攻擊最近敵人」的 fallback。

### 頁面結論

新版成功的核心不是更多 timeout，而是一個可解釋、可追溯、會主動完成戰鬥的 phenotype 改變。

### 建議視覺

用 before/after 示意圖：左側單位停在原地等敵人進入射程；右側單位鎖定最近敵人並向前追擊。旁邊標示 G16 `0/180/0` 與 G17 `180/0/0`。

### 講者備註

這是從 mutation artifact 與 Java diff 得到的機制解釋，與 final-test 的 197 勝方向一致。不過單一 mutation 與最終外部勝率之間仍不是嚴格因果實驗；更嚴謹的作法是做 mutation rollback 或同 seed 重跑。

資料來源：[Code Reflection metadata](../../runs/20260925_134245_911171/candidates/gen_0017_a4bee4778e92/mutation/code_reflection/metadata.json)、[parent Java](../../runs/20260925_134245_911171/candidates/gen_0017_a4bee4778e92/mutation/code_reflection/parent_candidate.java)、[reflected Java](../../runs/20260925_134245_911171/candidates/gen_0017_a4bee4778e92/mutation/code_reflection/reflected_candidate.java)、[final candidate Java](../../runs/20260925_134245_911171/candidates/gen_0040_c02a137db168/phenotype/CandidateAgent.java)

---

## Slide 10｜最終族群：5×40 有改善，但仍出現平台化

### 投影片文字

| 指標 | Fixed-roster 10×20 | Self-play 10×20 | Self-play 5×40 |
|---|---:|---:|---:|
| Final population size | 10 | 10 | 5 |
| 最高 fitness 同分 candidates | 1 | **7** | **4** |
| Unique objective vectors | 10 | 4 | 2 |
| Strategy niches | 3 | 4 | 3 |
| Unique Java hashes | 9 | 7 | 4 |
| 最高同分群的 Java hashes | 1 | 4 | 3 |

### 頁面結論

5×40 雖然找到能取勝的行為，但最終仍有 4/5 candidates 同列最高 fitness，objective 訊號只剩兩種，代表 selection resolution 仍然不足。

### 建議視覺

用三個 population strip 呈現 objective vectors。基準畫 10 種顏色，10×20 畫 4 種，5×40 畫 2 種；另用邊框差異表示 Java hash 仍未完全相同。

### 講者備註

同 fitness 不代表完全相同程式。5×40 的最高同分群仍有 3 個 Java hashes，顯示 phenotype 尚有差異，只是目前 snapshot 無法進一步排序。這正是加入固定 anchors 或外部 probe 的理由。

資料來源：[baseline generation metrics](../../runs/20260911_072610_382082/analysis/generation_metrics.csv)、[self-play 10×20 generation metrics](../../runs/20260923_134743_200030/analysis/generation_metrics.csv)、[self-play 5×40 generations](../../runs/20260925_134245_911171/generations/)

---

## Slide 11｜5×40 的時間成本接近基準，低於舊 self-play

### 投影片文字

| 指標 | Fixed-roster 10×20 | Self-play 10×20 | Self-play 5×40 |
|---|---:|---:|---:|
| Generation wall time | **16.72 h** | 25.30 h | 17.99 h |
| LLM requests | 1,659 | 1,839 | **1,626** |
| LLM cumulative time | 10.98 h | 13.36 h | **9.49 h** |
| Persisted match events | 舊 schema，無可比數字 | 47,520 | 43,740 |
| Match cumulative time | 舊 schema，無可比數字 | 8.63 h | 5.40 h |

5×40 相對 10×20：

- Wall time 少 **7.31 小時**，約降低 28.9%
- LLM requests 少 **213** 次
- LLM cumulative time 少 **3.87 小時**
- Match cumulative time 少 **3.23 小時**

### 頁面結論

在相近 regular candidate budget 下，5×40 同時得到更好的外部結果與較低的實際成本，是兩版 self-play 中明顯較好的配置。

### 建議視覺

左側畫 wall time bars，右側畫 final-test win rate bars。5×40 位於「成本接近基準、結果顯著優於舊版」的位置。

### 講者備註

10×20 run 曾中斷並恢復，manifest 雖為 complete，仍保留 snapshot mismatch failure 資訊，candidate artifacts 與成本包含 recovery overhead。因此 25.30 小時不能完全歸因於 10×20 配置。基準使用舊 timing schema，不能直接比較 persisted match event 數。

資料來源：[baseline timing](../../runs/20260911_072610_382082/timing.jsonl)、[self-play 10×20 timing](../../runs/20260923_134743_200030/timing.jsonl)、[self-play 5×40 timing](../../runs/20260925_134245_911171/timing.jsonl)、[self-play 10×20 manifest](../../runs/20260923_134743_200030/manifest.json)

---

## Slide 12｜結論與下一步

### 投影片文字

### 結論

- Fixed-roster 10×20 仍是最佳結果：**42.7%**。
- Self-play 5×40 已從 0% 提升到 **32.8%**，證明 self-play 可以產生外部勝場。
- 5×40 的改善可追溯到主動追擊敵人的 Code Reflection。
- 目前差距集中在 LightRush、HeavyRush 與 COAC。
- 最終族群仍有 4/5 最高同分，selection pressure 還不夠細。

### 建議下一個實驗

1. **先做 current-code fixed-roster 10×20 rerun**，建立同 commit、同 pipeline 的公平基準。
2. **Self-play snapshot 加入固定 anchors**，至少保留 LightRush、HeavyRush、WorkerRush 或 COAC。
3. **每次 snapshot refresh 加一個固定 holdout probe**，只監控、不參與 selection，及早發現外部能力退化。
4. **保留 5×40 搜尋規模**，因為成本與結果都優於 10×20 self-play。
5. **把 winless plateau 設為診斷條件**，若連續多代只有 draws，觸發攻擊能力檢查或 mutation bias。

### 頁面結論

下一階段不需要放棄 self-play；應保留 5×40 的探索深度，再用 fixed anchors 與 holdout probes 補上外部能力約束。

### 建議視覺

畫下一版 evaluation composition：self-play snapshot 為主體，旁邊加入固定 anchor opponents，外圈放不參與 selection 的 holdout probe。

---

## Appendix A｜完整 opponent 勝率比較

### 投影片文字

| Opponent | Fixed-roster wins | Self-play 10×20 wins | Self-play 5×40 wins | 5×40 與基準差 |
|---|---:|---:|---:|---:|
| PassiveAI | 60 | 0 | 60 | 0 |
| RandomAI | 59 | 0 | 60 | +1 |
| RandomBiasedAI | 57 | 0 | 57 | 0 |
| LightRush | 30 | 0 | 10 | -20 |
| HeavyRush | 40 | 0 | 10 | -30 |
| WorkerRush | 0 | 0 | 0 | 0 |
| AllInBot | 0 | 0 | 0 | 0 |
| Mayari | 0 | 0 | 0 | 0 |
| COAC | 10 | 0 | 0 | -10 |
| TMA | 0 | 0 | 0 | 0 |
| **Total** | **256** | **0** | **197** | **-59** |

### 解讀

5×40 與基準的總差為 59 勝，完全可由 RandomAI `+1`、LightRush `-20`、HeavyRush `-30`、COAC `-10` 解釋。

---

## Appendix B｜Run identity 與資料品質注意事項

### 投影片文字

| 項目 | 說明 |
|---|---|
| 基準選擇 | 依指定採 `20260911_072610_382082`，其搜尋 eval 使用多個固定 opponents，規模為 10×20 |
| 歷史版本限制 | 基準來自較早 repository state，不是與兩版 self-play 完全同 commit 的受控比較 |
| 5×40 命名 | source config 檔名為 `self_play_5x40.yaml`，resolved `experiment_name` 卻保留 `self_play_10x20` |
| 10×20 命名 | source config 檔名為 `self_play_10x20.yaml`，resolved `experiment_name` 卻保留 `self_play_5x40` |
| 判讀規則 | 本文件以 run ID 與 resolved generations/population 為準，不以 `experiment_name` 判斷 |
| 10×20 recovery | run 已完成，但 manifest 保留中斷時的 snapshot mismatch failure；成本含 recovery overhead |
| GP 比較 | Self-play GP 只可在相同 snapshot 內比較，不能與 fixed-roster GP 或不同 snapshot 直接比較 |
| 最安全比較 | 三組相同 600 場 fixed-roster final test 的 W/D/L |

### 頁面結論

本比較足以判斷最終外部表現，但若要把差距嚴格歸因於 evaluation mode，仍需在 current code 上重跑 fixed-roster control。

資料來源：[baseline manifest](../../runs/20260911_072610_382082/manifest.json)、[self-play 10×20 manifest](../../runs/20260923_134743_200030/manifest.json)、[self-play 5×40 manifest](../../runs/20260925_134245_911171/manifest.json)

---

## Appendix C｜一句話版本與 Q&A 備答

### 一句話版本

把 self-play 從 10×20 改成 5×40 後，外部勝率從 0% 提升到 32.8%，成本也下降，但仍未追上多固定對手 eval 基準的 42.7%。

### Q1：為什麼 5×40 比 10×20 好？

現有 artifact 顯示，關鍵差異是 G17 的 Code Reflection 補上了主動追擊與攻擊最近敵人的能力；更多 generations 讓這個 mutation 有機會出現並在後續 snapshot 中被保留。這是有證據支持的機制解釋，但尚未經同 seed ablation 證明唯一因果。

### Q2：為什麼 fixed-roster 還是更好？

固定 opponents 持續提供 LightRush、HeavyRush、COAC 等外部能力壓力。純 self-play 的 selection 只需要超越當期 snapshot，容易失去對外部策略的 coverage。

### Q3：可以直接比較三個 run 的 GP 嗎？

不可以。Fixed-roster 與 self-play 使用不同 evaluation context，self-play 每次 snapshot refresh 又會改變 fitness 語境。跨 run 應以共同的 600 場 final test 比較。

### Q4：下一個最重要的實驗是什麼？

先用 current code 重跑 fixed-roster 10×20 control，再測試「5×40 self-play 加固定 anchors」。這能把版本差異與 evaluation-mode 差異拆開。
