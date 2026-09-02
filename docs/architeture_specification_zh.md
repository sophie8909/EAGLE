# EAGLE 架構說明（中文摘要）

狀態：2026-08-31 現行 executable contract 的中文摘要。英文權威規格為
[`eagle_architecture_spec.md`](eagle_architecture_spec.md)。

## 系統定位

EAGLE 使用 LLM 在離線階段產生與改寫 Java MicroRTS agent。實際比賽執行時
不會呼叫 LLM。每個 phenotype 都是一份完整的
`ai.generated.CandidateAgent` Java 原始碼，不使用 patch、method-body map 或
runtime LLM policy。

## Candidate 與演化流程

Candidate 有兩種明確模式。預設 `generated_phenotype` 的 genotype 包含兩個
可演化 prompt：

1. `strategy_prompt`：遊戲 policy gene
2. `generation_prompt`：policy-to-Java translation gene

在預設模式，Java `CandidateAgent.java` 只屬於 phenotype／evidence，不會傳給
子代。`inherited_genotype` 則加入第三個完整 Java component。Uniform Crossover
對 policy、generation prompt 與 Java 各自獨立選 parent，保存三者來源 ID；
Generator 成功產生的 child Java 會成為下一代可選取的 Java component。這是
明確設定且有版本的 genotype，不是舊版隱含的 `previous_code` 欄位。

新建立的 candidate ID 使用 `gen_<四位 generation>_<12 位十六進位>`，例如
`gen_0007_3a81c65d20bf`，讓 candidate artifact folder 可直接按 generation
辨識與排序。從既有 artifact 或 resume 載入的明確 ID 不會被重新命名。

每一代依序執行 seeded lexicase parent selection、crossover、可選的 Strategy、
Code 或 Balance mutation、完整 Java generation、validation、compilation、integration、
180 場 evaluation、AOS credit，以及 seeded lexicase survivor selection。Survivor
selection 使用 joint parent-plus-offspring 的 `(mu + lambda)` 候選池，不放回地
選回固定族群；父代沒有 age bonus，子代也沒有優先權。父子皆為 `n` 時即為
`(n + n)`。

`random_seed` 影響 EA 隨機、lexicase case 順序、operator、crossover、mutation
intent 與 reflection sampling。MicroRTS match 不宣稱 seeded reproducibility；
重複比賽只用 `round_index` 識別。

## Reflection 與 Prompt

Reflection operator mode 只有三種：

- `static`
- `aos_opponent`
- `aos_head2head`

兩種 adaptive mode 都以 mutation context 實際使用的 evidence parent 作為
`comparison_parent_id`：Strategy 依 policy component provenance；預設模式的 Code／
Balance 依 generation-prompt provenance；inherited 模式的 Code／Balance 依 Java
component provenance。Crossover 後即使 component 來自第二個 direct parent，也不會
再固定把 AOS reward 歸到第一個 parent。`aos_opponent` 重用一般 180 場 evaluation，
`aos_head2head` 則對同一 comparison parent 執行額外 18 場 direct matches。

Strategy Mutation 只修改 `strategy_prompt`；Code Mutation 只修改
`generation_prompt`。Balance Reflection 只接收依 opponent、map 與 candidate
side 匯總的 W/D/L 表，辨識弱 cell 後依序重寫兩個 prompt；兩次 rewrite 都成功才
原子地套用，任何一步失敗都保留兩個原 prompt。Balance 的 Code Prompt Rewriter
同樣只回傳 `remove_rule_ids`／`add_rules` delta，經驗證後確定性組成 canonical
`generation_prompt`，不接受未驗證的整份 replacement prompt。歷史上由 Balance
產生但不符合 rule grammar 的 marked prompt，只在 rewrite boundary 視為零條可保留
規則並由合法 delta 取代，不會複製污染內容。三者完成後都必須重新產生完整 Java。

Strategy Reflection 只使用 policy 與 match evidence。Match Commentator 不會收到
Java 或 generation prompt；Coach 不會收到 Java 或 compiler diagnostics。Code
Reflection 在預設模式比較 policy 與當前 Java phenotype；在 inherited 模式則
比較 child 當前 policy 與 independently selected Java component。兩者皆可選用
static/compiler evidence，但不使用 raw game logs；Code Prompt Rewriter 只收到
原 generation prompt、其 canonical reusable-rule view、alignment review 與 immutable
API guide。Reviewer 只會看到 strategy marker 之間的可編輯 Java；固定 scaffold
欄位與 helper 不會作為 candidate 行為證據。Generator 永遠使用兩個 prompt gene
與固定 checked-in Java scaffold，且在 inherited 模式額外收到完整 inherited Java。

Code Prompt Rewriter 固定回傳 `remove_rule_ids` 與 `add_rules`。新增規則必須使用
固定 category 且為 policy-agnostic prose，不得寫入特定 strategy、unit type、Java/API
symbol 或 scaffold 修改；runtime 會產生穩定 rule ID、依序套用 delta，並確定性組成
最多十條規則的 canonical `generation_prompt`。Legacy free-form prompt 可讀取，但下次
成功 Code Reflection 時不會被複製進新 rule set。Generation 0 依 candidate mode 分流：預設模式仍是
每個 seed 檔建立一個 candidate，直接載入 `initial_java_seed_path`，不呼叫
Generator；inherited 模式必須只有一個 seed policy，將同一份 policy 與 callable
no-op Java 複製到 `population_size` 個 genotype，並對每個 candidate 各呼叫一次
Generator。因此 population 10 會有 10 份 request／response，也可能得到 10 份
不同 Java。三份 `static_0826_seed_variants` config 都使用此模式，後續每代以
`10 + 10` joint pool 做 lexicase survivor selection。

Callable no-op Java 保留完整 action helper API，但 `decide` 不發出 action；同一
檔案同時是這三份設定的初始 Java component 與 immutable scaffold。空白 policy
的 Strategy Alignment 仍記為 `not_applicable`、`score: null`，且不建立 alignment
LLM attempt。

所有走 Generator 的 candidate 可用 `generation_max_attempts` 做有界
compile-guided decoder。Attempt 1 使用權威的 active genotype 生成請求；若
extraction 沒有得到完整 source，下一
次仍重送 base request。若完整 source 在 validation 或 javac 失敗，下一次改用獨立
的 Java repair prompt，內容必須包含未改動的權威 genes（inherited 模式也含 Java component）、immutable
action API guide、canonical scaffold、標示為 untrusted 的前一次完整 source，以及
只屬於前一次 attempt 的結構化診斷。每次實際 request、source、hash、repair chain
和 evidence 都獨立保存。

Compile-guided decoder 只修正 phenotype 的可驗證編譯問題，不是 Code Reflection，
也不得修改 gene、策略意圖、lineage、AOS 狀態或 selection case。固定 scaffold-only
問題要求 strategy region token 完全不變；其他修正另以 deterministic similarity
guard 阻擋沒有診斷依據的大幅重寫，但此 guard 不能證明語意等價。每個通過
validation 的完整 source 最多編譯一次，第一個編譯成功的 attempt 直接成為唯一
canonical phenotype/classes；全部失敗時由最後一次 attempt 決定 failure stage，
其 source 只算 generation evidence，不會偽裝成 phenotype。Integration 與 180 場
evaluation 只對選中的 attempt 執行一次，且 integration/runtime failure 不會觸發
重新生成。舊設定預設仍為一次，`static_0824` 四個 production config 才明列上限
五次。

模型回覆仍必須是一份具有正確 package、class、constructor、lifecycle method、
security contract 與唯一 strategy marker pair 的完整 Java。通過此前置 envelope
檢查後，系統會用「設定中的 canonical scaffold＋模型回覆的 strategy region」
確定性建立 `normalized_candidate.java`。因此模型刪除未使用的固定 method、改寫
固定註解或重新排版固定區時，差異仍保留在 raw／extracted evidence，但不會進入
validation、javac 或 phenotype；partial、結構錯誤或含禁止行為的回覆不會因這個
正規化步驟被放行。

策略區的座標／佔用查詢只能呼叫固定的
`isFreeCell(context, x, y)`；它會先檢查 active map bounds，再查詢佔用。
直接呼叫 `GameState.free(...)`、`PhysicalGameState.getTerrain(...)` 或
`getUnitAt(...)` 都會在 deterministic validation 被拒絕並成為 decoder repair
evidence。固定的 `commandMove`、`commandBuild` 也會以目前 `GameState` 的
bounds 擋下非法座標，避免抽象 action 帶著地圖外座標進入 MicroRTS。

結構化輸出會保留原始 response，並只在 parser 邊界正規化已知的模型格式差異：
賽評的 `match_analysis/key_observations.time` 與 Reviewer 將文字修正拆成陣列的
情形。缺少數字 tick、必要欄位、alignment classification 或跨越 role 責任邊界
仍會判定失敗。Commentator 與 Coach 的 transport、parse、semantic validation
共用有界重試；每次 attempt 保存 UTC 起訖時間，並在 run `timing.jsonl` 寫一筆
不重複 prompt／response 的 timing event。

Strategy Reflection 的 candidate artifact 會在 `mutation/strategy_reflection/`
保存：parent
`strategy_prompt`、按 Commentator 呼叫順序排列的 match、各次 Commentator
解析結果、Coach 的結構化與最終 render input、Coach raw／parsed output、正規化後的
child `strategy_prompt`，以及實際交給 Generator 的 strategy 值。系統沒有另設
`policy` 欄位；可重用策略就是 genotype 的 `strategy_prompt`。每代另有只保存
artifact reference 的 policy JSONL sidecar，其他 mutation operator 的 candidate
也不會被排除。Coach parsed output 會原樣保留模型回顯，但 validated
`coach_result.parent_strategy_prompt` 一律取自權威的 input gene，不信任模型回顯。
這些新增內容只供觀測，不改變 prompt、sampling、selection、fitness 或
evaluation。

新 candidate artifact 將兩個 prompt gene 放在 `genotype/policy_prompt.txt` 與
`genotype/code_generation_prompt.txt`；inherited 模式另保存
`genotype/inherited_java.java` 與 `java_parent_id`。Generator 輸出放在
`phenotype/CandidateAgent.java`；Code Reflection evidence 放在
`mutation/code_reflection/`；Balance Reflection evidence 放在
`mutation/balance_reflection/`，並保存 W/D/L table、reflector 與兩個 rewriter 的
request/response evidence。Snapshot JSON 不重複內嵌完整 inherited Java，resume
由 canonical genotype 檔重建。

所有 executable prompt body 都放在 `prompts/`，一個 prompt 一個 UTF-8
`.txt` 檔。`prompts/manifest.toml` 只保存 metadata 與 placeholder contract。
Python 與 YAML 不再接受 inline prompt、seed template 或重複 prompt body。

## Evaluation

Evolution Evaluation 固定使用十個 opponent：PassiveAI、RandomAI、
RandomBiasedAI、LightRush、HeavyRush、WorkerRush、AllInBot、Mayari、COAC、TMA。
每個可執行 candidate 使用同一份 Java source 與 class directory，進行：

`10 opponents × 3 maps × 3 rounds × 2 sides = 180 matches`

每個 `evaluation.maps` 項目可以各自指定正整數 `tick_limit`；只有 path 的舊格式
則沿用 top-level `tick_limit`。解析後的 per-map 上限會由 match matrix 帶入一般
evaluation、AOS head-to-head 與 final test，確保同一張 map 在三條路徑使用相同上限。

Fitness 是十個 maximized opponent case。失敗或 incomplete candidate 的每個
case 都是 `-1000.0`。加權 aggregate Game Performance 以 PassiveAI、RandomAI、
RandomBiasedAI 權重各 `0.5`、三個 rush opponent 各 `1`、其餘四個 opponent 各
`2` 計算，固定分母為 `12.5`，且只用於報表。
WorkerRush 使用 vendored 的 upstream 實作，不再以繼承 LightRush 的重複行為
充當 identity adapter。每代的 expected/completed match count 是所有 candidate
的加總，而不是第一個 candidate 的值。

AllInBot 的 preflight 仍驗證 pinned upstream 原始 class 與 JAR hash；實際 search
與 final test 則在 candidate class tree 之外編譯 reflection-only
`ai.eagle.SafeAllInBot`。adapter 僅在 upstream delegate 拋出 `Exception`、回傳
null 或無效 action 時，寫出一次 stderr marker 並永久改為合法 passive action；
不捕捉 `Throwable` 或嚴重 JVM error。若該隔離使對局完成，artifact 明確保存
`fault_scope=opponent`、contained/recovered、marker/reason 與
`scoring_neutralized=true`；保留原始 observed result，但 candidate 的計分一律是
零分 draw。它不會變成 candidate win，也不是 candidate runtime failure。

Code Quality 也是 diagnostic，不是 lexicase objective。成功分數為：

`100 - (40C + 25N + 20L + 15F)`

其中 C、N、L、F 分別是 normalized cyclomatic complexity、nesting、logical
LOC 與 longest-function LOC。失敗分數為 `-1000.0`。Compiler、Function
Capability、Strategy Alignment 只保存為診斷資料；空白 policy 的 Strategy
Alignment 記為不適用且不呼叫 LLM。

## Match 與 Artifact owner

`evaluation/microrts_runner.py` 只負責七項 integration probe；
`evaluation/runtime_evaluation.py` 是唯一 match runner。

Integration 不使用空白 state：probe 會載入真實、含雙方 base/worker 的
`basesWorkers8x8.xml` 兩次，分別以獨立的 one-argument candidate instance 與
獨立 GameState 呼叫 player 0／player 1，確認 `PlayerAction` 非空、integrity
合法、可 `issueSafe` 並各 cycle 一次。這能在 180 場前攔截座標越界與跨 side
state 殘留等 runtime 問題；integration failure 只記錄 evidence，不會回到 decoder
retry。

每場比賽只保存一份 canonical 壓縮 tick stream：`match_trace.jsonl.gz`。
Strategy Reflection 直接讀取同一份 trace；同代 sibling 建立完成前保留 parent
trace，generation 原子落盤後才清理非 survivor 的 trace。`match_log.jsonl.gz` 已移除。

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
