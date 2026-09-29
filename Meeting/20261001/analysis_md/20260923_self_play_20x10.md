# EAGLE Self-play 20x10 實驗簡報內容

日期：2026-09-25

Run：`20260923_134743_200030`

主題：immutable-snapshot self-play 的搜尋行為與外部泛化結果

形式：投影片內容草稿，不含簡報版面製作

建議長度：12 張主簡報，加 3 張附錄，約 12 至 18 分鐘

---

## Slide 1｜Self-play 20x10 實驗

### 標題

Self-play 提高對內相對分數，但沒有產生外部勝場

### 副標題

20 代、族群大小 10、每 5 代更新 opponent snapshot、Ministral 3 8B

### 講者備註

本次實驗首次完整執行 EAGLE 的 immutable-snapshot self-play。簡報重點不是單看跨代分數，而是檢查 self-play 的選擇壓力是否轉化為對固定 MicroRTS 對手的勝場。

資料來源：[run config](../../runs/20260923_134743_200030/config.yaml)、[run summary](../../runs/20260923_134743_200030/summary.json)

---

## Slide 2｜結論摘要

### 投影片文字

這次 run 完成 20 代搜尋，但 self-play 成果沒有轉移到外部測試。

| 指標 | 結果 |
|---|---:|
| Final self-play，測試 agent 對 snapshot | **0 勝 / 180 和 / 0 敗** |
| Fixed-roster final test | **0 勝 / 151 和 / 449 敗** |
| Final-test 勝率 | **0%** |
| 可擊敗的固定對手 | **0 / 10** |
| 最終族群相同最高 fitness vector | **7 / 10 candidates** |
| 最終族群 strategy niches | **4** |

### 頁面結論

Self-play 找到能與自身族群長時間和局的策略，沒有找到能擊敗外部對手的策略。

### 建議視覺

左側放 `0 / 180 / 0`，右側放 `0 / 151 / 449`。使用同一個 W/D/L 順序與相同總寬度，直接呈現對內與對外的差異。

### 講者備註

最終 self-play 的 aggregate Game Performance 為 `0.037259`，全部勝負結果都是和局。正分只來自 shaping terms，不代表實際勝場。

資料來源：[tested candidate self-play evaluation](../../runs/20260923_134743_200030/candidates/gen_0020_ee9b19ad3dc8/evaluation/game_performance.json)、[final-test summary](../../runs/20260923_134743_200030/final_test/final_test_summary.json)

---

## Slide 3｜實驗設計

### 投影片文字

| 項目 | 設定 |
|---|---|
| 搜尋方法 | opponent-wise lexicase、`mu_plus_lambda` |
| 搜尋規模 | 20 代，每代 10 個 offspring，族群大小 10 |
| 初始族群 | 10 個 LLM-generated policies，Worker Rush policy 作為 seed prompt |
| Java 模式 | `inherited_genotype`，父代預設 `reuse_cached` |
| Self-play opponent | 10 個等權重 slots |
| Snapshot 更新 | generation 0、5、10、15、20 |
| 單一 candidate 評估 | 10 opponents × 3 maps × 3 rounds × 2 sides，共 180 場 |
| Mutation 配置 | Strategy 0.33、Prompt 0.33、Code 0.34 |

三張地圖為 8×8、16×16、24×24。LLM 使用 Ministral 3 8B，`parallel: 1`。

### 頁面結論

每個五代區間使用同一份 immutable opponent snapshot。Snapshot 更新後，父代必須在新 context 重新評估，才能與 offspring 一起進行 selection。

### 建議視覺

以時間軸標示 `G0`、`G5`、`G10`、`G15`、`G20` 五次 snapshot，兩個 snapshot 之間標成同一個可比較區間。

### 講者備註

Self-play slots 的名稱固定為 `self_play_000` 到 `self_play_009`，但背後 candidate 會隨 snapshot 更新。不同 snapshot 的分數基準不同，因此不能把 generation 0 到 20 畫成一條可直接比較的學習曲線。

資料來源：[resolved config](../../runs/20260923_134743_200030/config.yaml)、[snapshot artifacts](../../runs/20260923_134743_200030/generations/)

---

## Slide 4｜Self-play snapshot 的實際組成

### 投影片文字

| Snapshot | 建立來源 | Unique source candidates | 說明 |
|---:|---|---:|---|
| G0 | Generation 0 runnable population | 6 | 4 個初始 candidate 失敗，6 個來源循環填滿 10 slots |
| G5 | Generation 4 population | 10 | 首次完整 10-agent snapshot |
| G10 | Generation 8–9 survivors | 10 | 4 個來源生於 G8，6 個生於 G9 |
| G15 | Generation 12–14 survivors | 10 | 保留跨代 survivor |
| G20 | Generation 17–19 survivors | 10 | 作為最終 selection context |

標準 snapshot refresh 會建立 10 個 fresh-ID parent replicas，重新取得新 context 下的 fitness。本 run 在 G5、G10、G15、G20 各留下 10 份 records，另有 G4 same-context repair 的 10 份 records，合計 50 份。

### 頁面結論

初始 self-play 的競爭環境只有 6 個可執行來源，而且沒有固定外部對手提供能力下限。

### 建議視覺

五個 snapshot 依序排列。G0 只畫 6 個不同顏色的圓點，再循環補到 10 格。後續 snapshot 各畫 10 個來源。

### 講者備註

G0 的限制不是 self-play 機制錯誤，而是 bootstrap pool 偏小。這會讓早期 selection 只回答「誰比較能對付目前這六種 agent」，無法回答「誰能擊敗固定 baseline」。

資料來源：[G0 snapshot](../../runs/20260923_134743_200030/generations/generation_0000_self_play_snapshot.json)、[G5 snapshot](../../runs/20260923_134743_200030/generations/generation_0005_self_play_snapshot.json)、[G10 snapshot](../../runs/20260923_134743_200030/generations/generation_0010_self_play_snapshot.json)、[G15 snapshot](../../runs/20260923_134743_200030/generations/generation_0015_self_play_snapshot.json)、[G20 snapshot](../../runs/20260923_134743_200030/generations/generation_0020_self_play_snapshot.json)

---

## Slide 5｜每個固定 snapshot 內都有相對進步

### 投影片文字

Game Performance 越高越好。每列只比較同一份 opponent snapshot 內的起點與終點。

| 固定 context | Best GP | Mean GP | 判讀 |
|---|---:|---:|---|
| G0 至 G4 | 1.442 → **7.354** | -399.893 → **2.625** | Mean 起點受 4 個 `-1000` failure sentinels 影響 |
| G5 至 G9 | 0.185 → **3.794** | 0.185 → **1.119** | Best 與 mean 都提高 |
| G10 至 G14 | 0.195 → **0.620** | 0.195 → **0.238** | 改善較小，族群大多維持同分 |
| G15 至 G19 | 1.063 → **1.305** | 0.124 → **1.263** | 後段族群快速集中到高分區 |
| G20 | **0.037** | **0.021** | 新 snapshot 的單代結果，不能與 G19 直接比較 |

### 頁面結論

Search 能在每份 frozen opponent set 上提高相對 fitness，但這項證據只支持 within-snapshot adaptation。

### 建議圖表

畫四個獨立的小折線區間，不要用一條連續折線跨越 refresh boundary。G0 至 G4 的 mean 另加註 failure sentinel。

### 講者備註

G5、G10、G15、G20 都更換了 opponent context。分數在 refresh 後改變，不等於能力突然退步。跨 context 的能力比較必須使用固定對手或獨立 holdout。

資料來源：[generation metrics](../../runs/20260923_134743_200030/analysis/generation_metrics.csv)、[generation artifacts](../../runs/20260923_134743_200030/generations/)

---

## Slide 6｜Final test 沒有任何勝場

### 投影片文字

測試 candidate：`gen_0020_ee9b19ad3dc8`

| 指標 | 結果 |
|---|---:|
| 總場數 | 600 |
| W / D / L / E | **0 / 151 / 449 / 0** |
| 勝率 | **0%** |
| 不敗率 | 25.2% |
| p0 W / D / L | 0 / 78 / 222 |
| p1 W / D / L | 0 / 73 / 227 |

按地圖：

| 地圖 | W / D / L | 不敗率 |
|---|---:|---:|
| 8×8 | 0 / 35 / 165 | 17.5% |
| 16×16 | 0 / 57 / 143 | 28.5% |
| 24×24 | 0 / 59 / 141 | 29.5% |

### 頁面結論

較大地圖增加 timeout draws，沒有帶來勝場。Player side 也沒有改變結論。

### 建議視覺

用三條 100% stacked bars 呈現三張地圖的 draw 與 loss。Win 維持為零，不要省略。

### 講者備註

Final test 通過 integration，600 場沒有 candidate error，也沒有 opponent fault。這是策略能力不足，不是測試執行失敗。

資料來源：[final-test CSV](../../runs/20260923_134743_200030/final_test/final_test_results.csv)、[final-test summary](../../runs/20260923_134743_200030/final_test/final_test_summary.json)

---

## Slide 7｜只有三個基礎對手出現和局

### 投影片文字

每個 opponent 共 60 場，數字為 W / D / L。

| Opponent | W / D / L | 不敗率 |
|---|---:|---:|
| PassiveAI | 0 / 60 / 0 | 100.0% |
| RandomAI | 0 / 53 / 7 | 88.3% |
| RandomBiasedAI | 0 / 38 / 22 | 63.3% |
| LightRush | 0 / 0 / 60 | 0% |
| HeavyRush | 0 / 0 / 60 | 0% |
| WorkerRush | 0 / 0 / 60 | 0% |
| AllInBot | 0 / 0 / 60 | 0% |
| Mayari | 0 / 0 / 60 | 0% |
| COAC | 0 / 0 / 60 | 0% |
| TMA | 0 / 0 / 60 | 0% |

### 頁面結論

Agent 能拖住不主動進攻的對手，遇到任何 rush 或完整戰術 agent 都是 60 場全敗。

### 建議視覺

使用水平 stacked bar。由 Passive、Random、RandomBiased 到其餘七個對手排列，讓「和局能力」與「勝局能力」分開呈現。

### 講者備註

PassiveAI 的 60 場全和不能視為競爭力。Random 類對手的結果也只有和局，沒有轉成任何勝場。

資料來源：[final-test results](../../runs/20260923_134743_200030/final_test/final_test_results.md)

---

## Slide 8｜Self-play 的選擇訊號來自 shaping score

### 投影片文字

Final-test candidate 在最後一份 self-play snapshot 的 180 場結果：

| 指標 | 結果 |
|---|---:|
| Wins | 0 |
| Draws | **180** |
| Losses | 0 |
| Mean result score | **0.000** |
| Mean material score | +0.083 |
| Mean final-resource score | -0.046 |
| Aggregate Game Performance | **+0.037** |

十個 self-play cases 中，前五個 case 分數為 0；其餘五個只保留小幅 shaping 優勢，最高為 `0.102692`。

### 頁面結論

最後一代沒有勝負訊號。Lexicase 主要依靠微小的 material shaping 差異排序，容易選出能維持和局但不會終結比賽的 agent。

### 建議視覺

左側顯示 180 場全部為 draw。右側將 `+0.083` 與 `-0.046` 相加成 `+0.037`，標示這是 shaping 結果，不是 win score。

### 講者備註

這個結果能解釋為什麼 self-play fitness 仍為正數。Side swap 讓多數對稱對局互相抵消，只有少數 phenotype 間的材料與資源差異留下很小的 case score。

資料來源：[self-play evaluation](../../runs/20260923_134743_200030/candidates/gen_0020_ee9b19ad3dc8/evaluation/game_performance.json)

---

## Slide 9｜最終策略缺少可完成勝局的戰鬥行為

### 投影片文字

Final-test candidate 的 policy 只有 10 條規則：

- Light 只攻擊距離 1 內的 enemy Worker，或基地附近距離 2 內的 enemy Worker
- Ranged 只攻擊已在射程內的 enemy Worker
- Heavy 可以被生產，但沒有任何 Heavy 行動規則
- 沒有一般性的尋敵、接近敵人、攻擊建築或清除非 Worker 單位規則
- 未命中上述條件的 idle units 最後執行 idle

診斷分數仍然偏高：

| Diagnostic | 分數 |
|---|---:|
| Function Capability | 100 / 100 |
| Strategy Alignment | 8 / 10 |
| Code Quality | 31.31 |

### 頁面結論

程式能編譯、能呼叫合法 action，也忠實執行狹窄 policy，但這些診斷沒有保證 policy 能擊敗對手。

### 建議視覺

左側放 policy 規則覆蓋圖，將 Harvest、Produce、近距離 anti-worker 標成已覆蓋。將 pursuit、building attack、Heavy control 標成缺口。右側放三個診斷分數與 `0 wins`。

### 講者備註

這是本次最直接的 phenotype 證據。Self-play 對手也缺少積極終結能力時，這類被動策略可以靠和局與 shaping score 留在族群中。

資料來源：[policy prompt](../../runs/20260923_134743_200030/candidates/gen_0020_ee9b19ad3dc8/genotype/policy_prompt.txt)、[generated Java](../../runs/20260923_134743_200030/candidates/gen_0020_ee9b19ad3dc8/phenotype/CandidateAgent.java)、[code quality](../../runs/20260923_134743_200030/candidates/gen_0020_ee9b19ad3dc8/evaluation/code_quality.json)

---

## Slide 10｜最終族群出現 fitness plateau

### 投影片文字

Generation 20 survivor population：

| 指標 | 結果 |
|---|---:|
| Population size | 10 |
| 相同最高 fitness vector | **7 candidates** |
| 最高 aggregate GP | 0.037259 |
| Unique strategy niches | 4 |
| Unique Java phenotype hashes | 7 |
| Top fitness group 的 unique Java hashes | 4 |

七個 top candidates 共享同一個 strategy niche 與完全相同的十維 objective vector，但其中仍包含四份不同 Java phenotype。

### 頁面結論

目前 self-play matrix 無法區分多個不同 phenotype。大面積同分使 lexicase 的選擇壓力變弱，也讓「best candidate」依賴 tie handling。

### 建議視覺

畫 10 個候選點。前 7 個放在同一 fitness 高度，依 Java hash 分成 4 種色彩；其餘 3 個放在較低高度。

### 講者備註

`generation_0020.json` 將 `gen_0020_33346fff3c86` 記為 best，但 run summary 與 final test 選用 `gen_0020_ee9b19ad3dc8`。兩者 objective vector 相同，因此不影響「0 勝」結論，但顯示最終 winner 並不唯一。

資料來源：[generation 20](../../runs/20260923_134743_200030/generations/generation_0020.json)、[run summary](../../runs/20260923_134743_200030/summary.json)

---

## Slide 11｜目前結果支持的解釋

### 投影片文字

最符合現有證據的機制：

1. 初始 snapshot 只有 6 個 runnable agents，而且沒有固定外部能力錨點
2. 族群逐步共享相似的被動行為，彼此對戰大量進入 timeout draw
3. 勝負訊號消失後，selection 轉而放大小幅 shaping 差異
4. 多個不同 phenotype 得到相同 fitness vector，族群形成 plateau
5. 最終 agent 能維持對內和局，但無法擊敗固定對手

### 頁面結論

這次 run 證明 snapshot self-play pipeline 可以完成搜尋，也暴露純 self-play 的 bootstrap 與 objective degeneracy 問題。

### 建議視覺

使用五段因果鏈，從弱 bootstrap pool 排到 final-test 0 wins。每段只放一個主詞與一個觀察值。

### 講者備註

這是單一 run 的機制解釋，不是已完成的因果證明。需要對照實驗區分 self-play opponent choice、refresh interval、fitness shaping 與 initial population quality 的影響。

---

## Slide 12｜下一輪實驗設計

### 投影片文字

優先執行 hybrid evaluation，而不是直接增加 generations：

| 變更 | 目的 | 驗證指標 |
|---|---|---|
| 保留 self-play slots，加入 2 至 4 個固定 anchor opponents | 防止族群共同退化成被動和局 | Anchor win rate、case-wise maxima |
| 將每次 snapshot 的 champion 放入跨代 archive | 保留歷史壓力，減少只適應最近族群 | 對 archive 的勝率矩陣 |
| 將 win/loss 與 shaping 分開記錄 | 避免正 GP 被誤讀為勝局能力 | Win count、draw count、shaping-only GP |
| Tie 時優先保留行為或 phenotype 多樣性 | 降低七個 candidates 同 vector 的 plateau | Unique objectives、niches、Java hashes |
| 每個 snapshot 結束後跑小型 fixed-roster probe | 提前偵測外部能力退化 | 30 至 60 場 probe trend |

### 頁面結論

下一個高價值問題是：少量固定 anchors 能否保留 self-play adaptation，同時恢復可泛化勝場。

### 建議視覺

以 hybrid opponent pool 示意圖呈現 self-play agents、historical archive 與 fixed anchors 三種來源。主視覺放在同一個 opponent pool，不要拆成多個 UI cards。

### 講者備註

建議先做小規模 5 代實驗確認 victory signal 是否恢復，再決定是否投入完整 20 代。主要成功條件應是 fixed-roster 勝場，而不是 self-play aggregate GP。

---

# 附錄

## Appendix A｜Run 完整性與資料品質注意事項

### 投影片文字

| 項目 | 觀察 | 簡報處理方式 |
|---|---|---|
| Run status | `status: complete`，完成 generation 20 | 視為完整 run |
| Manifest failure fields | 保留一次 same-context guard 的 `ValueError` 與 timestamp | 視為中斷後恢復的歷史紀錄 |
| `analysis/summary.md` | 顯示 completed generations 0、final candidates 0 | 不採用這兩個欄位 |
| `candidate_summary.csv` | 只有 `no_data` | 改讀 generation 與 candidate artifacts |
| `error_statistics.csv` | 只列 5 個 unknown errors | 不用來計算完整 failure rate |
| Experiment name | resolved config 寫 `self_play_5x40`，實際參數為 20 generations × population 10 | 全文以 run ID 與實際參數識別 |
| Best candidate | generation artifact 與 run summary 指向不同 tied candidate | Final-test 報告以實際測試 candidate 為準 |

### 頁面結論

這份簡報的數字以 config、generation JSON、candidate evaluation 與 final-test artifacts 交叉核對，不直接採用 self-play 尚未完整支援的 analysis 摘要欄位。

### 講者備註

這些問題影響自動摘要與 run 命名，不影響 final-test 的 600 場 W/D/L，也不影響最後一代 self-play 180 場全和的核心證據。

資料來源：[manifest](../../runs/20260923_134743_200030/manifest.json)、[analysis summary](../../runs/20260923_134743_200030/analysis/summary.md)、[candidate summary](../../runs/20260923_134743_200030/analysis/candidate_summary.csv)

---

## Appendix B｜執行成本

### 投影片文字

| 指標 | 結果 |
|---|---:|
| Generation 0 加 20 個 evolutionary generations | 21 個 generation records |
| Recorded generation wall time 合計 | **25.30 小時** |
| LLM requests | **1,839** |
| LLM request 累積時間 | **13.36 小時** |
| Match 累積時間 | **8.63 小時** |
| Self-play snapshots | 5 |
| Parent fitness-refresh records | 50 |
| Final test | 600 matches |

Refresh generations 的工作量較高：G5、G10、G15、G20 需要在新 context 評估父代 replicas 與 offspring。

### 頁面結論

增加 generations 會線性放大成本，但目前主要瓶頸是 selection signal，不是搜尋長度不足。

### 講者備註

LLM 與 match 累積時間是各 operation duration 的加總，用於理解成本組成。Generation wall time 是每代完成時間的加總，不應再與前兩者相加。

資料來源：[timing statistics](../../runs/20260923_134743_200030/analysis/timing_statistics.csv)、[parent refresh artifacts](../../runs/20260923_134743_200030/generations/)

---

## Appendix C｜可直接引用的核心數字

### 投影片文字

| 問題 | 數字 | 判讀 |
|---|---:|---|
| Pipeline 是否完成 | G20 complete | Self-play 流程可執行 |
| 對內是否有相對改善 | 四個 frozen windows 皆提高 best GP | 能適應當前 snapshot |
| 最終對內勝場 | 0 / 180 | 沒有 victory signal |
| 最終對外勝場 | 0 / 600 | 沒有外部泛化勝場 |
| Rush 與高階對手 | 7 opponents × 60 場全敗 | 主要能力缺口 |
| Top fitness tie | 7 / 10 candidates | Selection plateau |
| Final strategy niches | 4 | 有描述層差異，但 objective 區辨力不足 |
| Final unique Java | 7 | Phenotype 不同仍可能得到相同 fitness |

### 一句話結論

本次 pure self-play 成功運作，但收斂到互相和局的族群；下一輪需要固定 anchors 或歷史 archive，讓勝局能力重新進入 selection signal。

---

## 數據口徑

- `W / D / L` 固定表示 win / draw / loss。
- Self-play 的 Game Performance 使用十個等權重 snapshot cases 的平均。
- 不同 snapshot context 的 Game Performance 不直接比較。
- Final test 使用 10 個固定 opponents、3 張地圖、每張地圖兩個 player sides 各 10 場，共 600 場。
- 本文件中的「tested candidate」固定指 `gen_0020_ee9b19ad3dc8`。
- `generation_0020.json` 另將同分的 `gen_0020_33346fff3c86` 記為 best candidate。
