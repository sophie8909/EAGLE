# EAGLE 更新紀錄：2026/10/22–10/28

## 1. 更新總覽

本階段的主要方向，是從固定 Framework 下的 Local Evolution，擴展為能結合 LLM Coach、語意相似度選親，以及定期更新整個 Framework 的演化架構。

| 日期 | 類別 | 主要變動 |
|---|---|---|
| 10/22 | 演算法 | 新增 Coach 50% / Traditional 50% 互斥繁殖路徑 |
| 10/22 | 演算法 | Candidate ID 改為明確、決定論產生 |
| 10/22 | 架構 | Fresh / Resume 共用演化迴圈 |
| 10/22 | 實驗 | 擴充 Framework Stability seeds 14–17 |
| 10/22 | 實驗 | 新增 seeds 8、13 各兩次重複實驗 |
| 10/23 | 實驗 | 新增 Serial Match Execution |
| 10/23 | 實驗 | 新增 2 Generation × 3 Population 小型測試 |
| 10/23 | 演算法 | Parent B 改為選擇語意最接近的不同個體 |
| 10/23 | 實驗 | 新增六組 seeds 8–13 的 Nearest-Behavior Local Evolution |
| 10/24 | 演算法 | 新增 Whole-Framework Reflection |
| 10/24 | 演算法 | 新增 Strategy Description Reflection 與 Framework Migration |
| 10/24 | 實驗 | 新增 Framework Reflection 六組 Seed 設定 |
| 10/24 | 實驗管理 | 整理 48 個 manifest-backed runs |
| 10/26 | 推論後端討論 | 評估使用 Codex CLI 取代部分付費 LLM API |

---

## 2. 演算法變動

### 2.1 Coach 與 Traditional 雙繁殖路徑（10/22）

新增參數：

`framework.coach_offspring_probability`

讓 `llm_coach` 模式可以在建立子代時，選擇兩種互斥的繁殖路徑。

#### Traditional Route

1. 選擇 Parent A。
2. 按既有選親方法選擇 Parent B。
3. 根據 `crossover_rate` 執行逐槽交配。
4. 根據 `mutation_rate` 執行 Local Single-Slot Mutation。
5. 產生完整 `control_genome`。

#### Coach Route

1. 選擇 Parent A。
2. 複製 Parent A 的完整 Genome。
3. 根據既有 Worst-Match Evaluation Evidence，透過 Coach 產生新的完整 Genome。
4. 驗證新 Genome 是否符合 Framework Slot Schema。
5. 將合法 Genome 轉換為 Java。

Coach Route 不使用 Parent B，也不執行 Crossover。

#### 參數規則

| 參數 | 意義 |
|---|---|
| `0.0` | 子代全部走 Traditional Route |
| `0.5` | 每個子代有 50% 機率走 Coach Route |
| `1.0` | 子代全部走 Coach Route |
| `null` | 保留原本的 Legacy Coach 行為 |

路徑選擇使用獨立的 Seeded RNG，與 `mutation_rate` 無關。

50% 是每個子代的機率，不保證每一代剛好一半。

Generation 0 仍由 Coach 產生初始 Genome。

#### 與舊版差異

舊版 Coach 是在 Crossover 後執行的 Strategy Mutation。

新版可將 Coach 視為獨立的 Offspring Generation Operator，避免 Coach 生成的完整 Genome 覆蓋掉剛完成的 Crossover 結果。

---

### 2.2 Parent B 改為 Nearest-Behavior Mating（10/23）

原本在 Self-Play 的同適應度候選中，偏向選擇語意距離較遠的個體。

新版改為：

**Parent B 優先選擇與 Parent A 行為最接近、但不是 Parent A 本身的個體。**

#### Selection 流程

1. 依照 Scalar Game Performance 建立最高適應度 Tier。
2. 使用 `fitness_tie_tolerance = 1.0` 判定同級候選。
3. 如果同級有其他個體，排除 Parent A。
4. 計算與 Parent A 的 Behavior Signature Distance。
5. 選擇最小相容距離的 Candidate。
6. 距離相同時，依 Candidate ID 排序後使用 Seeded RNG 選擇。
7. 如果沒有相容 Signature，使用既有 Fallback。
8. 若最高 Tier 只有 Parent A，允許重用 Parent A。

#### Mating 與 Survivor Selection 的區別

| 階段 | 選擇原則 | 目的 |
|---|---|---|
| Parent B Selection | Minimum Semantic Distance | 交配相似策略 |
| Survivor Boundary Selection | Maximum-Minimum Semantic Distance | 保留族群行為多樣性 |

也就是：

- 交配時偏向利用相似策略。
- 生存者選擇時仍盡可能保留不同策略。
- Semantic Signature 不構成第二個最佳化目標。
- Fixed-Roster Lexicase Selection 不受影響。

---

### 2.3 Deterministic Candidate Identity（10/22）

修改 Candidate ID 的產生方式，避免使用 Process-Random UUID。

新建 Candidate ID 格式：

`gen_<generation>_<12-hex-deterministic-suffix>`

ID 由 Root Seed 與穩定的 Lineage Identity 推導。

主要改動：

- 所有 Candidate 必須具有明確且非空的 ID。
- `Candidate` 不再自行產生隨機 ID。
- 相同 Seed 與 Lineage 可重現相同 ID。
- 從既有 Artifact 或 Resume 載入的 ID 保持不變。

此變動改善實驗可重現性，以及 Candidate 與 Artifact 的追蹤能力。

---

### 2.4 Whole-Framework Reflection（10/24）

新增：

`framework.evolution_mode: reflection`

這是本階段最大的演算法架構變動。

原本 `local` 模式會固定整個 Framework，只演化其中的 Typed Slot Genome。

新版 Reflection Mode 允許 LLM 在演化過程中，重新設計完整 Framework。

#### Framework Initialization

1. 使用 Groq `openai/gpt-oss-120b` 產生初始 Framework。
2. Framework 定義 Java Agent 結構及有限的 Typed Slots。
3. Generation 0 使用十份預先定義、彼此不同的 Strategy Description。
4. 其中一份以 MicroRTS WorkerRush 為基礎。
5. 本地 Qwen Coach 依照各 Strategy Description 選擇完整 Slot Genome。
6. 產生十個初始 Candidate。

初始 Strategy Description 記錄於：

`prompts/framework_initial_strategies.txt`

#### Framework Reflection Timing

每五代執行一次 Framework Reflection，與 Opponent Snapshot Refresh 同步。

| 時點 | 行為 |
|---|---|
| G0 | 初始化 Framework 與 Population |
| G1 | 初始化 Self-Play Opponent Snapshot |
| G6 | 使用 G5 Survivors 反思 Framework |
| G11 | 使用 G10 Survivors 反思 Framework |
| G16 | 使用 G15 Survivors 反思 Framework |
| G20 結束 | 不再額外執行 Reflection |

#### Reflection Input

使用上一個已完成世代的全部 Survivor：

- Strategy Description
- 完整 Control Genome
- Fitness
- 當前 Framework

由本地 Qwen3.5-9B 產生新的 Framework。

LLM 可以修改：

- Framework Java 架構
- Slot 數量
- Slot 類型與合法選項
- Slot Domain
- 戰鬥、經濟、生產、撤退等策略規則

但仍須符合 Framework Bundle Schema 及 CandidateAgent 的介面與安全限制。

#### Validation 與 Repair

每次 Framework 更新必須經過：

1. Bundle Schema Validation
2. Java Validation
3. Java Compilation
4. Default Genome 檢查
5. Slot Choices 與 Numeric Endpoints 檢查
6. Coach-selected Transition Genome 檢查

第一次提案失敗後，最多再進行三次診斷導向修復。

若全部失敗，保留舊 Framework，繼續演化。

此驗證不代表已窮舉所有 Slot 組合。

---

### 2.5 Strategy Reflection 與 Framework Migration（10/24）

Framework 變更後，舊的 Genome 不一定符合新 Slot Schema，因此新增獨立的 Strategy Revision 與 Migration 流程。

#### Strategy Revision

本地 Qwen 讀取舊世代所有 Candidate 的：

- Strategy Description
- Genome
- Fitness
- 舊 Framework

然後為每個來源個體產生更新後的自然語言策略描述。

所有來源 ID 都必須有對應描述，但後續描述允許重複。

#### Framework Migration

另一個獨立 Coach 階段使用：

- 舊 Framework
- 新 Framework
- 修改後的 Strategy Description

為每個來源 Candidate 選出符合新 Framework 的完整 Genome。

Migration 不直接使用預設值填補不相容 Slots。

新的 Genome 驗證通過後，建立新的 Parent Replica，並在新的 Opponent Context 下重新評估。

#### Strategy Description 的定位

每個 Candidate 新增保存：

`strategy_description`

但是：

- 真正執行的 Genotype 仍為 `control_genome`。
- Local Crossover / Mutation 不修改 Description。
- Local Offspring 繼承 Parent A 的 Description。
- Description 不直接編譯為 Java。

這使策略意圖可以跨 Framework 版本保存，但不保證描述永遠完全符合 Local Mutation 後的實際行為。

---

## 3. 實驗設計變動

### 3.1 Framework Stability 實驗擴充（10/22）

新增四個 Random Seeds：

`[14, 15, 16, 17]`

主要設定：

| 項目 | 設定 |
|---|---|
| Model | Qwen3.5-9B |
| Generations | 20 |
| Population | 10 |
| Runs per seed | 1 |
| Evolution | Framework Slots / Local |
| Evaluation | Self-Play |
| Framework | Fixed Worker Combat |
| Crossover | 0.75 |
| Mutation | 1.0 |

目的：擴大不同 Random Seeds 的表現觀察範圍。

---

### 3.2 Same-Seed Repeatability（10/22–10/23）

新增 Seeds 8、13 的重複實驗。

起始設定：

`random_seeds: [8, 13]`

`runs: 2`

代表執行：

`8, 8, 13, 13`

10/23 曾暫時提高為每個 Seed 三次，隨後恢復兩次。

目的：分析相同 Random Seed 是否能重現一致的實驗結果。

---

### 3.3 Serial Match Execution（10/23）

新增評估設定：

`evaluation.match_execution: serial`

原本預設使用 Parallel Match Evaluation。

新版增加 Serial 選項，讓對戰按照固定順序逐場執行。

| 模式 | Match Workers |
|---|---:|
| `parallel` | 10 |
| `serial` | 1 |

目的：

- 降低多執行緒／程序排程造成的變異。
- 改善相同 Seed 的實驗一致性。
- 方便進行 Reproducibility Audit。

此功能不修改 Fitness Formula。

---

### 3.4 Small-Scale Reproducibility Experiments（10/23）

新增兩代、三個體的小型實驗。

主要設定：

| 項目 | 設定 |
|---|---|
| Generations | 2 |
| Population | 3 |
| Seeds | 8、13 |
| Runs per seed | 2 |
| Total scheduled runs | 4 |

另有 Seed 8 的 Smoke Test 設定。

目的：在較短時間內測試 Evolution Pipeline 與 Same-Seed Repeatability，減少完整 20 代實驗的除錯成本。

---

### 3.5 Nearest-Behavior Local Evolution（10/23）

新增：

`qwen3_5_9b_rich_framework_local_nearest_20x10_seed8_13_1run`

主要設定：

| 項目 | 設定 |
|---|---|
| Model | Qwen3.5-9B |
| Generations | 20 |
| Population | 10 |
| Seeds | 8–13 |
| Runs per seed | 1 |
| Crossover Rate | 0.75 |
| Mutation Rate | 1.0 |
| Evolution Mode | Local |
| Evaluation Mode | Self-Play |
| Opponent Pool Capacity | 50 |
| Opponent Refresh Interval | 5 |
| Coach | Disabled |
| Match Commentator | Disabled |
| Selection | Nearest-Behavior Mating |

使用三張地圖：

- 8×8：1,500 ticks
- 16×16：3,000 ticks
- 24×24：4,000 ticks

此組實驗著重檢驗新的語意距離選親規則。

---

### 3.6 Framework Reflection Experiments（10/24）

新增：

`qwen3_5_9b_rich_framework_reflection_20x10_seed8_13_1run`

| 項目 | 設定 |
|---|---|
| Initial Framework Model | GPT-OSS-120B via Groq |
| Local Reflection Model | Qwen3.5-9B |
| Generations | 20 |
| Population | 10 |
| Seeds | 8–13 |
| Runs per seed | 1 |
| Evolution Mode | Reflection |
| Framework Refresh | Every 5 generations |
| Context Size | 65,536 |
| Crossover | 0.75 |
| Mutation | 1.0 |
| Evaluation | Self-Play |

實驗用於測試：

1. 初始策略描述能否產生有效 Genome。
2. 整個 Framework 是否能在演化中修改。
3. 新舊 Framework 之間的 Genome Migration。
4. Framework Reflection 是否能提升後續搜尋表現。
5. Framework 更新失敗時是否能安全保留舊版本。

**狀態：已新增實作與實驗設定；尚無足夠資料確認六組正式實驗全部完成。**

---

## 4. 實驗結果與可重現性

### 4.1 10/24 實驗索引快照

當時整理的 Run 狀態：

| 狀態 | 數量 |
|---|---:|
| Manifest-backed runs | 48 |
| Complete | 42 |
| Running | 2 |
| Initialized | 3 |
| Interrupted | 1 |
| 非標準資料目錄 | 4 |

這是 10/24 建立索引時的快照，不代表 10/28 的即時執行狀態。

### 4.2 主要實驗組別

以下數值為實驗索引所記錄的 Best Fitness 平均值。

| 實驗組別 | 完成數 / 紀錄數 | Mean Best Fitness |
|---|---:|---:|
| Rich Framework Local — Seed 8 | 2/2 | 1.272 |
| Rich Framework Local — Seed 9 | 1/1 | 25.733 |
| Rich Framework Local — Seed 10 | 1/1 | -32.037 |
| Rich Framework Local — Seed 11 | 1/3 | 10.988 |
| Rich Framework Local — Seed 12 | 1/1 | 6.761 |
| Rich Framework Local — Seed 13 | 1/1 | 18.267 |
| Framework Stability — Seeds 8–13 | 12/13 | 4.758 |
| Framework Stability — Seeds 8、13 重複組 | 4/5 | 12.488 |
| Framework Stability — Seeds 14–17 | 4/4 | -8.499 |
| Nearest-Behavior Local | 6/7 | 10.688 |

注意：

- 以上包含 10/22 之前啟動的實驗，不全是本階段新產生的結果。
- 平均值由不同完成 Run 的 Best Fitness 組成。
- 不同實驗未必具有完全相同的對手快照，因此不應直接視為公平的演算法效能比較。
- 尚未建立足夠證據證明 Nearest-Behavior Selection 優於舊 Selection。
- Framework Reflection 的最終正式實驗結果仍待確認。

---

## 5. 工程架構與 Artifact 變動

### 5.1 Fresh / Resume Loop 統一

新增共用演化迴圈：

`eagle/evolution/loop.py`

Fresh Search 與 Resume Search 改為共用 Generation Iteration 與 Finalization。

改善：

- 減少兩份演化流程的重複程式。
- 降低 Resume 與 Fresh Run 執行行為不一致的風險。
- 改善 Stagnation、Checkpoint 與 Interrupted Run 的重現性。

### 5.2 Experiment Index 解耦

新增：

`eagle/experiment_index.py`

將實驗索引辨識與驗證從主要 Experiment Execution 分離。

避免 GUI 載入 Run 資訊時額外載入完整演化執行模組。

### 5.3 Framework Version Artifacts

Whole-Framework Reflection 新增版本管理。

通過驗證的 Framework 儲存於：

`framework/versions/<sha256>/bundle.json`

Reflection Evidence 儲存於：

`framework/reflections/generation_<nnnn>/invocation_<nnn>/`

保存內容包括：

- 原 Framework
- Survivor Genomes / Fitness
- LLM Requests / Responses
- 修復紀錄
- Validation / Compilation Results
- Strategy Revision
- Coach Migration Evidence
- Framework Activation Result

Framework 版本只在完成的 Generation Snapshot 中生效。

Resume 使用 Checkpoint 指定的版本，不會因未完成的 Reflection Artifact 而誤啟用新版本。

---

## 6. 測試與驗證

| 變動 | 已確認驗證 |
|---|---|
| Coach / Traditional 分流 | 67 項 Focused WSL Tests 通過 |
| Nearest-Behavior Selection | 60 項 Focused Tests 通過 |
| Fresh / Resume 共用 Loop | 798 Pass、5 Skip、0 Fail |
| Serial Match Execution | 設定持久化、Worker 數量及無效設定測試 |
| Nearest-Behavior Experiment Config | Config Validation 與 Runtime Construction |
| Framework Reflection | 已新增實作、契約與測試；完整正式實驗結果待確認 |

測試通過不代表所有正式實驗均已完成。

---

## 7. 推論後端討論（10/26）

10/26 討論使用 ChatGPT Plus 的 Codex CLI，取代部分付費 LLM API 呼叫。

主要方向：

- 透過 `codex exec` 呼叫模型。
- 使用 Python Subprocess 建立最小 Provider Adapter。
- 盡量保留 EAGLE 現有 Prompt、Schema、Retry 流程。
- 優先考慮 Initial Population 或低頻 Reflection。
- 不優先套用至大量並行的每個子代呼叫。

安裝時遇到 npm 全域目錄 `EACCES` 權限問題，提出使用者本地 npm prefix 作為解法。

**此項屬後端方案討論，未確認已整合至 EAGLE。**

---

## 8. 本階段研究方向的變化

### 8.1 Evolution Search Space

| 模式 | 演化對象 |
|---|---|
| Local Framework Evolution | 固定 Framework 的 Slot Values |
| LLM Coach Evolution | LLM 選擇完整 Slot Genome |
| Framework Reflection | Framework Structure + Slot Domains + Slot Genome |

Framework Reflection 將搜尋空間從單純的參數組合，擴展至可變的策略框架結構。

### 8.2 Exploration 與 Exploitation

Nearest-Behavior Mating 採用：

- 相似個體交配：偏向 Exploitation。
- Survivor Diversity Selection：保留 Exploration。

兩個操作分別負責不同演化階段。

### 8.3 LLM 使用位置

新版架構進一步區分：

- Framework Bootstrap
- Strategy Description Reflection
- Framework Reflection
- Genome Selection / Migration
- Local Crossover / Mutation

其中 Local Evolution 仍可完全不需要候選階段的 LLM 呼叫。

### 8.4 目前尚未確認的研究問題

1. Framework Reflection 是否比 Frozen Framework 取得更好的最終策略。
2. Nearest-Behavior Mating 是否比原 Selection 有更好的收斂表現。
3. Framework 更新帶來的效能提升是否足以抵銷額外 LLM 成本。
4. Semantic Diversity 能否有效反映實際策略多樣性。
5. Same-Seed Repeatability 在 Parallel 與 Serial Evaluation 下有何差異。
6. Framework Migration 是否會造成原有高適應度策略退化。

---

## 9. 主要 GitHub 變更來源

- [10/22 — Coach / Traditional Offspring Routes](https://github.com/sophie8909/EAGLE/commit/4f37f5f6)
- [10/22 — Deterministic Candidate Identity](https://github.com/sophie8909/EAGLE/commit/099a5848)
- [10/22 — Shared Evolution Loop](https://github.com/sophie8909/EAGLE/commit/9a341f2a)
- [10/22 — Stability Replicates](https://github.com/sophie8909/EAGLE/commit/51a6a652)
- [10/23 — Serial Match Execution](https://github.com/sophie8909/EAGLE/commit/aa09da10)
- [10/23 — Small-Scale Repeated Experiments](https://github.com/sophie8909/EAGLE/commit/a95c549d)
- [10/23 — Nearest-Behavior Mating](https://github.com/sophie8909/EAGLE/commit/28ea6606)
- [10/24 — Experiment Index](https://github.com/sophie8909/EAGLE/commit/d349c4c9)
- [10/24 — Framework Reflection and Strategy Revision](https://github.com/sophie8909/EAGLE/commit/009ee77a)

## 10. 紀錄限制

- GitHub 查詢範圍截至 2026/10/28。
- 最新可確認提交為 2026/10/24。
- 本整理不包含尚未 Commit 的本地 Working Tree 修改。
- 實驗結果以 10/24 的 `reports/experiments_index.md` 為基準。
- 實驗設定、程式實作、測試通過及正式實驗完成是不同狀態，不可混為一談。
