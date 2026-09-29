# EAGLE 0907 後版本整理

## 範圍與判定方式

- 時間範圍：2026-09-08 00:00:00 至 2026-09-09 10:59:58（Asia/Taipei）。
- 基準版本：`659e5a39168f6507da4b43ebddfa2701417dcab5`（2026-09-07 23:12:08，`feat: strengthen code reflection assessment`）。
- 最新版本：`0009cafe6d38f3945ee61df88ac6a6a9c600ddf3`（2026-09-09 10:59:58）。
- 儲存庫目前沒有 Git tag，因此本文以 Git commit 作為「版本節點」。
- 本範圍共有 5 個提交；相對於基準版本，淨變更為 43 個檔案、1,524 行新增、320 行刪除。
- 本文只整理已提交內容，不包含工作樹中尚未追蹤或尚未提交的檔案。

## 版本時間軸

| 版本 | 時間 | Commit | 主題 | 主要結果 |
| --- | --- | --- | --- | --- |
| V1 | 09/08 08:46 | `348cbe6da1b` | Code Reflection 評估設定 | 新增 5×3 與 20×10 兩組靜態反思比例實驗 |
| V2 | 09/08 08:47 | `dfc4a117610` | 5×3 實驗登錄 | 記錄 5 代、族群 3 的執行目錄 |
| V3 | 09/08 10:18 | `9e855d0f417` | 20×10 實驗登錄 | 記錄 20 代、族群 10 的執行目錄 |
| V4 | 09/08 12:11 | `eb2d6e23693` | 分階段 Java materialization | 重整每代 offspring 流程，並加入獨立 `generation_model` |
| V5 | 09/09 10:59 | `0009cafe6d3` | 主分支整合 | 合併簡報資產、簡報製作技能與 Codex 使用量控制更新 |

## V1：新增 Code Reflection 評估實驗

Commit：`348cbe6da1b9d3d2131d8f1ab212b4b6d5b7cec4`

新增兩份可重現的實驗設定：

- [`0908_code_reflection_assessment_5x3`](../configs/experiments/0908_code_reflection_assessment_5x3/ministral3_8b_static_0.33_0.33_0.34_code_assessment_5x3.yaml)：5 個演化世代、族群大小 3。
- [`0908_code_reflection_assessment_20x10`](../configs/experiments/0908_code_reflection_assessment_20x10/ministral3_8b_static_0.33_0.33_0.34_code_assessment_20x10.yaml)：20 個演化世代、族群大小 10。

兩組設定的共同條件如下：

- 模型：Ministral 3 8B。
- survivor selection：`mu_plus_lambda`。
- reflection operator：`static`。
- Strategy / Prompt / Code Reflection 比例：0.33 / 0.33 / 0.34。
- crossover rate：0.75；mutation rate：1.0；random seed：7。
- 評估使用 8×8、16×16、24×24 三張地圖，每張 3 rounds，交換玩家位置。

這個版本的目的，是用小型 5×3 實驗先快速檢查行為，再用 20×10 設定做較完整的 Code Reflection 評估。

## V2：登錄 5×3 評估執行

Commit：`dfc4a1176105c1ca9392b133f64d074cdb2cf50a`

新增 [`experiment.yaml`](../configs/experiments/0908_code_reflection_assessment_5x3/experiment.yaml)，把設定檔對應到執行目錄 `runs/20260908_084706_819288`。這個提交只記錄執行索引，不包含實驗結果本身的程式邏輯變更。

## V3：登錄 20×10 評估執行

Commit：`9e855d0f41763ce474772ea222c9904ae8d9e562`

新增 [`experiment.yaml`](../configs/experiments/0908_code_reflection_assessment_20x10/experiment.yaml)，把設定檔對應到執行目錄 `runs/20260908_101749_429776`。與 V2 相同，此版本是實驗索引紀錄，不改變核心演化流程。

## V4：Generation-wide Java materialization

Commit：`eb2d6e23693c1eeb4f66021e83fad35e5c10e430`

這是 0907 後最主要的架構版本，影響 31 個檔案，新增 1,147 行、刪除 289 行。

### 核心流程變更

每一代 offspring 的處理從交錯執行改成三個明確階段：

1. `plan_offspring`：先為整個 offspring population 固定 parent selection、crossover/copy 結果與 mutation assignment。
2. `apply_offspring_mutations`：完成 Strategy Reflection、Prompt Reflection，以及 Code Reflection 的 diagnosis；此時 Code revision 暫緩。
3. `materialize_code_reflections`：進入統一的 Java materialization 階段，完成 Code revision，並與一般 Java generation 共用同一階段模型。

這項切分讓 operator assignment 不再與 LLM 呼叫交錯，也讓同一世代的 Java 產生集中在單一 phase boundary。

### 雙模型支援

實驗設定新增可選的 `generation_model`：

- `model`：負責初始化，以及 reflection / prompt rewrite。
- `generation_model`：負責最終 Java materialization 與 compile repair。
- 未設定 `generation_model` 時，自動沿用 `model`，維持單模型相容性。
- 使用不同模型時，experiment orchestrator 會在 reflection 與 generation 階段邊界切換同一個 llama.cpp runtime，切換後執行 endpoint preflight。
- 新執行、resume 與 reflection inspection 路徑都納入 phase-aware model handling。

### Code Reflection 與 artifacts

- Code Reflection schema 從 `eagle-code-reflection-v3` 升為 `eagle-code-reflection-v4`。
- diagnosis 與 revision 拆成兩階段；revision 初始狀態可為 `pending`、`not_required` 或 `not_run`。
- candidate compact mutation record 新增 reflection / revision model、status、attempts、error、Java SHA-256 與 `java_changed` 等欄位。
- timing artifacts 分開記錄 `code_reflector_llm` 與 `code_revision_llm`。
- resume 路徑沿用相同三階段流程，避免新執行與續跑產生不一致語意。

### 新增模型比較設定

- [`01_ministral3_8b_only_20x10.yaml`](../configs/experiments/0908_generation_model_comparison_20x10/01_ministral3_8b_only_20x10.yaml)：reflection 與 generation 都使用 Ministral 3 8B。
- [`02_ministral3_8b_to_qwen3_5_9b_20x10.yaml`](../configs/experiments/0908_generation_model_comparison_20x10/02_ministral3_8b_to_qwen3_5_9b_20x10.yaml)：reflection 使用 Ministral 3 8B，Java generation 使用 Qwen 3.5 9B。

兩份設定保持相同的 20×10 演化條件與 0.33 / 0.33 / 0.34 反思比例，使比較集中在 final Java materialization model 的差異。

### 文件與測試同步

- 架構、演化流程、mutation、Java generation、artifact/timing schema、操作指南與 current status 均更新至新 phase contract。
- 測試涵蓋 Code Reflection deferred revision、pipeline ordering、experiment launcher、initial population 與 runtime workflow。
- `create_offspring` 保留為相容 wrapper，依序呼叫新的三階段 API。

## V5：主分支合併整合

Commit：`0009cafe6d38f3945ee61df88ac6a6a9c600ddf3`

這個 merge commit 將另一條 `master` 歷史整合到 V4 之後。以第一個 parent（V4）為基準，帶入的內容包括：

- 2026-09-10 EAGLE 進度簡報與可重用 PowerPoint template。
- reference-matched presentation 的本地 skill、agent metadata 與 08/30 參考說明。
- Codex usage controller 的手動開關，以及依剩餘天數動態計算 reserve 的邏輯與測試。
- `AGENTS.md` 的控制器說明更新。

注意：合併進來的來源 commits 多數 authored date 是 09/07，另有兩個 usage-controller commits 是 08/30、08/31；它們因為在 09/09 的 merge 才進入目前這條本地主線，所以列在 V5，而不把來源提交重新算成 09/08 之後的新版本。

## 目前版本的整體狀態

截至 `0009cafe6d3`，0907 後的演進可歸納為三條主線：

1. **實驗可重現性**：加入 5×3、20×10 Code Reflection 評估設定與執行索引。
2. **演化流程架構化**：每代先完整規劃 offspring，再做 reflection/rewrite，最後集中 materialize Java。
3. **模型職責分離**：允許 reflection model 與 generation model 分工，同時保持單模型設定相容。

換言之，這一段版本的核心不是調整 fitness 或 lexicase 規則，而是重新定義「一整代何時完成 operator assignment、何時做 reflection、何時切換模型並產生 Java」的執行邊界，並補上對應的實驗設定、artifacts、resume、文件與測試契約。

## Git 查核方式

```bash
git log --since='2026-09-08 00:00:00 +0800' \
  --date=iso-local --pretty=format:'%H %ad %s'

git diff --shortstat \
  659e5a39168f6507da4b43ebddfa2701417dcab5..0009cafe6d38f3945ee61df88ac6a6a9c600ddf3
```
