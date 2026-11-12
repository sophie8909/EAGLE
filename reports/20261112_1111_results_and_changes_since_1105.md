# 1111 實驗結果與 1105 後變動整理

更新時間：2026-11-12 21:43（Asia/Taipei）

## 1. 摘要

1111 的實驗是 `1 GPT seed + 9 local` 的 framework-slot 演化：每個 seed 的
generation 0 index 0 使用固定的 GPT genome，其餘 9 個初始 genome 與後續
offspring 使用 Qwen3.5 9B 的 local finite-slot evolution。設定為 population 10、
50 generations、self-play 每 5 代更新對手池，並啟用 semantic probes。

目前 batch 狀態：

| Seed | Run | 狀態 | 完成代數 | Best search `game_performance` | Final test |
|---:|---|---|---:|---:|---|
| 8 | [`20261111_131257_292954`](../runs/20261111_131257_292954/) | complete | 50 | 32.911733 | 完成 |
| 9 | [`20261112_011300_617215`](../runs/20261112_011300_617215/) | complete | 50 | 27.010029 | 完成 |
| 10 | [`20261112_125328_100654`](../runs/20261112_125328_100654/) | partial / running manifest | 33 | — | 尚未執行 |
| 11 | — | 尚未開始 | — | — | — |
| 12 | — | 尚未開始 | — | — | — |

注意：seed 10 的 manifest 仍標記為 `running`，但截至本報告時間找不到其
`experiment_pid`，且最後一個 generation artifact 是 G33；因此這裡將它視為
中斷或待續跑的 partial run，不把它當成仍在運行中的 process。

Config：[`1111_1gpt_9local_50x10_seed8_12`](../configs/experiments/1111_1gpt_9local_50x10_seed8_12/)

## 2. 1111 完成 run 的結果

Final test 固定為 10 opponents × 3 maps × 10 games × 2 player sides，合計 600
場。下表的順序為 `W/D/L/E`；`E` 是 execution error。

| Seed | Best candidate | Best search score | Final-test W/D/L/E | Win rate |
|---:|---|---:|---:|---:|
| 8 | `gen_0050_e76bf1bc50da` | 32.911733 | 463/11/126/0 | 77.17% |
| 9 | `gen_0048_016ae62c6eec` | 27.010029 | 352/10/238/0 | 58.67% |

兩個已完成 seed 的平均：

- Best search score：29.960881
- Final-test：815/21/364/0（1,200 場）
- Final-test win rate：67.92%
- Seed 8 比 seed 9 高 18.50 個百分點，顯示 seed variance 仍然很大。

### 2.1 對手表現摘要

| Seed | 明顯強項 | 主要弱項 |
|---:|---|---|
| 8 | Passive、Random、RandomBiased、LightRush、HeavyRush、WorkerRush 均接近或達到全勝；AllInBot 也為 55/5/0 | TMA 三張 map 全敗；Mayari 與 COAC 在 map 2/3 仍有明顯敗場 |
| 9 | Passive、RandomBiased、HeavyRush 多數全勝；map 1 的 Random 只有 1 draw | WorkerRush、AllInBot、Mayari、COAC、TMA 仍是主要失分來源；TMA 三張 map 全敗 |

完整 match matrix：

- Seed 8：[final_test_results.md](../runs/20261111_131257_292954/final_test/final_test_results.md)
- Seed 9：[final_test_results.md](../runs/20261112_011300_617215/final_test/final_test_results.md)

## 3. 與前一批 1 GPT + 9 local 結果比較

1111 seed 8、9 與 1109 的同類 treatment 對照如下。1109 的結果來自既有
`1108_gpt_vs_local_50x10_seed8_9` 比較報告。

| Seed | 1109 best search | 1109 final W/D/L | 1111 best search | 1111 final W/D/L |
|---:|---:|---:|---:|---:|
| 8 | 2.716686 | 364/9/227 | 32.911733 | 463/11/126 |
| 9 | 42.320554 | 431/0/169 | 27.010029 | 352/10/238 |

這兩個 seed 的平均 final-test win rate 從 66.25%（1109）變為 67.92%（1111），
但 seed 8 改善、seed 9 退步，不能據此宣稱 1111 已穩定優於前一批。

## 4. 1105 後的主要變動

### 4.1 初始化與實驗設定

- 1105：`1104_description_guided` 改為由 GPT 透過十個 authored descriptions
  選出全部十個初始 genome；後續演化仍由 local model 執行。
- 1105：拆分 Ubuntu / Windows 與不同 seed 的 GPT initialization configs，並
  固定 framework bundle bytes 與 SHA-256，避免 CRLF/LF 差異破壞可重現性。
- 1111：新增五 seed 的 1111 config。它固定第一個 GPT genome，令其他 9 個
  初始 genome 與所有 offspring 走 local evolution；設定 seeds 8–12、50 代、
  population 10。

### 4.2 Local LLM lifecycle

1105 恢復由 experiment 管理 local LLM lifecycle：fresh/resume run 會 lazy-start
相容的 owned local server，完成、失敗或中斷時清理；`--connect-only` 則只做
endpoint preflight，不接管外部已啟動的 server。GUI 與 launcher 也同步支援此
選項。

### 4.3 收斂與固定評估工具

1107–1109 增加 seed 8/9/10 的 convergence reports，以及 50-generation 的
`10 GPT initial` 對 `1 GPT + 9 local` 比較資料與圖表。

1110 起增加：

- 自動對選定 final candidate 執行 fixed cross-generation final test。
- 每 5 代對全部 runnable individuals 執行 fixed evaluation，輸出個體級收斂
  資料與統計圖。
- fixed evaluation 可從 partial artifact resume。
- 長時間 fixed evaluation 增加 progress / heartbeat，降低被誤判為卡住的風險。
- 新增 `run_1113_all_candidate_convergence.sh` 與相關分析、繪圖測試。

### 4.4 Selection 與 self-play diversity

1111 前後 selection contract 改為保留 self-play survivor，以維持演化族群的
behavioral diversity；相關 selection、generation flow、architecture spec、
testing contract 與文件同步更新。這是目前 1111 run 使用的 selection 行為。

### 4.5 Artifact、evaluation 與測試文件

1105 後同步更新 runtime、evolution flow、framework slots、artifact schema、
evaluation pipeline、current status、architecture gaps、migration plan、
repository map、operations 與 testing contracts。新增或更新的測試涵蓋：

- description-guided initialization；
- experiment launcher / canonical CLI；
- fixed evaluation 與 partial resume；
- final test 與 all-candidate convergence；
- selection contract、framework Coach integration 與 GUI。

## 5. 目前仍待完成

1. 續跑或確認 seed 10 的 partial run，從 G33 接續到 G50 並執行 final test。
2. 執行 1111 seed 11、12。
3. 五個 seed 完成後，再以相同 fixed final-test protocol 計算平均、標準差與
   seed-wise confidence interval；目前只有兩個完成 seed，不適合下穩定性結論。

## 6. 主要 artifact 位置

- 1111 batch index：[`experiment.yaml`](../configs/experiments/1111_1gpt_9local_50x10_seed8_12/experiment.yaml)
- Seed 8：[manifest](../runs/20261111_131257_292954/manifest.json)、[summary](../runs/20261111_131257_292954/summary.json)
- Seed 9：[manifest](../runs/20261112_011300_617215/manifest.json)、[summary](../runs/20261112_011300_617215/summary.json)
- 1109 treatment comparison：[RESULTS.md](../configs/experiments/1108_gpt_vs_local_50x10_seed8_9/RESULTS.md)
- 1113 fixed convergence：[report.md](../Meeting/1113/report.md)

