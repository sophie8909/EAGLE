# EAGLE 架構說明（中文摘要）

狀態：2026-08-20 現行 executable contract 的中文摘要。英文權威規格為
[`eagle_architecture_spec.md`](eagle_architecture_spec.md)。

## 系統定位

EAGLE 使用 LLM 在離線階段產生與改寫 Java MicroRTS agent。實際比賽執行時
不會呼叫 LLM。每個 phenotype 都是一份完整的
`ai.generated.CandidateAgent` Java 原始碼，不使用 patch、method-body map 或
runtime LLM policy。

## Candidate 與演化流程

Genotype 固定包含兩個可演化 prompt：

1. `strategy_prompt`：遊戲 policy gene
2. `generation_prompt`：policy-to-Java translation gene

Java `CandidateAgent.java` 是 phenotype／evidence，不是 genotype，也不會傳給
子代。Uniform Crossover 只對兩個完整 prompt component 獨立選 parent，並只保存
這兩個 component 的來源 candidate ID。

新建立的 candidate ID 使用 `gen_<四位 generation>_<12 位十六進位>`，例如
`gen_0007_3a81c65d20bf`，讓 candidate artifact folder 可直接按 generation
辨識與排序。從既有 artifact 或 resume 載入的明確 ID 不會被重新命名。

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

Strategy Reflection 只使用 policy 與 match evidence。Match Commentator 不會收到
Java 或 generation prompt；Coach 不會收到 Java 或 compiler diagnostics。Code
Reflection 則比較 policy 與當前 Java phenotype，可選用 static/compiler evidence，
但不使用 raw game logs；Code Prompt Rewriter 只收到原 generation prompt 與
alignment review。Generator 使用兩個 gene 加上固定 checked-in Java scaffold，
不使用 parent Java。

Code Prompt Rewriter 固定回傳且只回傳
`{"rewritten_prompt":"..."}`。Generation 0 是唯一 decoder 例外：所有 seed
candidate 使用空白 `strategy_prompt`，直接載入 `initial_java_seed_path` 的舊版
初始 Java，不呼叫 LLM；之後仍經相同 validation、compilation、integration 與
evaluation。這份 Java 只是 gen0 phenotype，不是第三個 gene，也不會遺傳。

結構化輸出會保留原始 response，並只在 parser 邊界正規化已知的模型格式差異：
賽評的 `match_analysis/key_observations.time` 與 Reviewer 將文字修正拆成陣列的
情形。缺少數字 tick、必要欄位、alignment classification 或跨越 role 責任邊界
仍會判定失敗。

Strategy Reflection 的 candidate artifact 會在 `mutation/strategy_reflection/`
保存：parent
`strategy_prompt`、按 Commentator 呼叫順序排列的 match、各次 Commentator
解析結果、Coach 的結構化與最終 render input、Coach raw／parsed output、正規化後的
child `strategy_prompt`，以及實際交給 Generator 的 strategy 值。系統沒有另設
`policy` 欄位；可重用策略就是 genotype 的 `strategy_prompt`。每代另有只保存
artifact reference 的 policy JSONL sidecar，其他 mutation operator 的 candidate
也不會被排除。這些新增內容只供觀測，不改變 prompt、LLM 呼叫、sampling、
selection、fitness 或 evaluation。

新 candidate artifact 將兩個 gene 放在 `genotype/policy_prompt.txt` 與
`genotype/code_generation_prompt.txt`，Java phenotype 放在
`phenotype/CandidateAgent.java`；Code Reflection evidence 放在
`mutation/code_reflection/`。舊路徑只能由 loader 隔離讀取，不會恢復舊的第三 gene。

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
WorkerRush 使用 vendored 的 upstream 實作，不再以繼承 LightRush 的重複行為
充當 identity adapter。每代的 expected/completed match count 是所有 candidate
的加總，而不是第一個 candidate 的值。

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
./experiment.sh --resume RUN_DIR_OR_CONFIG_FOLDER [--mock] [--skip-final-test]
./analyze.sh RUN_DIR
```

`experiment.sh`／`python -m eagle experiment` 統一管理 config discovery、
llama.cpp start/reuse/switch、health check、EA、resume、final test 與 owned-process
cleanup。舊的 `run.sh`、`run_env.sh`、`python -m eagle run`、
`python -m eagle runtime` 已移除。

以資料夾啟動批次時，該設定資料夾會建立 `experiment.yaml` 索引，逐筆記錄
「config 檔名 → 絕對 run folder」。索引在 run folder 建立後立即原子更新，
不會在下次執行時被當成 config；既有的 `experiment-v2` 同名設定檔不會被覆寫。

`--resume` 指向設定資料夾時會讀取既有索引，不會清空它。系統先續跑已索引但
search 或必要 final test 尚未完成的 run，跳過完整完成者，再依檔名字典序執行
其餘尚未建立 run 的 config；新 run 仍會原子寫回同一索引。若 search 已完成、
只缺 final test，則不會為該步驟啟動 llama.cpp。

## 驗證

```bash
python3 -m compileall eagle evaluation generation
python3 -m unittest discover -s tests
git diff --check
```

完整 evolutionary experiment 不是一般 repository migration 的必要驗證。
