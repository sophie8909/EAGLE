# EAGLE 架構說明（中文摘要）

狀態：2026-10-21 現行 executable contract 的中文摘要。英文權威規格為
[`eagle_architecture_spec.md`](eagle_architecture_spec.md)。

## 系統定位

在 `java_materialization_mode: llm` 下，EAGLE 使用 LLM 在離線階段產生與改寫 Java MicroRTS agent；`deterministic_dsl` 以版本化 compiler 產生 Java；`framework_slots` 在 fresh startup inline 呼叫 Groq GPT-OSS bootstrap 建立完整 Java framework 與有限 typed slots，再由 `framework.evolution_mode` 選擇 local EA 或 Coach 輔助的完整 genome 選擇。實際比賽執行時
不會呼叫 LLM。每個 phenotype 都是一份完整的
`ai.generated.CandidateAgent` Java 原始碼，不使用 patch、method-body map 或
runtime LLM policy。

## Candidate 與演化流程

### Java Materialization 三模式
`candidate_java_mode` 與 `java_materialization_mode` 是不同設定。後者未設定時
預設 `llm`，維持既有流程。`deterministic_dsl` 僅以完整的
`strategy_prompt` 作為 active genotype；`generation_prompt` 與 inherited Java
即使保留也只是 inactive compatibility data，不參與 crossover 或 phenotype
materialization。此模式只允許整份 policy 的 copy/crossover 與 Strategy
Mutation，不做 rule-level crossover，並停用 Prompt Reflection、Code Reflection/
source repair、Java Generation 與 compile-repair LLM。版本為
`eagle-dsl-compiler-v1` / `eagle-dsl-java-v1`。Compiler 產生完整 Java 後仍執行
validation、javac、Integration、semantic probe 與 evaluation；失敗不會退回
LLM。此 migration 的測試、真實整合與 smoke-run 結果尚待 implementation owner
回報。
Gen 0 的 WorkerRush seed 是唯一封閉的 reference policy：deterministic compiler
直接委派到 vendored `ai.abstraction.WorkerRush` 並重播完整 action vector，同時
記錄官方來源 SHA-256；LLM 生成與 Strategy Mutation 不得產生 reference policy。
Deterministic 設定必須使用 `candidate_java_mode: generated_phenotype` 與 `parent_evaluation_mode: reuse_cached`，其他值會被拒絕。

### Groq framework 與有限 slots

`framework_slots` 會在 fresh experiment startup inline 執行 bounded Groq GPT-OSS
bootstrap。未設定 `framework.bundle_path` 時，必須提供
`framework.design_brief`；`framework.model` 可省略，預設為
`openai/gpt-oss-120b`。每個 replicate 會建立獨立 framework；若要跨 seeds
固定 framework，請明確共用同一 `bundle_path`。Standalone
`python -m eagle framework` 仍支援預先建立 bundle 的相容流程。

Experiment 啟動時會將 bundle exact bytes 寫入 run 的
`framework/bundle.json` 並記錄 SHA-256。Candidate 的唯一 active genotype 是
`control_genome`。`framework.evolution_mode` 預設 `local`，使用 seeded local
sampling、逐 slot crossover 與最多一個 slot mutation；`llm_coach` 是 opt-in，
由 experiment model 為每個 Gen 0 slot 選完整 genome，Strategy Mutation 則沿用
最差 completed match → Commentator → Coach。兩種 policy 都使用相同凍結 bundle
和 `eagle-framework-slots-v1` materializer，不呼叫 Java Generator、source
repair 或 compile repair。Resume 僅讀 run-owned frozen bundle，驗證 hash 並比較
`design_brief`、bootstrap model、evolution mode，不會重新 bootstrap。
在 `llm_coach` 中，可用 `framework.coach_offspring_probability` 在 crossover
前選擇 Coach offspring 路徑。預設 `null` 保留舊設定的 Coach 行為；明確數值
範圍為 `0.0` 到 `1.0`，且只允許 `llm_coach`，透過獨立 seeded RNG 選擇比例。
此路徑選擇與 `mutation_rate` 無關。Coach 路徑只複製 parent A
的 genome，再由 Coach 提出完整 genome，不執行 crossover，也不使用 parent B。
傳統路徑則保留設定的 `crossover_rate`、donor 選擇，並依
`mutation_rate` 執行 local 單一 slot mutation。`0.0` 表示後續 offspring 全走
傳統路徑，`1.0` 表示全走 Coach；Gen 0
仍一律由 Coach 選完整 genome。Resume 會比較有效設定；舊 manifest 缺少欄位時
視為 `null`。`local` 模式設定數值會被拒絕。
Bootstrap 失敗會保留 attempts 與 failed manifest，pending config 在可用 frozen
bundle 建立前不可 resume；失敗 replicate 不會加入 folder-batch index，資料夾
重跑可再次啟動缺少的 slot。Mock 模式若只有 `design_brief` 而沒有既有
`bundle_path` 會拒絕執行，確保不呼叫 API。Groq 的 `GROQ_API_KEY` 從
process environment 讀取，Mistral 的 key 從 `api_key/mistral` 讀取，兩者
都絕不寫入 config 或 artifact。完整契約見
[framework slots](architecture/framework_slots.md)。

Repository 另提供固定初始 framework 範例：
`configs/framework_coach_mock.yaml` 搭配
`configs/framework_bundles/fixed_worker_combat/bundle.json`。這個 bundle 是可
實際編譯與執行的完整 `CandidateAgent`，不是假的 placeholder；它暴露 27 個
可重組的有限 controls，涵蓋採集、建造、生產、兵種、攻擊門檻、目標排序、集結、
fallback 與防守，而不是把策略鎖成單一 WorkerRush。該 config 使用
明確的 `bundle_path`，因此只會跳過 framework bootstrap；後續使用
`execution_mode: openai` 與 `framework.evolution_mode: llm_coach`，由 managed
local llama-server 加上設定的 additional endpoint 執行 EA 的 LLM 呼叫。
Java render、validation、`javac`、Integration、semantic probe 與 MicroRTS
評估仍照常執行。
### LLM materialization lifecycle

以下 Candidate、genotype、source gate 與 generation 流程只描述
`java_materialization_mode: llm`；deterministic 模式見上方說明。

每個功能 profile 都以 `model`（或 `generation_model`）的一組本機欄位定義唯一
managed primary endpoint，並可在同一區段加入最多一筆有序的
`additional_endpoints`。Additional endpoint 的格式嚴格為
`{base_url, model}`，代表 EAGLE 不擁有的 OpenAI-compatible service；整個 profile
因此最多兩個 endpoint。`RuntimeManager` 只在 primary 提供兩個本機 runtime 路徑時啟停 llama.cpp，絕不
adopt、restart、signal 或 stop additional endpoint。每個 endpoint 在 candidate 工作前
都必須完成 chat-completion preflight，任何一個失敗都 fail closed，不會開始
candidate request。


Candidate Java state 有兩種明確模式。LLM materialization 下，預設 `generated_phenotype` 的 active genotype 包含兩個
可演化 prompt：

1. `strategy_prompt`：canonical versioned JSON DSL policy gene
2. `generation_prompt`：policy-to-Java translation gene

在 LLM materialization 的預設 candidate Java mode，Java `CandidateAgent.java` 只屬於 phenotype／evidence，不會傳給
子代。LLM materialization 搭配 `inherited_genotype` 時，會加入第三個完整 Java component。Uniform Crossover
對 policy、generation prompt 與 Java 各自獨立選 parent，保存三者來源 ID；
Generator 成功產生的 child Java 會成為下一代可選取的 Java component。這是
明確設定且有版本的 genotype，不是舊版隱含的 `previous_code` 欄位。

新建立的 candidate ID 使用 `gen_<四位 generation>_<12 位十六進位>`，例如
`gen_0007_3a81c65d20bf`，讓 candidate artifact folder 可直接按 generation
辨識與排序。從既有 artifact 或 resume 載入的明確 ID 不會被重新命名。

新 run 的 policy 只接受 `eagle-strategy-dsl-v1` JSON，由
`eagle/strategy_dsl.py` 驗證與正規化。`rules` 依順序包含 `actor`、`when`、`action`；
合法動作 guard 為內建語意，空 rules 表示 idle。DSL 在離線 Java generation 階段
實作，不新增 runtime interpreter。歷史自然語言 artifact 僅供唯讀；不相容舊 run
resume 必須清楚失敗，不能默默轉換 policy。Resolved config 保存
`evolution_protocol: eagle-dsl-pre-crossover-v1` 與
`strategy_policy_format: eagle-strategy-dsl-v1`，resume 在修改 artifact 前先檢查。
Controller state 使用 `eagle-reflection-operator-v6`。

每代先選 reproduction sources，再對每個來源以自身 policy 與精確 Java 執行
獨立 Code Reflection gate，通過後才允許實際 crossover／mutation。所有 contributor
都必須通過。缺陷來源改產生保留 policy／generation genes 的單一父代修正子代，
跳過 crossover／一般 mutation；診斷失敗不等於健康，也不能進入 variation。
來源 gate 使用兩個 worker；plan 依 canonical 順序進行 crossover 與 AOS 分配，
每個子代完成自己的依賴後立即進入 mutation、Code revision、Java decode／compile。
兩個 preparation worker 與單一 evaluation consumer 重疊運作：先準備好的個體
開始 integration、semantic probe 與 match，其他個體仍可交配、變異或生成。
沒有整批 reflection／generation 屏障。完成順序不改變 candidate 結果順序、
原始 ordinal、seed、固定對手快照或評分；match 維持最多十個 worker。
同 server origin 的所有功能共用兩個 request 名額，不同 host／port 可獨立並行。
每個 task 的 endpoint 由 canonical index 固定，相依呼叫與 retry 不改 route。
初始 policy 的固定 seed snapshot 與重複結果重試順序保持不變。中斷時取消排隊
工作並等待已執行 producer／worker 結束；trace 在相依工作與世代保存後才清理。


之後執行正常 mutation 的 AOS credit，以及
seeded lexicase survivor selection。Survivor
selection 使用 joint parent-plus-offspring 的 `(mu + lambda)` 候選池，不放回地
選回固定族群；父代沒有 age bonus，子代也沒有優先權。父子皆為
` 時即為
`(n + n)`。

`parent_evaluation_mode` 的 canonical 預設是 `reuse_cached`：父代不會在每一代
重新生成或重新評估。`regenerate_same_genotype` 只是一個非 canonical 的診斷 treatment，
而且只能搭配 `inherited_genotype` 與 `reflection_operator_mode: static`。它會為每個舊父代
建立新的 ID replica，保留完全相同的 policy、generation prompt、inherited Java 與 component
provenance，清空舊 phenotype／evaluation 狀態後重新走完整評估；survivor selection 只使用
replica 加 offspring，絕不覆寫或直接選回舊父代。每代的
`generation_<nnnn>_parent_rematerialization.json` 會保存 source→replica、genotype hash、
舊／新 Java hash、fitness、status 與是否被選中，供診斷比較。

`random_seed` 是整個 EA 的根 seed；初始化、選擇、operator、crossover、mutation、
reflection sampling、LLM request 與 retry 都依穩定任務身分衍生獨立 seed。
可控的執行流程永遠採用此規則，不再提供 deterministic/non-deterministic 切換。
一般評估、父子對戰及 final test 都傳遞並保存每場比賽的 JVM seed；多執行緒依固定
match 順序彙整，seed 與決策不依完成順序或 thread 身分。LLM endpoint assignment
也只由 canonical input index 與 resolved config 中保存的 endpoint 順序決定。GPU
layer 固定為 `999`、model thread 固定為 `8`、managed-local server slot 固定為 `2`、LLM worker 固定為 `2`、match worker 固定為 `10`，
由 `eagle/execution.py` 統一管理。CUDA/GPU preflight 必須成功，無 GPU 時明確失敗，不回退 CPU。
LLM temperature 仍可設定。相同版本的新 checkpoint 保存 stagnation 狀態，resume 可延續相同軌跡。

外部 LLM 可能忽略 seed 或改變模型；GPU kernel、batching、浮點運算、外部 opponent
私有 RNG 與時間預算／timeout 仍可能造成差異。固定 seed 無法保證這些外部輸出相同；
raw request/response hash 與 match seed 是追查差異的證據。時間戳、PID 與 run folder
名稱屬於操作紀錄，不要求逐位元相同。舊版 run 的 artifacts 可讀取，但本次 seed stream
規則改變後不保證沿用原本演化軌跡。

若要排除 server 內部狀態對 seed 實驗的影響，可使用
`scripts/test_llm_seed_restarts.py`；它會在每個 seed 的重複 request 後完整停止
並重新啟動 llama-server，再測下一個 seed，並保存每個 seed 的 raw response、hash
與 server lifecycle。

正式 experiment 也採用相同的 run 邊界：每個 run（包含 `runs` replicate）開始前
會停止上一個 EAGLE-owned llama-server，再依該 run 的 resolved config 啟動新的
server；同一個 run 內所有角色固定綁定各自 server，不再切換模型。

## Reflection 與 Prompt

Reflection operator mode 只有三種：

- `static`
- `aos_opponent`
- `aos_head2head`

兩種 adaptive mode 都以 mutation context 實際使用的 evidence parent 作為
`comparison_parent_id`：Strategy 依 policy component provenance；預設模式的 Prompt 依 generation-prompt provenance；inherited 模式的 Prompt 依 Java
component provenance。Crossover 後即使 component 來自第二個 direct parent，也不會
再固定把 AOS reward 歸到第一個 parent。`aos_opponent` 重用一般 180 場 evaluation，
`aos_head2head` 則對同一 comparison parent 執行額外 18 場 direct matches。

Strategy Mutation 只修改 `strategy_prompt`。Prompt Mutation 是舊 Code Reflection
行為：只用 policy、父代 Java 的可編輯策略區、不可變 API 指南，以及與該 Java
來源完全對應的 validation／compiler 錯誤，經 Reviewer 與 Rewriter 只修改
`generation_prompt`。Code Reflection 是 reproduction source 的獨立 gate，不是第三個一般 mutation，
不參與 adaptive probability 或 reward。v6 結論只有兩個獨立維度：
`strategy_fidelity`（faithful／unfaithful／ambiguous_strategy）與
`code_correctness`（correct／incorrect）。只允許失敗維度提出具體證據與最小修正；
correctness 包含真正 compilation、runtime、control-flow 缺陷與 game／API 違規。
拒絕未知欄位、精簡或美化重構指令；ambiguous policy 且 Java correct 不需修正。
兩階段不接收勝負、fitness、match 或 trace 作為優化依據。Strategy Reflection
仍使用恰好一場最差 completed match，Coach 的新 policy 必須通過 DSL 驗證。

設定中的 `model` 負責 initial policy、reflection 與 prompt rewrite。可選的
`generation_model` 固定負責 Java generation、Code revision 與 compile repair，
直接呼叫已啟動的 server。不同 model 必須設定不同 host／port，由操作者啟動；
EAGLE 不再依 phase 切換模型。省略時所有功能共用 `model` 並行呼叫。
primary 省略 `model.path` 與 `model.llama_server` 時直接使用外部 server；
兩者皆提供才管理本機 runtime，僅提供其一屬設定錯誤。generation 與 additional
endpoints 一律由外部管理。


所有會產生或解讀策略的 LLM 階段共用同一份不可變的
`microrts_gameplay_contract`：包含完整 entity、production graph、合法 action 與
可觀察 state。它允許策略大幅改成其他類型，但每個條件都必須能由遊戲 state
觀察，每個回應都必須能用 MicroRTS 合法動作執行；不能把一般 RTS 的概念帶進
policy。這份 contract 是固定 domain context，不是比賽 evidence；Strategy 與 Code
Reflection 使用它來限制輸出為可執行的遊戲規則，而不是根據勝負調整策略。

Strategy Reflection 只使用 policy 與 match evidence，並依記錄的
`strategy_parent_id` 從該 parent evaluation 挑選恰好一場最差的已完成比賽：
優先採用最低的有限數字 per-match `performance`；缺少或非有限時，以 loss
`-100`、draw `0`、win `100` 作為分數；同分依穩定 `match_id` 排序，不受 seed
影響，失敗比賽不參與。正數 legacy `sample_count` 與 `sample_budget` 仍可接受，
但實際選取數固定為一場。Match Commentator 只診斷該場；Coach 收到全部比賽的
global evaluation summary 與恰好一份該場診斷。若該場 trace 無法使用或
Commentator 重試耗盡，沿用既有失敗處理並保留 parent policy，不改選其他比賽。
Match Commentator 不會收到 Java 或 generation prompt；Coach 不會收到 Java
或 compiler diagnostics。Prompt
Reflection 在預設模式比較 policy 與當前 Java phenotype；在 inherited 模式則
比較 child 當前 policy 與 independently selected Java component。兩者皆可選用
static/compiler evidence，但不使用 raw game logs；Prompt Rewriter 只收到
原 generation prompt、其 canonical reusable-rule view、alignment review 與 immutable
API guide。Reviewer 只會看到 strategy marker 之間的可編輯 Java；固定 scaffold
欄位與 helper 不會作為 candidate 行為證據。Strategy／Prompt／無 mutation 路徑的
Generator 使用兩個 prompt gene 與固定 checked-in Java scaffold，且在 inherited
模式額外收到完整 inherited Java；Code Reflection 成功路徑不呼叫這個 Generator。

Prompt Rewriter 固定回傳 `remove_rule_ids` 與 `add_rules`；每次 mutation 必須
新增一條 12–240 字元的 policy-agnostic 規則，並最多移除一條既有規則。新增規則
必須使用固定 category，不得寫入特定 strategy、unit type、Java/API symbol 或
scaffold 修改；runtime 會產生穩定 rule ID、依序套用 delta，並確定性組成最多十條
規則的 canonical `generation_prompt`。若 semantic validation 拒絕輸出，下一次有界
重試會收到原 request 與精確錯誤，且失敗 delta 不會被部分套用。Legacy free-form
prompt 可讀取，但下次成功 Prompt Reflection 時不會被複製進新 rule set。Generation 0 依 candidate mode 分流：預設模式仍是
每個 seed 檔建立一個 candidate，直接載入 `initial_java_seed_path`，不呼叫
Generator；inherited 模式必須只有一個 seed policy，將同一份 policy 與 callable
no-op Java 複製到 `population_size` 個 genotype，並對每個 candidate 各呼叫一次
Generator。因此 population 10 會有 10 份 request／response，也可能得到 10 份
不同 Java。三份 `static_0826_seed_variants` config 都使用此模式，後續每代以
`10 + 10` joint pool 做 lexicase survivor selection。失敗子代仍保留在 joint
pool 的診斷與 artifact 紀錄中，但在有效候選足以填滿族群時不得取代已完成評估的父代；
因此整批子代失敗時會保留父代。若完成評估的候選少於目標族群大小，selection 會明確失敗。

新增的 `initial_population_mode: llm_generated_policies` 是另一個明確的
generation-0 邊界：第 1 個 candidate 保留設定檔中的 Worker Rush policy，第 2–10
個 candidate 各自以「Generate one RTS strategy」prompt 呼叫 LLM，得到 9 份不同的
RTS policy prompt；這裡的 random 指 LLM 策略取樣，不是 MicroRTS `RandomAI` agent。
這些初始 policy request 也包含相同 gameplay contract，因此可以產生不同策略，
但不能描述遊戲中不存在或無法觀察的規則。
10 個 candidate 的 inherited Java 都使用同一份 checked-in
`java_seeds/worker_rush/CandidateAgent.java`，但它只作為 Java Generator 的 prompt
context，不是 generation-0 phenotype。每一份初始 policy 都各自呼叫 Java Generator，
產生、驗證並編譯自己的完整 Java agent。
每次初始 policy 呼叫的 request、raw response、解析／重試結果與 UTC timing 都保存在
該 candidate 的 `initialization/policy_generation/`，run `timing.jsonl` 只另存一筆
不重複 prompt／response 的 request timing event。

Callable no-op Java 保留完整 action helper API，但 `decide` 不發出 action；同一
檔案同時是這三份設定的初始 Java component 與 immutable scaffold。一般 evaluation 不會呼叫 Function Capability 或 Strategy Alignment，也不會
寫入相關診斷檔或 timing；standalone helper modules 保留供明確呼叫的工具使用。

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
確定性建立
normalized_candidate.java`。因此模型刪除未使用的固定 method、改寫
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

Coach 與 strategy-contract-rewriter 改用每條 rule 一筆的 JSONL。每個
`strategy_rule` record 都標示角色欄位（Coach 為 `new_strategy_prompt`，rewriter
為 `revised_strategy_prompt`），並只攜帶一條完整 rule。Parser 逐行驗證，依原始
行序保留合法 rule；非 JSON 說明、截斷行、欄位錯誤或語意非法的整條 rule 都會記錄
後丟棄。只要至少留下一條合法 rule 就成功，只有全部 rule 都壞掉才重試／失敗。
Parser 不會在 rule 內部刪 condition、action 或欄位來修補它。完整 parent policy
回顯不符合 rule-record schema，因此不會被誤認為 child。舊的完整 JSON／完整 JSON
fence 仍以整體驗證方式相容，原始 response 也會原樣保存，另存逐行抽取報告。

Strategy Reflection 的 candidate artifact 會在 `mutation/strategy_reflection/`
保存：parent
`strategy_prompt`、唯一選出的最差比賽及其 Commentator 解析結果、Coach 的結構化
與最終 render input（含全部比賽的 global evaluation summary）、Coach
raw／parsed output、正規化後的
child `strategy_prompt`，以及實際交給 Generator 的 strategy 值。系統沒有另設
`policy` 欄位；可重用策略就是 genotype 的 `strategy_prompt`。每代另有只保存
artifact reference 的 policy JSONL sidecar，其他 mutation operator 的 candidate
也不會被排除。Coach parsed output 會原樣保留模型回顯，但 validated
`coach_result.parent_strategy_prompt` 一律取自權威的 input gene，不信任模型回顯。
這些 artifact 不新增 fitness objective，也不改變 AOS 或 policy state。

新 candidate artifact 將兩個 prompt gene 放在 `genotype/policy_prompt.txt` 與
`genotype/code_generation_prompt.txt`；inherited 模式另保存
`genotype/inherited_java.java` 與 `java_parent_id`。Generator 輸出放在
`phenotype/CandidateAgent.java`；Prompt Reflection evidence 放在
`mutation/prompt_reflection/`；Code Reflection evidence 放在
`mutation/code_reflection/`，並保存父代 Java、反思 request/raw response/parsed
conclusion、帶入該 conclusion 的修碼 request/raw response
與抽取出的 reflected source。Snapshot JSON 不重複內嵌完整 inherited Java，resume
由 canonical genotype 檔重建。

Run 的 resolved `config.yaml` 會依設定順序保存每個 profile 的 primary 與
additional endpoint 清單；這個順序屬於 execution identity。Resume 不允許新增、
刪除、重排或改指 endpoint。每筆 LLM call index 與 `timing.jsonl` request event
都必須記錄實際處理該 request 的 endpoint 與 model，不能只記 profile primary。

所有 executable prompt body 都放在 `prompts/`，一個 prompt 一個 UTF-8
`.txt` 檔。`prompts/manifest.toml` 只保存 metadata 與 placeholder contract。
Python 與 YAML 不再接受 inline prompt、seed template 或重複 prompt body。

## Evaluation

預設 `evaluation.mode: fixed_roster` 固定使用十個 opponent：PassiveAI、RandomAI、
RandomBiasedAI、LightRush、HeavyRush、WorkerRush、AllInBot、Mayari、COAC、TMA。
每個可執行 candidate 使用同一份 Java source 與 class directory，進行：

`10 opponents × 3 maps × 3 rounds × 2 sides = 180 matches`

每個 `evaluation.maps` 項目可以各自指定正整數 `tick_limit`；只有 path 的舊格式
則沿用 top-level `tick_limit`。解析後的 per-map 上限會由 match matrix 帶入一般
evaluation、AOS head-to-head 與 final test，確保同一張 map 在三條路徑使用相同上限。

Fixed-roster fitness 是十個 maximized opponent case。Self-play 則只有單一
`game_performance` objective；失敗或 incomplete candidate 的 active objective
為 `-1000.0`。固定 roster 的加權 aggregate Game Performance 以 PassiveAI、RandomAI、
RandomBiasedAI 權重各 `0.5`、三個 rush opponent 各 `1`、其餘四個 opponent 各
`2` 計算，固定分母為 `12.5`，且只用於報表；self-play 的等權重平均則直接作為 fitness。
WorkerRush 使用 vendored 的 upstream 實作，不再以繼承 LightRush 的重複行為
充當 identity adapter。每代的 expected/completed match count 是所有 candidate
的加總，而不是第一個 candidate 的值。

明確設定 `evaluation.mode: self_play` 時，opponent pool 容量由
`evaluation.self_play_opponent_library_capacity` 控制，預設為 50，包含固定
protected 成員且不得小於 10。初始 pool 是 `SEARCH_OPPONENT_REGISTRY` 的全部十個
opponent。`allinbot`、`mayari`、`coac`、`tma` 永久 protected，不參與淘汰賽；其餘六個
builtin baseline 與 generated agent 可參與。pool 未滿時收錄新穎且符合資格的 agent；滿額後，
每個新 entrant 以 seeded 抽樣挑戰一個非 protected incumbent，進行三張 map × 三輪 ×
雙方各一次，共 18 場 head-to-head。勝、和、敗分別計 1、0.5、0；只有勝場嚴格多於敗場
才能取代 incumbent。比賽不完整或發生錯誤時不得晉級，且保留失敗證據。Tournament 不呼叫
LLM，重用 entrant source/classes，並以既有 adapter 準備 defender。

Generation 0 評估全部十個 builtin source，並使用與後續 context 相同的固定 slot schema：四個
protected opponent 使用實際 case ID，其餘六個 source 放入 `self_play_000`…`self_play_005`。
Generation 1 與每個後續 `self_play_refresh_interval` 邊界（預設 Generation 1、6、11…）保留四個
protected case ID，並將從 pool 確定性抽樣的六個 non-protected opponent 放入這六個 diagnostic
slot。Context row 以 `source_opponent_id` 記錄 builtin source；builtin 的
`source_candidate_id` 與 `source_generation` 為 null。所有 slot 等權重，每位 candidate 仍執行
180 場。Context 變更時，先用相同 phenotype 建立 fresh-ID parent replica 並重評，只有同一
context 的 parent 與 offspring 可以一起 selection。

Pool 存於 `archives/self_play_opponents.json`，schema 為
`eagle-opponent-pool-v1`，含 capacity、protected IDs、member references 與 phenotype hashes。
每場 duel 存於 `archives/opponent_pool_tournaments/generation_NNNN/<entrant_id>/result.json`
及各 match 證據，並寫入 `opponent_pool_tournament` timing event。Pool state 存入既有
`resume_archives`，replay 前先還原。Self-play resolved config 必須含
`evaluation.self_play_pool_policy: tournament-v1`；缺少此 marker 的舊 resolved config 只能
檢視，不能依新政策 resume。Snapshot 使用 `eagle-self-play-snapshot-v4`、member references
與 context hash。舊 cohort helper 可保留供歷史讀取，但不再控制 active schedule。完整規範見
[英文架構規格](eagle_architecture_spec.md#9-evolution-evaluation)。

V4 snapshot 的 `runtime_identity` 會雜湊實際設定的 MicroRTS `src`、`bin`、`lib`、builtin
opponent JAR、adapter/support libraries 與 map 檔案 bytes。載入 snapshot 時，會先驗證這些
identity 才重用 cached fitness；runtime 或 map 資產變更時必須建立新 run。
`evaluation/game_performance.json` 同時保存 `evaluation_configuration`、
`evaluation_context_id`、`fitness_case_ids` 與分數，供 resume 驗證 context。Tournament 證據
保存 candidate defender 準備/改名後 runtime class tree hash；可取得時也保存 builtin source
與 resolved-class hash。

Self-play 以每個 tier 的最高
`game_performance` 為固定錨點，差距小於或等於 `1.0` 視為同級，不使用鏈式比較。
同級內 parent B 優先選擇與 parent A 語意距離最大者；survivor boundary 使用 seeded
max-min 語意多樣性。Self-play 目前要求 `reflection_operator_mode: static` 與
`parent_evaluation_mode: reuse_cached`。Context 取樣、resume 與舊 checkpoint 的相容性以
前述 `tournament-v1` 規範為準。

Self-play 對每個可執行完整 `CandidateAgent` 建立行為語意簽章：三張 configured map
各取 early／mid／late 一個可行動、非 terminal 的重載 `GameState`，共九個 probe。
每個 probe 使用新的 agent instance，將 unit action 依 unit ID 排序並 canonicalize
後雜湊；九個有序 action hash 向量相同才視為 library 中的 exact equivalent。語意距離是
九個 action hash 的 normalized Hamming distance；dataset 或 probe
順序不相容、或缺少簽章時只能作 fallback，不能被視為最 novel。完整結果以 phenotype
hash、dataset hash 與 normalization version 快取；probe 失敗只記 diagnostic，不改 fitness。

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
LOC 與 longest-function LOC。失敗分數為 `-1000.0`。Compiler 診斷仍供 reflection 與失敗記錄使用。一般 evaluation 不會呼叫
Function Capability 或 Strategy Alignment，也不會寫入相關診斷檔或 timing；
standalone helper modules 保留供明確呼叫的工具使用。

## Match 與 Artifact owner

`eagle/evaluation/microrts_runner.py` 只負責七項 integration probe；
`eagle/evaluation/runtime_evaluation.py` 是唯一 match runner。

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

離線分析以每個 generation artifact 中已選出的 population 作為該代 survivor
snapshot。圖表與 per-agent／per-opponent／per-match CSV 的 `generation` 是 survivor
所在的 snapshot 世代；candidate 自己的建立世代另存為 `birth_generation`。因此父代
若連續存活，會在每個實際存活的世代各出現一次，不會全部被畫回出生世代。

## 執行入口

```bash
./experiment.sh CONFIG_FOLDER_OR_YAML [--mock] [--skip-final-test]
./experiment.sh --resume RUN_DIR_OR_CONFIG_FOLDER [--mock] [--skip-final-test]
./analyze.sh RUN_DIR
```

跨世代固定評估使用獨立命令與輸出，不改變一般 `eagle.final_test`：

```bash
python -m eagle.fixed_evaluation --run-dir runs/<run> [--generations 0 5 10 15 20] [--seed <int>] [--output-dir <dir>]
```

預設世代為 0、5、10、15、20；未指定 seed 時讀取 run config。run 必須完成，每個指定 snapshot 都必須存在，不會替換世代。每代從 runnable survivors 選擇 generation-local、有限且最高的 Game Performance，同分以 candidate ID 穩定排序。所有代表共用凍結 protocol 與同一 seed stream，分別重新編譯及 Integration，並各跑 600 場；不呼叫 LLM，也不修改 search artifacts。protocol、逐代證據、彙總與部分進度寫入獨立 `fixed_evaluation/`。指定的 output directory 必須是新建或空目錄；重跑請使用另一個目錄以保留舊證據。彙總檔名為 `fixed_evaluation_summary.json`、`fixed_evaluation_results.csv`、`fixed_evaluation_results.md`。`mean_match_score` 是 benchmark 的未加權平均，與 canonical search fitness 分開；矩陣不完整或含錯誤時 aggregate score 和 win rate 為 null，命令以非零狀態結束。

實驗主機也提供常駐、唯讀的本地監控入口；它會自動發現 `runs/` 下現在與之後
由 `experiment` 建立的 canonical run：

```bash
python -m eagle monitor --runs-root runs --host 0.0.0.0 \
  --port 8765
```

`/status` 回傳所有已發現 run 的詳細資料，`/status.json` 與
`runs/monitor_status.json` 則只保留總 run 數、設定代數、目前 run／代、PID、
存活狀態與每個 run 的小摘要；`/status/<run_id>` 查詢單一詳細 run。它們只讀取
canonical manifest 與最新 atomic generation snapshot；詳細端點另回傳 match、fitness、
錯誤摘要，以及 CPU／記憶體／磁碟／NVIDIA GPU 資訊，不會解析 console log，也沒有
重啟、停止或修改實驗的 API。正常完成標記為 `complete`；active run 的 PID 消失則標記
為 `unexpected_termination`，和 `interrupted`／`failed` 分開。token 保護是可選的；若不
設定 token，可直接用瀏覽器開啟 URL。monitor 預設每 30 秒原子更新
`runs/monitor_status.json`，也可透過 `http://<experiment-host>:8765/status.json`
讀取。若不使用 token，仍應限制防火牆只允許信任的區網電腦；完整端點與防火牆建議見
[`operations/monitoring_experiment.md`](operations/monitoring_experiment.md)。

`experiment.sh`／`python -m eagle experiment` 統一管理 config discovery、
optional managed-local llama.cpp start/reuse、全部 endpoint 的 chat preflight、EA、
resume、final test 與 owned-process cleanup。它只管理 primary local process；
additional endpoint 永遠是 unmanaged。舊的 `run.sh`、`run_env.sh`、`python -m eagle run`、
`python -m eagle runtime` 已移除。

以資料夾啟動批次時，該設定資料夾會建立 `experiment.yaml` 索引，格式為 `schema_version: eagle-experiment-index-v1`，以 `runs` 將精確 config 檔名對應至絕對 run folder 的有序清單；清單位置是從零開始的 replicate index。索引在每個 run 建立時立即原子更新。舊版「檔名 → 單一路徑」格式仍會讀取為一項清單，並在下次記錄 run 時原子升級，不會在下次執行時被當成 config。既有的 `experiment-v2` 同名設定檔不會被覆寫，該資料夾也不會產生批次索引。

`--resume` 指向設定資料夾時會讀取既有索引，不會清空它。系統先驗證每個槽位的 effective seed 與完整有序 endpoint 清單，再優先續跑已索引但 search 或必要 final test 尚未完成的 run，跳過完整完成槽位，之後建立缺少的 replicate；新 run 仍會原子寫回同一索引。若 generation zero 尚未記錄，該槽位會換成新 run，舊 evidence 仍保留。若 search 已完成、只缺 final test，則不會為該步驟啟動 llama.cpp。全新啟動會建立新的索引。

## 驗證

```bash
python3 -m compileall eagle
python3 -m unittest discover -s tests
git diff --check
```

完整 evolutionary experiment 不是一般 repository migration 的必要驗證。
雙 endpoint 的 focused config、route、concurrency、runtime propagation 與 preflight
測試已通過；`192.168.1.136:1234` 的 models 與 bounded chat completion 也已回 HTTP
200。仍需一次有界的完整實驗 smoke，確認 local/remote request 實際重疊且 artifacts
同時出現兩個 route；本文不宣稱該完整實機驗證已完成。

## 2026-10-02 可維護性架構與文件入口

Python 統一於 `eagle/`。修改單一 EA operator 到 `eagle/operators/` 的 initialization、selection、crossover、adaptive、strategy、prompt 或 code；演化階段順序集中於 `eagle/evolution/generation.py`，offspring 與 parent refresh 各自分開。Java 生成位於 `eagle/generation/`；評估的 records、decoding、opponents、matches、pipeline 位於 `eagle/evaluation/`。既有演算法、設定、assets、run artifacts 與 checkpoint 契約保持不變。

文件 map 新增：[可維護性重構計畫](implementation/maintainability_refactor_plan.md) 與
[本地實驗監控](operations/monitoring_experiment.md)，前者包含掃描結果、修改入口、
實作順序與驗證記錄；Groq GPT-OSS framework／有限 slot mode 的 owner 是
[framework slots](architecture/framework_slots.md)；完整 owner 表見
[repository map](implementation/repository_map.md)。
