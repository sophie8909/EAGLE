# EAGLE 實驗與程式變更報告

日期範圍：2026-10-01 至 2026-10-07
分析基準 HEAD（本次新增 config/report 前）：`68476fa29fc`

## 1. 執行摘要

- 10/1–10/5 完成 self-play、evaluation persistence、並行 MicroRTS、4×10 與 LLM seed propagation 等工作。
- 10/6 完成 explicit seed schedule 與 deterministic mode；同日的舊 10×4 實驗是在 deterministic mode 加入前執行，不能作為 deterministic 證據。
- 10/7 以 deterministic mock pipeline 完成 3×2 smoke gate：seed 7、8、9 均各兩 run，行為結果一致。
- 本日再完成 deterministic 4×10：seed 7、8 各兩 run，四個 run 均完成；同 seed 的行為 artifact 一致。
- 本機 Codex 執行環境沒有 CUDA，因此實際 Ministral openai run 無法在合理時間完成；4×10 本次結果是完整 EA/mock pipeline 驗證，不是實際 LLM 生成結果。

## 2. 本次 4×10 實驗

設定檔：

`configs/experiments/1009_determinism_4x10_2seeds/ministral3_8b_determinism_4x10_2seeds.yaml`

| 項目 | 設定 |
| --- | --- |
| generations | 4 |
| population | 10 |
| seeds | 7、8 |
| runs | 每個 seed 2 run |
| evaluation | self-play，10 slots × 3 maps × 3 rounds × 2 sides = 180 matches/candidate |
| reflection | static，Strategy/Prompt/Code = 0.33/0.33/0.34 |
| reproducibility | `deterministic_mode: true`、temperature 0、serial match worker、CPU llama contract |
| execution | `mock`（本機沒有 CUDA；未冒充實際 LLM 結果） |

Run directories：

| Seed | Run 1 | Run 2 | 行為比對 |
| --- | --- | --- | --- |
| 7 | `runs/20261007_133838_331187` | `runs/20261007_133856_523061` | PASS |
| 8 | `runs/20261007_133919_738016` | `runs/20261007_133937_477330` | PASS |

比對範圍包含 generation snapshots、candidate ID、lineage、fitness/objectives、evaluation results、match score/vector 與 mutation/operator 路徑。只有 timing 欄位不同，因為實際執行時間不應被當作演化行為。

## 3. 10/1 至今的實驗紀錄

| 日期 | 實驗 | Runs / 狀態 | 備註 |
| --- | --- | --- | --- |
| 10/2 | `ministral3_8b_parallel_match_20x10` | 1 interrupted | 舊 parallel evaluation run；之後保留作效能與 artifact 對照 |
| 10/2–10/4 | `ministral3_8b_self_play_semantic_tie_20x10` | seed 7、8、9 各完成 | self-play scalar Game Performance、semantic tie-break |
| 10/5 | `ministral3_8b_self_play_4x10` | seed 7 一次 failed、seed 7/8 完成 | 舊非-deterministic 4×10；temperature 與 GPU runtime 尚未統一 |
| 10/6 | `ministral3_8b_self_play_10x4` | seed 7/8/9 各兩次完成 | 舊非-deterministic 10×4；不能用來證明同 seed bitwise 一致 |
| 10/6 | deterministic 10×4 attempt | incomplete | 已啟用 deterministic config，但 LLM server timeout，只有部分 generation 0 evidence |
| 10/7 | deterministic 3×2 smoke | seed 7、8、9 各兩次 mock complete | 先通過 seed 7 gate，再跑 seed 8/9；行為一致 |
| 10/7 | deterministic 4×10 | seed 7、8 各兩次 mock complete | 本報告的主要新實驗；行為一致 |

歷史實驗 artifact 位於 `/home/mhlab/EAGLE/runs/`，舊 run 必須依其 run-local `config.yaml` 判斷，不能用目前 config 回推當時設定。

## 4. 程式變更整理

### 10/1–10/4：EA、self-play 與效能基礎

- Self-play library 依完整 semantic behavior 去重，並對齊 LocalLearner lifecycle。
- Fresh/resume generation orchestration 統一，EA operators 與 execution stages 分離。
- Evaluation persistence 與 compact match artifact overhead 降低。
- MicroRTS evaluation 支援平行 match workers，同時保留 canonical match order。
- self-play objective 改為 semantic tie-aware Game Performance scalar。
- 支援 independent experiment runs，並補上 workflow diagram 與 repository cleanup。

### 10/5：LLM seed、runtime lifecycle 與 4×10

- 每個 OpenAI-compatible LLM request 傳遞 experiment seed，並加入 LLM stability diagnostics。
- 每個 seed trial 與 experiment run 邊界重啟 owned llama-server，避免 server state 汙染後續 run。
- 提高 prompt request bound 至 80k chars，以避免長 context 被過早截斷。
- 新增 compact self-play 4×10 config。
- failed evolutionary candidate 與 valid parent survivor pool 隔離，保留失敗 stage evidence。

### 10/6：explicit seed schedule 與 deterministic mode

- `random_seeds: [7, 8, 9]` 搭配 `runs: 2` 會明確排程為 `7, 7, 8, 8, 9, 9`。
- `deterministic_mode` 控制：
  - EA、selection、crossover、operator choice 使用同一個 seeded RNG contract。
  - 每場 MicroRTS match 依 run seed 與 immutable match identity 派生 JVM seed。
  - seed 傳遞到 initial policy、reflection、rewrite、Java generation、repair 與 preflight LLM request。
  - temperature=0、CPU llama.cpp、threads=1、batch size ≥512、parallel=1、match worker=1。
  - match seed 持久化在 match metadata。
- llama deterministic batch size 修正，避免 context decode assertion：
  `GGML_ASSERT(n_tokens_all <= cparams.n_batch)`。
- vendored MicroRTS random source 改用 `-Deagle.match.seed`。

### 10/7：最後一個非行為 UUID 差異

- Strategy Reflection metadata 原本用 `uuid4()` 產生 request correlation ID；雖然沒有送入模型，仍會讓同 seed artifact 不同。
- 改為由 candidate ID、generation、role、match ID、suffix 經 SHA-256 派生的 stable ID。
- 新增 deterministic request ID regression test。
- 新增 3×2 與 4×10 deterministic smoke configs。

## 5. Reproducibility 結論

目前可保證的範圍是同一台機器、同一 model file、同一 llama.cpp build、同一 JVM 與同一 config 下的 deterministic mode。不同硬體、model quantization、llama.cpp build 或 JVM 不承諾 bitwise 相容。

本次 4×10 mock run 已證明 EA 層的 seed propagation、candidate identity、selection/mutation path、self-play evaluation 與 artifact 行為可重現。實際 openai LLM 仍需在有 CUDA 的 5080 host 上依同一份 config 執行，才能補上模型生成層的 end-to-end evidence。

## 6. Validation 與版本

- `python -m unittest discover -s tests -q`：518 tests passed，1 skipped。
- 3×2 與 4×10 deterministic mock runs 均完成。
- 相關 reproducibility commits：
  - `8b39a3c6c79` — propagate experiment seed and add stability checks
  - `b712ec9c9da` — support repeated explicit seed schedules
  - `cae83dbf851` — add deterministic experiment mode
  - `735bc5796ea` — keep deterministic llama batch size viable
  - `68476fa29fc` — stabilize deterministic reflection metadata
