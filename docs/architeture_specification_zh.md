# EAGLE 架構說明（中文摘要）

狀態：2026-08-19 現行 executable contract 的中文摘要。英文權威規格為
[`eagle_architecture_spec.md`](eagle_architecture_spec.md)。

## 系統定位

EAGLE 使用 LLM 在離線階段產生與改寫 Java MicroRTS agent。實際比賽執行時
不會呼叫 LLM。每個 phenotype 都是一份完整的
`ai.generated.CandidateAgent` Java 原始碼，不使用 patch、method-body map 或
runtime LLM policy。

## Candidate 與演化流程

Genotype 固定包含三個部分：

1. `strategy_prompt`
2. `previous_code`
3. `generation_prompt`

子代的 `previous_code` 來自被選 parent 最近一次完成評估的 Java phenotype。
Uniform Crossover 會獨立選擇三個 genotype component，並保存各 component 的
來源 candidate ID。

每一代依序執行 seeded lexicase parent selection、crossover、可選的 Strategy
或 Code mutation、完整 Java generation、validation、compilation、integration、
126 場 evaluation、AOS credit，以及 seeded lexicase survivor selection。

`random_seed` 影響 EA 隨機、lexicase case 順序、operator、crossover、mutation
intent 與 reflection sampling。MicroRTS match 不宣稱 seeded reproducibility；
重複比賽只用 `round_index` 識別。

## Reflection 與 Prompt

Reflection operator mode 只有三種：

- `static`
- `aos_opponent`
- `aos_head2head`

Strategy Mutation 只修改 `strategy_prompt`；Code Mutation 只修改
`generation_prompt`。兩者完成後都必須重新產生完整 Java。

所有 executable prompt body 都放在 `prompts/`，一個 prompt 一個 UTF-8
`.txt` 檔。`prompts/manifest.toml` 只保存 metadata 與 placeholder contract。
Python 與 YAML 不再接受 inline prompt、seed template 或重複 prompt body。

## Evaluation

Evolution Evaluation 固定使用七個 opponent：LightRush、HeavyRush、WorkerRush、
AllInBot、Mayari、COAC、TMA。每個可執行 candidate 使用同一份 Java source 與
class directory，進行：

`7 opponents × 3 maps × 3 rounds × 2 sides = 126 matches`

Fitness 是七個 maximized opponent case。失敗或 incomplete candidate 的每個
case 都是 `-1000.0`。加權 aggregate Game Performance 只用於報表。

Code Quality 也是 diagnostic，不是 lexicase objective。成功分數為：

`100 - (40C + 25N + 20L + 15F)`

其中 C、N、L、F 分別是 normalized cyclomatic complexity、nesting、logical
LOC 與 longest-function LOC。失敗分數為 `-1000.0`。Compiler、Function
Capability、Strategy Alignment 只保存為診斷資料。

## Match 與 Artifact owner

`evaluation/microrts_runner.py` 只負責七項 integration probe；
`evaluation/runtime_evaluation.py` 是唯一 match runner。

每場比賽只保存一份 canonical 壓縮 tick stream：`match_trace.jsonl.gz`。
Strategy Reflection 直接讀取同一份 trace；`match_log.jsonl.gz` 已移除。

支援的 run schema 只有 `eagle-run-v2`。每個 run 只有一份完整解析後的
`config.yaml`，generation 使用 compact candidate reference，candidate state
只放在 `candidates/<id>/candidate.json` 與其 stage artifact。舊的
`resolved_config.json`、`generation_metrics.jsonl`、`final_population.json`、
root `errors.jsonl` 與 run-v1 reader 已移除。

## 執行入口

```bash
./experiment.sh CONFIG_FOLDER_OR_YAML [--mock] [--skip-final-test]
./experiment.sh --resume RUN_DIR [--mock] [--skip-final-test]
./analyze.sh RUN_DIR
```

`experiment.sh`／`python -m eagle experiment` 統一管理 config discovery、
llama.cpp start/reuse/switch、health check、EA、resume、final test 與 owned-process
cleanup。舊的 `run.sh`、`run_env.sh`、`python -m eagle run`、
`python -m eagle runtime` 已移除。

以資料夾啟動批次時，該設定資料夾會建立 `experiment.yaml` 索引，逐筆記錄
「config 檔名 → 絕對 run folder」。索引在 run folder 建立後立即原子更新，
不會在下次執行時被當成 config；既有的 `experiment-v2` 同名設定檔不會被覆寫。

## 驗證

```bash
python3 -m compileall eagle evaluation generation
python3 -m unittest discover -s tests
git diff --check
```

完整 evolutionary experiment 不是一般 repository migration 的必要驗證。
