# EAGLE deterministic DSL 與 GPU 平行執行版本

來源版本：94ab1869。截點：2026-10-14（Asia/Taipei）。

本文件逐頁保留簡報內容與詳細解說。示例均為機制教學，不代表實驗量測。

## 1. EAGLE deterministic DSL 版本



- 2026-10-14　程式版本 94ab1869
- Ministral3 8B　seed 8 × 3 runs



詳細解說：本簡報以94ab1869為程式截點，2026-10-14 Asia/Taipei。主線為使用者選定的deterministic DSL三次同seed實驗，介紹目前方法、執行變更、啟動失敗證據與待量測項目。沒有把程式測試當成對戰成績。

來源：configs/experiments/1014_deterministic_dsl_3x2_seed8_3runs/ministral3_8b_deterministic_dsl_3x2_seed8_3runs.yaml；eagle/runtime/processes.py

## 2. 策略表示與編譯：逐次變更




| 版本／日期 | 變更前 | 變更後與目的 |
| --- | --- | --- |
| 37d5ec2e<br>10/14 | 策略以 DSL 表示<br>Java 仍依 LLM 解碼 | 新增固定 typed-IR compiler<br>同輸入得到同 Java |
| 9500d3c1<br>10/14 | 搜尋主線為 LLM<br>materialization | deterministic_dsl 整合搜尋<br>只演化策略基因 |
| dbaeb7c2<br>10/14 | 缺少專用驗證設定 | seed 8 × 3 runs<br>3 代、population 2 |
| 214c5733<br>10/14 | 巢狀規則 schema<br>容易被誤讀 | 釐清完整 DSL rule 結構<br>規則內容須完整合法 |

影響主線：移除 Java LLM 解碼；成績與耗時尚未驗證

詳細解說：37d5ec2e是compiler實作、9500d3c1是流程整合；195ec5d3是相應文件，不將它誤標為實作。這些改變的程式契約可由source確認，但目前沒有正式三次run效能量測。方法基準是10/13簡報記錄的1fa6662e，並非共同測試結果。

來源：eagle/generation/dsl_java_compiler.py；eagle/generation/backend.py；docs/architecture/java_generation.md

## 3. 回應格式、批次與 runtime：逐次變更




| 版本 | 原行為 | 本版行為 |
| --- | --- | --- |
| 2585ce0e | 資料夾不能執行多 runs | 每個 replicate 有獨立槽<br>experiment.yaml 支援續跑 |
| c401d99a | GPU／平行度由 config 覆寫 | GPU 強制啟用<br>2 LLM slots、10 match workers |
| 6dee5d4f<br>4f04c901 | 策略回應以整份 JSON 判定 | JSONL 每行一條規則<br>保留合法規則、丟棄壞行 |
| b536fd42<br>94ab1869 | 提示仍有泛稱策略描述<br>verbosity 3 缺 offload log | LLM 提示對齊 DSL<br>verbosity 4、fit off |



詳細解說：此頁每項為獨立變更。JSONL parsing先由6dee建立目標欄位record，4f04加入rule-level salvage。b536提示適用LLM materialization，對主線deterministic compiler不構成處理步驟。94ab修正啟動證據可見性並禁用自動fitting；沒有宣稱硬體或搜尋效能已改善。

來源：eagle/experiment.py；eagle/execution.py；eagle/strategy_dsl.py；prompts/code_reflection.txt；eagle/runtime/processes.py

## 4. 本次設定與有效執行模式




| 項目 | 本次設定 | 實際作用 |
| --- | --- | --- |
| 策略／Java | deterministic_dsl<br>eagle-dsl-java-v1 | 策略 JSON → 固定 Java compiler<br>Generation meta prompt 不啟用 |
| 搜尋預算 | seed 8，runs 3<br>演化 3 代、population 2 | 三次相同 seed、獨立 run<br>gen0 另列，之後 gen1–3 |
| 反思 | static，mutation_rate 1<br>Strategy probability 1 | 只有 Strategy Reflection<br>Code／Prompt Reflection 不啟用 |
| 評估 | self_play，3 maps<br>parent mode reuse_cached | Game Performance 最大化<br>同分以 semantic novelty 分辨 |



詳細解說：由ExperimentConfig.from_mapping可確認self_play強制解析為game_performance_semantic_tiebreak。CLI一般banner中出現lexicase不代表此config實際採fixed-roster lexicase。單一WorkerRush設定seed在deterministic模式複製為population_size=2；gen0有兩個不同ID但相同policy的候選。

來源：configs/experiments/1014_deterministic_dsl_3x2_seed8_3runs/ministral3_8b_deterministic_dsl_3x2_seed8_3runs.yaml；eagle/config.py；eagle/operators/initialization.py

## 5. 完整搜尋流程




流程節點：config=Config、seed、GPU 檢查；init=Gen0：2 個 seed clones；bootstrap=DSL 編譯、初始評估；iteration=父代、crossover、反思 / 每代 2 offspring；eval=DSL 編譯與對戰 / μ＋λ 倖存者選擇；stop=達到停止條件？；final=完成：champion final-test；outputs=summary、checkpoint、timing
連線：config → init；init → bootstrap；bootstrap → iteration；iteration → eval；eval → stop；stop → iteration；stop → final；final → outputs

中斷／失敗：保留最後完整 checkpoint，以 --resume 接續

詳細解說：先完成GPU runtime啟動與config協定核對，gen0建立兩個seed clones、編譯與bootstrap self-play評估，保存snapshot。gen1到gen3按序建立offspring，反思可同時發出但結果固定排序；編譯與評估後以mu+lambda選survivors。正常完成後共同final-test不回饋搜尋。stagnation門檻25高於三代預算，正常會先到代數上限。外部exception/interrupt留下最後完整checkpoint。

來源：eagle/evolution/search.py；eagle/evolution/generation.py；eagle/final_test.py

## 6. DSL：策略與實作之間的固定契約



- 策略是一個 version + rules 的 JSON object；每條 rule 包含 actor、when、action。空 rules 明確表示 idle。
- 條件只讀當前可觀測狀態；action、target、selector 使用封閉詞彙。禁止自訂 prose／Java 欄位。
- Java 是離線編譯的 phenotype；固定 scaffold、compiler version 與 policy hash 一起保存。



詳細解說：策略格式eagle-strategy-dsl-v1，上限16000字元、32rules、conditiondepth6、booleanfanout8。規則包含actor單位類型、when條件、action合法動作。choose是合法動作子集上的確定性hash選擇，沒有persistent RNG。策略本身仍由LLM反思改變，確定性的是policy到Java的物化映射，不等於不使用LLM。

來源：prompts/strategy_dsl_reference.txt；eagle/strategy_dsl.py；eagle/generation/dsl_java_compiler.py

## 7. DSL 的規則順序與 fallback




流程節點：actor=idle friendly actors / 按 unit ID 升序；rules=規則按 rules 陣列順序；when=when 成立？；issue=action 可合法發出？；commit=發出一個 action / 更新本輪 reservations；next=不成立／guard 失敗 / 繼續下一條 rule
連線：actor → rules；rules → when；when → issue；issue → commit；when → next；issue → next；next → rules

每個 actor 每 cycle 最多一個 action；沒有匹配則 idle

詳細解說：每個目前idle的friendly actor依升序ID處理，對其type對應rules依arrayorder判斷。when false、目標不存在、path不可達、stockpile不足、cell占用或guard失敗均繼續下一條。第一個真正可issue的action終止該actor，explicitidle也終止。hash target先合法filter，selector metric ties按ID或cell y,x。一次PlayerAction累積resource/cell reservation供後續actor使用。

來源：prompts/strategy_dsl_reference.txt；eagle/generation/dsl_java_compiler.py

本頁為教學示例，非實驗量測。

## 8. Gen0 與每代需要保存的狀態




| 階段 | 候選／狀態 | 證據 |
| --- | --- | --- |
| Gen0 | 單一 WorkerRush policy<br>複製為 2 個候選 | 不同 candidate IDs<br>相同 DSL 與 Java hash |
| 對手快照 | bootstrap 後建立 run-local library<br>Java／語意等價去重 | 固定 source IDs、slot IDs<br>與 context_id |
| Gen1–3 | 每代建立 2 offspring<br>保存已完成 survivors | parents、strategy_parent_id<br>反思與 lineage |
| Checkpoint | 只承認完整提交的 generation | config、compiler/scaffold hashes<br>manifest、snapshot、timing |



詳細解說：初始化clone不是多樣化，兩個policy相同。初始bootstrap評估由compiled候選提供對手；之後library去重可能將兩個identicalJava候選縮為一個source。snapshotcontext改變時，gen1必須先更新父代fitness，而不是無條件重用gen0分數。相同context後可reuse_cached。

來源：eagle/operators/initialization.py；eagle/evolution/search.py；eagle/evolution/generation.py；eagle/self_play.py

## 9. Self-play opponent pool 的建立與刷新



- 只有完整、可執行且評估成功的 phenotype 可進入 library；依 candidate ID、Java hash 與完整語意簽章去重。
- Library 容量 50，按 FIFO 保留；刷新時循環取最多 10 個來源，再填滿 10 個 evaluation slots。
- 本設定每 5 代刷新；只跑 gen1–3，因此沿用 gen0 快照。若 context 不同，先重評父代再比較。



詳細解說：select_self_play_library_candidates在libraryorder上以epoch=generation//refresh_interval與source_count=min(N,10)決定start=(epoch*source_count)%N；expand_self_play_slots將非空來源按順序循環到10slots。初始兩個相同Java的seedclones在libraryhash去重後通常只剩一個來源，十格並不代表十種策略。gen0bootstrapcontext與librarysnapshotcontext可能不同，gen1觸發context_migration_required；gen2/3若context一致則可reuse。library的capacity與refresh_interval不等於全archive最優對手選擇。

來源：eagle/self_play.py；eagle/evaluation/opponents.py；eagle/evolution/generation.py

## 10. 評估對手、繁殖父代與倖存者




| 用途 | 從哪裡選 | 選擇規則 |
| --- | --- | --- |
| Evaluation opponents | 固定 self-play snapshot<br>不是目前 breeding pool | library 循環來源 → 10 slots<br>同輪所有候選共用 context |
| Breeding parents | 目前 evolving population | Game Performance 最高 tier<br>第二父代 tie 可看語意距離 |
| Survivors | 目前 parents + offspring | μ＋λ 選 2 人<br>tier 邊界用 seeded novelty |
| Final-test opponents | 固定 10 種共同測試對手 | 與搜尋 self-play pool 分開<br>champion 測試後不回饋搜尋 |



詳細解說：GamePerformance的tier不是鏈式鄰近合併，最高分往下1.0以內屬tier。父代A在top tier選擇，B可用A語意簽章當reference。survivor先保留完整較好score tiers，容量截斷的tier才用farthest-first語意新穎度，不讓semantic distance把較差tier提升。missing/incompatible簽章走seeded fallback。finaltest固定roster，不混同搜尋的selfplay_000–009slots。

來源：eagle/operators/selection.py；eagle/evolution/offspring.py；eagle/self_play.py；eagle/final_test.py

## 11. 每代變異：只有 Strategy Reflection



- 先以 root seed 衍生各 slot 的父代、crossover 與 operator stream，再一次建立 2 個 offspring 計畫。
- Crossover rate 0.75：從兩個父代選一份完整 policy；不拼接 rule 子樹，也不繼承 Java／generation prompt。
- Mutation rate 1.0、Strategy probability 1：反思可改 policy；Code source gate、Prompt Mutation 都停用。



詳細解說：deterministic branch在plan_offspring設定gate_sources=()，不呼叫independentCodeReflection。crossover(strategy_only)只在兩親中選整份strategy_prompt，source-parent provenance跟policy選擇同步。mutationsource仍按strategy_parent_id鎖定，不能隨意改用當代最好parent。所有計畫的來源選擇先serial決定，然後可並行reflection；回傳按照slot順序整合。

來源：eagle/evolution/offspring.py；eagle/operators/crossover.py；eagle/execution.py

## 12. Strategy Reflection 的證據來源




流程節點：parent=記錄的 strategy_parent_id；worst=已完成 matches / 恰好選一場 worst；commentator=Match Commentator / 單場 trace → diagnosis；summary=parent 全場摘要 / global summary；coach=Coach / 單場診斷＋全場摘要；dsl=JSONL 完整 rules / 驗證 → 新 policy
連線：parent → worst；worst → commentator；parent → summary；commentator → coach；summary → coach；coach → dsl

單場診斷提供具體失敗證據；全場摘要保留整體表現

詳細解說：選擇只從記錄的strategy_parent_id對應parent已完成matches中挑最低有限performance的一場；若無有限score，依loss=-100、draw=0、win=100 fallback。stablematch_id打破tie；failedmatches排除。Commentator看到該場canonicaltrace；Coach看到一份diagnosis與parent全部matches的global summary。JSONL結果經驗證後形成策略基因。缺trace不換成另一場。

來源：eagle/operators/context.py；eagle/operators/strategy.py；docs/architecture/mutation.md

## 13. JSONL：合法規則子集可形成策略



- 每個實體行是一筆 strategy_rule record；Coach 使用 new_strategy_prompt，contract rewrite 使用 revised_strategy_prompt。
- 每條 rule 獨立驗證 actor／when／action；丟棄 malformed、錯欄位或語意不合法的整條規則，保留合法行順序。
- 至少一條合法 rule 才成功；零條合法規則最多 3 次嘗試。耗盡可保留原 policy；transport exception 仍可能中止 run。

固定 compiler 接收的是完整、正規化 policy，不是未驗證的原始 JSONL

詳細解說：這裡不能把合法空policy與零條合法JSONL輸出混為一談。空rules完整policy是idle，然而Coach策略變更的JSONL協定需要至少一條合法strategy_rule。Salvage不修補非法rule子樹，也不從父策略echo推斷新策略。wholeJSON/fullfence保留既有讀取behavior，但本版提示輸出目標是rule-per-lineJSONL。上限mutation_max_attempts=3。具體backend/serverexceptions與語意解析失敗走不同失敗邊界，不能保證所有例外都正常降級候選。

來源：eagle/strategy_dsl.py；eagle/operators/strategy.py；prompts/coach_refine.txt

## 14. 確定性 Java 物化與失敗邊界




流程節點：policy=完整 canonical DSL policy；ir=validate／normalize / 建立 typed IR；emit=固定 compiler＋scaffold / 完整 Java phenotype；validate=source validation / 單次 javac、Integration；game=語意 probe、matches / fitness、diagnostics；evidence=phenotype、hashes / result、lineage、timing
連線：policy → ir；ir → emit；emit → validate；validate → game；game → evidence

編譯失敗：保留原階段證據與失敗候選；沒有 Java LLM fallback

詳細解說：DSLcompiler先validate/normalize，生成typedIR，再用eagle-dsl-java-v1與固定scaffold發射完整source。下游一般validation、單次javac與integration維持，probe/matches有自身diagnostics。deterministic模式沒有JavaGeneration、CodeReflection、PromptReflection或compile-repairLLM。compiler/validation/javacfailure保持實際failurestage與source/hash，不假裝進入遊戲。

來源：eagle/generation/dsl_java_compiler.py；eagle/evaluation/decoding.py；eagle/evaluation/pipeline.py

## 15. 評估規模與 fitness




| 項目 | 本設定 | 用途 |
| --- | --- | --- |
| Search matrix | 10 slots × 3 maps<br>× 3 rounds × 2 sides = 180 | 每個候選完成一次評估<br>slots 可重複同一來源 |
| 地圖與 tick limit | 8×8：1500；16×16：3000<br>24×24：4000 | 雙方換邊、固定 match seeds<br>超時／失敗保留診斷 |
| Game Performance | 勝／和／敗基分 + bounded shaping<br>跨 completed matches 聚合 | 唯一 optimizer objective<br>Code Quality 只作診斷 |
| Champion final-test | 10 opponents × 3 maps<br>× 10 games × 2 sides = 600 | 正常完成後的共同測試<br>與 search fitness 分開 |



詳細解說：game_performance使用每場result100/0/-100加[-10,10]shaping，以詳細telemetry計算資源及軍力等訊號，不等同winrate。semanticprobe為1.0tier tie新穎度，不能突破fitness tiers。finaltest若非mock且未skip在正常runcomplete後進行；中斷/失敗時不跑。180與600是定義的matrix大小，不是已完成場數。

來源：eagle/evaluation/game_performance.py；eagle/evaluation/game_metrics.py；eagle/opponent_cases.py；eagle/final_test.py

## 16. 平行執行與固定整合順序



- Runtime 固定 2 request slots、每 slot context 32768；兩個獨立 offspring 的反思工作可同時呼叫。
- DSL／Java preparation 可平行；完成全部 preparation 後才建立對手 pool。每個候選的 matches 用 10 workers。
- parallel_map 按輸入順序回傳；父代／operator 計畫與 survivor 整合保留固定順序，跨 run 仍依序執行。



詳細解說：LLM_WORKERS=2、MODEL_THREADS=8、MATCH_WORKERS=10為程式常數，config不可覆寫。serverctx-size=contextper-slot*parallel=65536。單一runtime一次只載入一個model，generation與reflectionmodel有switchbarrier；本deterministic主線不啟用Java生成LLM。evaluate_population preparation採parallel_map，但candidateevaluation仍serial、單candidate180matches內部parallel。不要宣稱3個run並行或整個generation所有階段重疊。工作有穩定taskseed；浮點GPUbackend、wall-clocktimeouts仍有外部nondeterminism。

來源：eagle/execution.py；eagle/runtime/processes.py；eagle/evaluation/pipeline.py；eagle/evaluation/matches.py

## 17. 三次 replicate 與資料夾續跑




| 階段 | experiment.yaml／run | 恢復行為 |
| --- | --- | --- |
| 展開 config | random_seeds [8]、runs 3<br>有效序列 [8,8,8] | run1、run2、run3<br>各自獨立目錄與 checkpoint |
| 保存索引 | 每個 YAML filename<br>對應有序 run paths 清單 | 按 replicate slot 更新<br>不覆蓋其他 slot |
| --resume folder | 核對每槽 config／effective seed<br>先處理未完成 indexed runs | 已完成跳過<br>未啟動 replicate 接續建立 |
| 中斷時 | 以最後完整 generation 恢復<br>gen0 前失敗無 checkpoint | 無可用 checkpoint 可建替代run<br>原始失敗證據保留 |



詳細解說：索引schemaeagle-experiment-index-v1；source config的runs跟random_seeds展開成orderedslots。路徑是實際run_dirs，由on_run_created更新。resume不可將不相容policyformat/compiler/scaffold默默轉換。三次同seed是重複性檢查，不能把它當三個獨立randomseed樣本；GPU/runtime差異仍需用hash與timing檢查。

來源：eagle/experiment.py；eagle/evolution/resume.py；docs/operations/running_eagle.md

## 18. GPU 啟動：可用裝置與實際 offload




| 檢查 | 固定行為 | 不通過時 |
| --- | --- | --- |
| 裝置 preflight | llama-server --list-devices<br>確認 CUDA／NVIDIA backend | 停止啟動，不退回 CPU |
| 要求全層 | --n-gpu-layers 999<br>--fit off | 禁止自動記憶體 fitting<br>載入失敗即保留錯誤 |
| 證據可見性 | --log-verbosity 4 | core INFO 才輸出 offload 行<br>server ready 不代表驗證成功 |
| 實際 full offload | 只讀這次 child 的新 log<br>要求 offloaded N/N，N > 0 | 缺失／部分／stale 證據<br>停止 owned process |



詳細解說：LLAMA_LOG_INFO在common/log.cpp被GGML_INFO映射到LOG_LEVEL_TRACE4；userlogverbosity3缺少modelcorelog，但CUDAdevice以及HTTPserverready仍可見。94ab保留原strictregex，不以CUDAlisting或slots推斷成功。GPU count固定999要求多於模型layercount，實際log才驗證N/N。其含義是所有model layersoffload，並非宣稱完全沒有CPU上任何runtime工作。來源外部：https://github.com/ggml-org/llama.cpp/blob/master/common/log.cpp ; common/arg.cpp ; src/llama-model.cpp。

來源：eagle/runtime/processes.py；eagle/runtime/config.py；tests/test_runtime_workflow.py

## 19. 啟動量測：模型載入至 server ready

RTX 5080／Ministral3 8B；單次貼文紀錄，n = 1


Chart-ready data（秒）：{"categories":["載入開始 → warmup 開始","warmup 開始 → server ready"],"values":[6.902104,0.165716],"seriesName":"單次啟動分段 wall time（秒）"}

兩段合計 7.068 秒；GPU 驗證仍失敗，未進入 generation 0

詳細解說：用戶trace採相對timestamp：model load start0.149851s，warmupstart7.051955s，ready7.217671s。分段相减6.902104s與0.165716s，加總7.067820s。第一段包括模型載入與其他初始化至warmup，第二段包括warmup與slot/server初始化，不能稱純warmupkernel耗時。這是單次失敗啟動局部walltime，不含devicepreflight或整個experiment。沒有前後對照，不估generationduration或speedup。

來源：Meeting/20261014_dsl_gpu_parallel/runtime_log_excerpt.txt

## 20. Code Reflection 與 Generation 提示的 DSL 更新



- Code diagnosis 以 rule index、actor／when／action 與 intrinsic semantics 指出 Java 不一致；合法空 rules 不再視為模糊策略。
- Generation meta rules 對齊規則順序、合法 action、target ties、hashed choose、reservations 與 fallback。
- 初始 meta prompt、反思後的 canonical 標頭、Java revision 與 compile repair 一起更新；Java／JSON 輸出契約保留。

本設定不使用這些 LLM 提示；它們供 llm materialization 模式使用

詳細解說：b536修改16檔，包含11promptresources、canonicalreusableheader、兩docs與兩tests。具體attack是range-only、engage可移動、harvest不自動return、moveentityrange1自指或adjacent不可issuedfallthrough。generation輸出完整Java，不改為DSLresponse。這些提示屬llm materialization，主線deterministic_dsl完全不呼叫Code/PromptReflection、JavaGeneration/compileRepair。因此不能將本次實驗效果歸因於b536。

來源：prompts/code_reflection.txt；prompts/initial_generation.txt；eagle/operators/reusable_prompt.py；prompts/java_compile_repair.txt

## 21. 目前的實驗結果與缺口




| 證據 | 已知狀態 | 可支持的結論 |
| --- | --- | --- |
| 目標 seed 8 × 3 runs | 遠端啟動在 gen0 前失敗<br>正式 manifests 未取得 | 不能報勝率／fitness trajectory<br>或完成三次實驗 |
| 本機 deterministic smoke | 其他設定、population 1<br>semantic probe 曾回報錯誤 | 不是目標 config 的 benchmark<br>不拿零分作比較基準 |
| 10/13 workflow baseline | 1fa6662e，LLM／inherited 模式<br>seed 7，方法說明簡報 | 可比較方法與執行邊界<br>沒有共同成績量測 |
| 共同 final-test | 目標 champion results 未提供 | 尚無可用版本間 outcome chart<br>不可用測試 PASS 取代勝率 |



詳細解說：正式run需run-localconfig、manifest、completedsnapshots與finaltestsummary驗證。Agent查找到runs/20261014_142526_546498等deterministic_dsl_smoke，不是Ministral3seed8三run且semanticdataset曾錯誤。已完成matches紀錄不能因名字相似就用於正式比較。缺乏fitness與finaltest數值，這頁明確保留結果缺口，不繪不存在的零值nativechart。

來源：Meeting/20261014_dsl_gpu_parallel/version_report.md；Meeting/20261013_current_workflow/content.json；Meeting/20261014_dsl_gpu_parallel/runtime_log_excerpt.txt

## 22. 已完成的程式驗證




| 範圍／版本 | 驗證紀錄 | 不代表 |
| --- | --- | --- |
| GPU／平行化<br>c401d99a | 先前全套 603 tests<br>1 skip：歷史 AllInBot fixture | 不是 remote GPU 實跑<br>不是勝率或加速量測 |
| DSL 提示<br>b536fd42 | 85 項 focused regressions 通過<br>含 meta prompt round-trip | 未量測模型回應品質 |
| GPU startup fix<br>94ab1869 | 49 項 runtime／launcher tests 通過<br>完整通過，partial／zero 拒絕 | RTX 5080 尚未重跑確認 |
| 資料一致性 | config parse 與 seed schedule 核對<br>diff checks 通過 | 不等於跨 backend 完全確定性 |



詳細解說：測試count源自本次對話各實作阶段留下的驗證紀錄。603包含一個skip；85與49focused是不同scope而且可能重疊，不能加總成737個不重複tests。runtime tests用controlledchildlog驗證verbosity4確保freshfulloffload通過，32/33與0/33停止ownedprocess，stalepriorlog無法通過。這頁只列工程回歸證據，對戰結果另頁未提供。

來源：tests/test_runtime_workflow.py；tests/test_experiment_launcher.py；tests/test_reusable_generation_prompt.py；tests/test_code_reflection.py

## 23. 與 10/13 方法基準的比較




| 比較項 | 10/13：1fa6662e | 10/14：94ab1869 |
| --- | --- | --- |
| 有效 genotype | DSL policy、generation prompt<br>加 inherited Java | 只有完整 DSL policy |
| Java 物化 | LLM decoder／revision<br>compile-guided repair | 固定 compiler + scaffold<br>單次 javac，无 LLM repair |
| 搜尋／執行 | seed 7、self_play<br>match workers 9 | seed 8、self_play<br>GPU mandatory、match workers 10 |
| 可支持的差異 | 方法基準，沒有實測對照 | 移除 Java LLM 工作可由契約確認<br>成功率／節省時間仍需量測 |



詳細解說：基準是前次workflowdeckrecord1fa，不是67fbdartifactcommit本身。比較同時改了seed、materialization與runtime，沒有matchedtest只能說methoddifferences，不能推導higherfitness、tokenreduction百分比或GPUparallel speedup。若後續要量化，需同一hardware/model/maps/budget與finaltestprotocol，保留run IDs與完整walltime。

來源：Meeting/20261013_current_workflow/content.json；docs/architecture/java_generation.md；eagle/execution.py

## 24. 執行與資料夾 resume 指令



- 開始（先同步 94ab1869 及前置變更）：
./experiment.sh \
  configs/experiments/1014_deterministic_dsl_3x2_seed8_3runs
- 中斷後接續：
./experiment.sh --resume \
  configs/experiments/1014_deterministic_dsl_3x2_seed8_3runs
- 檢查 experiment.yaml 的 3 個 run paths；每次保存 gen0、gen1–3 與 final-test。



詳細解說：從EAGLErepo root執行，experiment.sh使用condarun-neagle。啟動fix沒有新增configfields，不需修改現有YAML。第一個runtime還未on_run_created時沒有index/checkpoint，這次應先重新執行start命令；已有index才用folderresume。成功run正常會執行finaltest，skip-final-test若使用則必須一致標記比較arm。bash反斜線在換行前不要帶其他字元。

來源：experiment.sh；eagle/cli/experiment.py；eagle/experiment.py

## 25. 完成三次 run 後要比較的證據



- 重複性：逐 run 比較 policy／Java hash、selected-parent lineage、每代 survivors 與 completed-match seeds。
- 效能：統一 final-test roster／maps／seeds，報 W／D／L／E、Game Performance 與各 run 差異。
- 時間：gen0 單列，gen1–3 用已提交 timing 記錄；區分 run wall time、stage sums 與平行工作量。



詳細解說：三次seed8replicates回答相同rootseed的runtime重複性，不是不同隨機初始化樣本。generationtiming以committedrecords為准，partialLLM log不能推估完整generation。必要時matchedbaseline採同硬體/模型/seed/預算但固定一個變因；本scope不啟動新experiments。remoteGPUpostfixlaunch、self-playsemanticprobe/finaltest都待正式run證據。

來源：eagle/evolution/search.py；eagle/timing.py；eagle/final_test.py；Meeting/20261014_dsl_gpu_parallel/version_report.md
