# `self_play_10x20` semantic tie-break 實驗分析

日期：2026-09-29
Run：`/home/mhlab/EAGLE/runs/20260928_115653_334420`
Resolved config：`/home/mhlab/EAGLE/runs/20260928_115653_334420/config.yaml`

## 結論摘要

這次實驗完成 20 generations、population 10、600 場 final test，Integration 7/7 通過且沒有 match error；但 fixed-roster final test 仍是 **0 勝 / 444 敗 / 156 和 / 0 錯誤**。因此，scalar self-play Game Performance 加上 semantic tie-break 能保留一部分 probe-level 行為多樣性，卻沒有把 self-play 的正 shaping fitness 轉成固定對手的取勝能力。

## 這次實驗修改了什麼

相對於前一個 legacy self-play 10×20 run `20260923_134743_200030`，保留 Ministral 3 8B、population 10、20 generations、每 5 代 refresh、`llm_generated_policies`、`inherited_genotype`、static reflection、random seed 7 與三張地圖；主要修改集中在 selection objective：

1. `algorithm`: `lexicase` → `game_performance_semantic_tiebreak`。
2. 演化 objective：10 個 `opponent_cases` → 單一 scalar `game_performance`。
3. 啟用 semantic probes：3 maps × early/mid/late，共 9 個 probe states。
4. 在 fitness 差距 `≤ 1.0` 的 inclusive tier 內，以 semantic signature 做 tie-break；semantic signature 只用於平手選擇，不是額外 optimizer objective。
5. 實際 resolved config 明確記錄 `parent_evaluation_mode: reuse_cached`。

注意：目前 IDE 開啟的 `configs/experiments/0925_self_play/self_play_5x40.yaml` 是另一個 legacy 5×40 設定（仍是 `lexicase`、`opponent_cases`）；它不是本次 run 的來源。目標 run 的來源是 `configs/experiments/0927/self_play_10x20.yaml`。

## 目標 run 結果

### Search / self-play

- Best candidate：`gen_0020_f079b7fcf571`
- Best search `game_performance`：`1.263534`
- Best candidate self-play：180 場全和（0/180/0）；正 fitness 來自 resource、material、survival shaping，不是勝局。
- Final population 的 search fitness：`1.263534, 0.999972, 0.163226, 0.144392 × 6`；10 個候選仍是 self-play draw。
- Generation 20 的 semantic signatures：4 / 10 unique，最大同質群為 7 / 10。G5、G10、G15 都是 1 / 10，表示 tie-break 的多樣性效果主要在後期才出現。

### Fixed-roster final test

| 對手 | W/L/D/E |
| --- | ---: |
| PassiveAI | 0/0/60/0 |
| RandomAI | 0/2/58/0 |
| RandomBiasedAI | 0/22/38/0 |
| LightRush | 0/60/0/0 |
| HeavyRush | 0/60/0/0 |
| WorkerRush | 0/60/0/0 |
| AllInBot | 0/60/0/0 |
| Mayari | 0/60/0/0 |
| COAC | 0/60/0/0 |
| TMA | 0/60/0/0 |

分地圖：8×8 為 0/159/41、16×16 為 0/145/55、24×24 為 0/140/60。三張地圖與兩個 player side 都沒有勝局，故不能解讀成單一地圖或 side 的偶然失敗。

### Artifact / reliability

- Candidate directories：270；其中 10 個 refresh-only 目錄沒有 `candidate.json`。
- 正式 candidate records：260；evaluated 232、failed 28。
- 28 個 failure：validation 19、generation 7、compilation 2。
- Final test：600/600 場完成、match errors 0、opponent fault contained/recovered 都是 0。
- 五個 refresh boundaries 共 50 筆 refresh records；只有 14 筆保留相同 Java hash，36 筆 `generated_java_preserved: false`。因此本 run 的演化結果需要標記為 refresh contract caveat，不能當作完全 phenotype-preserving 的乾淨 ablation。
- 已提交 generation timing 加總約 23.106 小時；這是 generation records 的加總，不把它誤當成單純 LLM 或 match 時間。

## 與近期實驗的共同 final-test 比較

所有下列 final test 都是同一套 10 opponents × 3 maps × 10 rounds × 2 sides = 600 場；但 self-play search fitness 仍不可跨 snapshot 或跨 evaluation mode 直接比較，橫向比較以 final-test W/L/D 為主。

| 實驗 | Run | W/L/D | 勝率 | 角色 |
| --- | --- | ---: | ---: | --- |
| Fixed-roster mixed initial population | `20260911_072610_382082` | 256/332/12 | 42.67% | 主要 fixed-roster control |
| Legacy self-play 10×20 | `20260923_134743_200030` | 0/449/151 | 0% | semantic tie-break 前的 self-play comparison |
| Legacy self-play 5×40 | `20260925_134245_911171` | 197/392/11 | 32.83% | legacy lexicase，無 semantic probes |
| Semantic tie-break 10×10 | `20260926_195259_768977` | 257/321/22 | 42.83% | post-0924 comparison |
| Semantic tie-break 5×20 | `20260927_035808_811233` | 0/388/212 | 0% | draw-attractor comparison |
| Semantic tie-break 10×20 | `20260928_115653_334420` | 0/444/156 | 0% | 本次實驗 |

這些 run 不是完全 controlled comparison：LLM sampling、run 所在 repository state、refresh preservation 問題與初始化實際 phenotype 都可能不同。安全結論是：本 run 的 semantic tie-break 沒有改善 fixed-roster 勝率；與 10×10／5×20 的差異不能單獨歸因於 population 或 generation 數量。

## 保留／刪除原則

保留 09/24 以前仍被現行比較或控制組引用的資料，至少包括：

- `20260911_072610_382082`：fixed-roster mixed initial population 主要 baseline。
- `20260910_160655_907573`：全 WorkerRush initial population control arm。
- `20260923_134743_200030`：目前 self-play 10×20 comparison 的 legacy baseline。
- model parameter audit 與 seed comparison 明確引用的 historical control runs。

本次已依使用者確認刪除以下 21 個 raw run，合計約 70 GB；09/24 以前仍作為 control、baseline、seed/model audit 或現行比較依據的 run 均保留：

```text
20260811_145941_699720  20260812_153827_980509  20260813_134047_831263
20260815_132814_015905  20260817_221555_905133  20260818_225759_015642
20260819_061959_224529  20260819_170459_756534  20260820_101925_877795
20260826_193927_154079  20260826_201429_397697  20260830_173117_263163
20260831_101514_161627  20260904_190550_626269  20260920_112443_496938
20260920_132133_546328  20260920_144031_248127  20260921_013708_847328
20260921_120920_977136  20260922_115743_497216  20260923_133624_926898
```

刪除後已核對：上述 21 個目錄均不存在，保留清單與目標 run 均仍可讀取；Notion 頁面同步記錄清理完成與保留原則。

## Sources

- `manifest.json`, `config.yaml`, `summary.json`
- `analysis/generation_metrics.csv`
- `analysis/semantic_uniqueness.csv`
- `analysis/semantic_candidates.csv`
- `final_test/final_test_summary.json`
- `final_test/final_test_results.md`
- `generations/generation_*_self_play_snapshot.json`
- `generations/generation_*_self_play_parent_refresh.json`
