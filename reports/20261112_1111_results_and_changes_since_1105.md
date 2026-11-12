# EAGLE 實驗分期、結果與 1105 後變動

更新時間：2026-11-12（Asia/Taipei）

## 先講結論：實驗不是同一批

目前應分成兩個階段閱讀：

1. **第一階段：初始化方法比較**
   比較 `10 GPT initial` 與 `1 GPT + 9 local`。兩者都使用同一個
   framework-slot bundle，但當時尚未使用後來新增的 self-play diversity seats。
2. **第二階段：多樣性控制後的 1 GPT 版本**
   加入 self-play survivor diversity control 後，再跑 `1 GPT + 9 local` 的
   五 seed batch，也就是 1111 config。這不是第一階段的直接同批重跑。

## 1. 第一階段：10 GPT vs 1 GPT + 9 local

### 實驗目的

確認 generation 0 的十個 genome 是否都交給 GPT 選擇，會不會比「只有第一個
genome 使用 GPT、其餘九個使用 local seed」更好。

### 兩個 treatment

| Treatment | Generation 0 | 後續 evolution | Config |
|---|---|---|---|
| **10 GPT initial** | 十個初始 genome 都由 GPT 從 authored strategy descriptions 選出 | local crossover / mutation | [`10_gpt_initial_seed8_9.yaml`](../configs/experiments/1108_gpt_vs_local_50x10_seed8_9/10_gpt_initial_seed8_9.yaml) |
| **1 GPT + 9 local** | index 0 使用固定 GPT genome；index 1–9 使用 local genomes | local crossover / mutation | [`1_gpt_9_local_seed8_9.yaml`](../configs/experiments/1108_gpt_vs_local_50x10_seed8_9/1_gpt_9_local_seed8_9.yaml) |

共同設定：population 10、50 generations、self-play 每 5 代更新、相同 framework
bundle、相同 final-test protocol。

### 已完成的直接對照結果

repository 中目前保存的同一個 50×10 comparison report 是 **seed 8、9**：

| Treatment | Seed | G0 best | G50 best | Final-test W/D/L | Win rate |
|---|---:|---:|---:|---:|---:|
| 10 GPT initial | 8 | -1.26 | 38.06 | 439/9/152 | 73.17% |
| 10 GPT initial | 9 | 2.36 | 10.71 | 327/20/253 | 54.50% |
| 1 GPT + 9 local | 8 | -9.50 | 2.72 | 364/9/227 | 60.67% |
| 1 GPT + 9 local | 9 | -9.52 | 42.32 | 431/0/169 | 71.83% |

兩 seed 平均：

| Treatment | Mean G0 best | Mean G50 best | Mean final-test win rate |
|---|---:|---:|---:|
| 10 GPT initial | -0.55 | 24.39 | 63.83% |
| 1 GPT + 9 local | -9.51 | 22.52 | 66.25% |

解讀：10 GPT initial 在 G0 明顯較高，但最後表現有 seed variance；在這兩個
seed 的 final test，1 GPT + 9 local 平均勝率略高。這只能說明結果對 seed 敏感，
不能宣稱任一 treatment 穩定勝出。

完整報告：[`1108_gpt_vs_local_50x10_seed8_9/RESULTS.md`](../configs/experiments/1108_gpt_vs_local_50x10_seed8_9/RESULTS.md)

### 關於「五 seed comparison」的資料邊界

config 與報告需要區分：

- 上面這份 repository 的 **同一個 50×10 直接比較表實際只有 seed 8、9**。
- `1104_description_guided` 另有 100×10 的 GPT initialization runs，包含
  seeds 8、9、10，但不是上表的同一個 50×10 batch。
- **1111 才是明確宣告 seeds 8、9、10、11、12 的五 seed batch**，而且它已經
  使用多樣性控制後的 selection contract。

因此不能把 1111 的五 seed 結果回填成第一階段的五 seed baseline comparison。

## 2. 第二階段：多樣性控制後的 1 GPT + 9 local

### 為什麼新增這個版本

第一階段的 self-play selection 可能讓族群集中到少數高分行為。之後加入
self-play survivor diversity control：除了依 fitness 選 survivor，另外保留兩個
以 max-min behavioral distance 選出的 diversity seats。這個 selection 變動在
1111 config 之前已進入程式與測試。

### 1111 實驗設定

Config：[`1111_1gpt_9local_50x10_seed8_12`](../configs/experiments/1111_1gpt_9local_50x10_seed8_12/)

- treatment：1 GPT + 9 local
- seeds：8、9、10、11、12（五個 seed）
- population：10
- generations：50
- GPT genome：每個 seed 共用同一個 frozen GPT genome，index 0 使用
- local genomes：其餘 9 個初始 genome 依 seed 產生；offspring 全部 local evolution
- self-play：每 5 代更新 opponent pool
- semantic probes：啟用
- framework bundle SHA-256：`f674a580f0db088bd3436232d2dd36d071a231c9886f480a7aaed25669203e2b`

### 1111 目前進度與結果

| Seed | Run | 狀態 | 完成代數 | Best search score | Final test |
|---:|---|---|---:|---:|---|
| 8 | [`20261111_131257_292954`](../runs/20261111_131257_292954/) | complete | 50 | 32.911733 | 完成 |
| 9 | [`20261112_011300_617215`](../runs/20261112_011300_617215/) | complete | 50 | 27.010029 | 完成 |
| 10 | [`20261112_125328_100654`](../runs/20261112_125328_100654/) | partial / failed after G33 | 33 | — | 尚未完成 |
| 11 | — | 尚未開始 | — | — | — |
| 12 | — | 尚未開始 | — | — | — |

已完成的 final test，每個 run 是 600 場：

| Seed | Best candidate | Final-test W/D/L/E | Win rate |
|---:|---|---:|---:|
| 8 | `gen_0050_e76bf1bc50da` | 463/11/126/0 | 77.17% |
| 9 | `gen_0048_016ae62c6eec` | 352/10/238/0 | 58.67% |

目前兩個完成 seed 合計 1,200 場：`815/21/364/0`，勝率 **67.92%**。這只是
1111 五 seed batch 的暫時結果，不能當成五 seed 平均；seed 10–12 尚未完成。

### 和第一階段 1 GPT + 9 local 的差異

| Seed | 第一階段 best search | 第一階段 final W/D/L | 1111 diversity-control best search | 1111 final W/D/L |
|---:|---:|---:|---:|---:|
| 8 | 2.716686 | 364/9/227 | 32.911733 | 463/11/126 |
| 9 | 42.320554 | 431/0/169 | 27.010029 | 352/10/238 |

這是不同 run、不同 selection contract 的觀察性比較；seed 8 改善，seed 9 退步，
目前不足以證明 diversity control 一定提升平均戰績。應等五個 seed 完成後再做
平均與變異分析。

## 3. 1105 後的變動，按實驗流程排列

### 3.1 第一階段準備：GPT initialization

- `1104_description_guided` 改為支援十個初始 genome 都由 GPT 依 authored
  descriptions 選擇。
- 同時保留 `gpt_initial_candidates: 0` 的 1 GPT + 9 local treatment，並把
  第一個 GPT genome 固定寫入 `initial_genomes`。
- Ubuntu / Windows 與 seed-specific config 分開，並固定 framework bundle bytes
  與 SHA-256，避免 CRLF/LF 造成不可重現。

### 3.2 實驗執行基礎設施

- 恢復 experiment-owned local LLM lifecycle：fresh/resume 會管理相容的 local
  llama-server；完成、失敗或中斷時清理 owned process。
- 新增 `--connect-only` 路徑，讓已由外部啟動的 server 不被 experiment 接管。
- launcher 與 GUI 同步支援這個模式。

### 3.3 多樣性控制

- self-play survivor selection 新增兩個 diversity seats。
- diversity seats 以 behavioral distance 對 fitness leaders 做 max-min 選擇。
- 更新 `selection.py`、generation flow、architecture spec、current status、
  testing contract 與相關 tests。

### 3.4 固定評估與 convergence analysis

- final candidate 可自動執行 fixed cross-generation final test。
- 可在 G0、G5、G10… 對所有 runnable candidates 做固定 protocol evaluation。
- fixed evaluation 支援 partial resume，並增加長時間執行的 progress / heartbeat。
- 新增 all-candidate convergence runner、CSV、統計彙總與繪圖工具。

## 4. 待完成工作

1. 完成或確認 1111 seed 10 的 G33 partial run。
2. 執行 1111 seed 11、12。
3. 五個 seed 都完成後，再比較 diversity-control 版本的平均 final-test、標準差，
   並和第一階段 baseline 分開報告。

## 5. 主要資料位置

- 第一階段 comparison：[1108 RESULTS.md](../configs/experiments/1108_gpt_vs_local_50x10_seed8_9/RESULTS.md)
- 第二階段 config：[1111 config](../configs/experiments/1111_1gpt_9local_50x10_seed8_12/)
- 1111 seed 8：[manifest](../runs/20261111_131257_292954/manifest.json)、[final test](../runs/20261111_131257_292954/final_test/final_test_results.md)
- 1111 seed 9：[manifest](../runs/20261112_011300_617215/manifest.json)、[final test](../runs/20261112_011300_617215/final_test/final_test_results.md)
- 1113 convergence analysis：[report.md](../Meeting/1113/report.md)

