# EAGLE 最終版本介紹

來源版本：94ab1869。截點：2026-10-14（Asia/Taipei）。

本文件逐頁說明最終版本的設定與運作機制。

## 1. EAGLE 最終版本介紹



- 標準規模：population 10 × 演化 20 代
- Deterministic DSL　Ministral3 8B



詳細解說：本簡報介紹程式來源94ab1869的最終運作方式，標準實驗為population10、20個演化世代，gen0初始化另列。其餘設定沿用deterministic_dsl、seed8重複三次、Strategy-only self-play。說明設定、策略表示、初始化、反思、確定性編譯、評估、選擇、平行工作、GPU啟動與續跑。

來源：configs/experiments/1015_deterministic_dsl_20x10_seed8_3runs/ministral3_8b_deterministic_dsl_20x10_seed8_3runs.yaml；eagle/runtime/processes.py

## 2. 執行模式與實驗設定




| 項目 | 本次設定 | 實際作用 |
| --- | --- | --- |
| 策略／Java | deterministic_dsl<br>eagle-dsl-java-v1 | 策略 JSON → 固定 Java compiler<br>Generation meta prompt 不啟用 |
| 搜尋預算 | population 10、演化 20 代<br>seed 8，runs 3 | gen0 另列，之後 gen1–20<br>三次相同 seed、獨立 run |
| 反思 | static，mutation_rate 1<br>Strategy probability 1 | 只有 Strategy Reflection<br>Code／Prompt Reflection 不啟用 |
| 評估 | self_play，3 maps<br>parent mode reuse_cached | Game Performance 最大化<br>同分以 semantic novelty 分辨 |



詳細解說：ExperimentConfig解析此self_play設定為game_performance_semantic_tiebreak。Gen0把單一WorkerRush policy複製為population_size=10，各候選有不同identity。有效genotype只有strategy_prompt；標準設定20個演化世代另有gen0初始化，三個獨立run的有效seed均為8。

來源：configs/experiments/1015_deterministic_dsl_20x10_seed8_3runs/ministral3_8b_deterministic_dsl_20x10_seed8_3runs.yaml；eagle/config.py；eagle/operators/initialization.py

## 3. 完整搜尋流程




流程節點：config=Config、seed、GPU 檢查；init=Gen0：10 個 seed clones；bootstrap=DSL 編譯、初始評估；iteration=父代、crossover、反思 / 每代 10 offspring；eval=DSL 編譯與對戰 / μ＋λ 倖存者選擇；stop=達到停止條件？；final=完成：champion final-test；outputs=summary、checkpoint、timing
連線：config → init；init → bootstrap；bootstrap → iteration；iteration → eval；eval → stop；stop → iteration；stop → final；final → outputs

中斷／失敗：保留最後完整 checkpoint，以 --resume 接續

詳細解說：先完成GPU runtime啟動與config協定核對，gen0建立10個seed clones、編譯與bootstrap self-play評估，保存snapshot。gen1到gen20按序建立每代10個offspring，反思以2個LLM slots並行、結果固定排序；編譯與評估後以mu+lambda選10個survivors。第5、10、15、20代刷新對手快照並重評父代。stagnation門檻25高於20代預算，正常會先到代數上限。正常完成後共同final-test不回饋搜尋；外部exception/interrupt留下最後完整checkpoint。

來源：eagle/evolution/search.py；eagle/evolution/generation.py；eagle/final_test.py

## 4. DSL：策略與實作之間的固定契約



- 策略是一個 version + rules 的 JSON object；每條 rule 包含 actor、when、action。空 rules 明確表示 idle。
- 條件只讀當前可觀測狀態；action、target、selector 使用封閉詞彙。禁止自訂 prose／Java 欄位。
- Java 是離線編譯的 phenotype；固定 scaffold、compiler version 與 policy hash 一起保存。



詳細解說：策略格式eagle-strategy-dsl-v1，上限16000字元、32rules、conditiondepth6、booleanfanout8。規則包含actor單位類型、when條件、action合法動作。choose是合法動作子集上的確定性hash選擇，沒有persistent RNG。策略本身仍由LLM反思改變，確定性的是policy到Java的物化映射，不等於不使用LLM。

來源：prompts/strategy_dsl_reference.txt；eagle/strategy_dsl.py；eagle/generation/dsl_java_compiler.py

## 5. DSL 的規則順序與 fallback




流程節點：actor=idle friendly actors / 按 unit ID 升序；rules=規則按 rules 陣列順序；when=when 成立？；issue=action 可合法發出？；commit=發出一個 action / 更新本輪 reservations；next=不成立／guard 失敗 / 繼續下一條 rule
連線：actor → rules；rules → when；when → issue；issue → commit；when → next；issue → next；next → rules

每個 actor 每 cycle 最多一個 action；沒有匹配則 idle

詳細解說：每個目前idle的friendly actor依升序ID處理，對其type對應rules依arrayorder判斷。when false、目標不存在、path不可達、stockpile不足、cell占用或guard失敗均繼續下一條。第一個真正可issue的action終止該actor，explicitidle也終止。hash target先合法filter，selector metric ties按ID或cell y,x。一次PlayerAction累積resource/cell reservation供後續actor使用。

來源：prompts/strategy_dsl_reference.txt；eagle/generation/dsl_java_compiler.py

## 6. Gen0 與每代需要保存的狀態




| 階段 | 候選／狀態 | 證據 |
| --- | --- | --- |
| Gen0 | 單一 WorkerRush policy<br>複製為 10 個候選 | 不同 candidate IDs<br>相同 DSL 與 Java hash |
| 對手快照 | bootstrap 後建立 run-local library<br>Java／語意等價去重 | 固定 source IDs、slot IDs<br>與 context_id |
| Gen1–20 | 每代建立 10 offspring<br>保存已完成 survivors | parents、strategy_parent_id<br>反思與 lineage |
| Checkpoint | 只承認完整提交的 generation | config、compiler/scaffold hashes<br>manifest、snapshot、timing |



詳細解說：初始化clone不是多樣化，10個policy相同。初始bootstrap評估由compiled候選提供對手；之後library去重可能將10個identicalJava候選縮為一個source。snapshotcontext改變時，gen1必須先更新父代fitness，而不是無條件重用gen0分數。相同context後可reuse_cached。

來源：eagle/operators/initialization.py；eagle/evolution/search.py；eagle/evolution/generation.py；eagle/self_play.py

## 7. Self-play opponent pool 的建立與刷新



- 只有完整、可執行且評估成功的 phenotype 可進入 library；依 candidate ID、Java hash 與完整語意簽章去重。
- Library 容量 50，按 FIFO 保留；刷新時循環取最多 10 個來源，再填滿 10 個 evaluation slots。
- 每 5 代刷新對手快照：gen5、10、15、20。刷新或 context 改變時，先重評父代，再與 offspring 在相同快照下比較。



詳細解說：select_self_play_library_candidates依libraryorder，以epoch=generation//refresh_interval與source_count=min(N,10)決定start=(epoch*source_count)%N，再循環填滿10slots。Gen0的10個相同Java候選在libraryhash去重後通常只剩一個source；gen1可因contextmigration重評父代。第5、10、15、20代加入當代可執行parents、刷新對手快照並重評父代。兩個刷新點之間，context一致時可reuse_cached。Library容量50、FIFO保留；每輪候選共享相同context。

來源：eagle/self_play.py；eagle/evaluation/opponents.py；eagle/evolution/generation.py

## 8. 評估對手、繁殖父代與倖存者




| 用途 | 從哪裡選 | 選擇規則 |
| --- | --- | --- |
| Evaluation opponents | 固定 self-play snapshot<br>不是目前 breeding pool | library 循環來源 → 10 slots<br>同輪所有候選共用 context |
| Breeding parents | 目前 evolving population | Game Performance 最高 tier<br>第二父代 tie 可看語意距離 |
| Survivors | 目前 parents + offspring | μ＋λ 選 10 人<br>tier 邊界用 seeded novelty |
| Final-test opponents | 固定 10 種共同測試對手 | 與搜尋 self-play pool 分開<br>champion 測試後不回饋搜尋 |



詳細解說：GamePerformance的tier不是鏈式鄰近合併，最高分往下1.0以內屬tier。父代A在top tier選擇，B可用A語意簽章當reference。survivor先保留完整較好score tiers，容量截斷的tier才用farthest-first語意新穎度，不讓semantic distance把較差tier提升。missing/incompatible簽章走seeded fallback。finaltest固定roster，不混同搜尋的selfplay_000–009slots。

來源：eagle/operators/selection.py；eagle/evolution/offspring.py；eagle/self_play.py；eagle/final_test.py

## 9. 每代變異與 Strategy Reflection



- 先以 root seed 衍生各 slot 的父代、crossover 與 operator stream，再一次建立 10 個 offspring 計畫。
- Crossover rate 0.75：從兩個父代選一份完整 policy；不拼接 rule 子樹，也不繼承 Java／generation prompt。
- Mutation rate 1.0、Strategy probability 1：反思可改 policy；Code source gate、Prompt Mutation 都停用。



詳細解說：plan_offspring先依rootseed衍生父代、crossover與operator的taskstreams。deterministic模式以整份策略作crossover的選擇單位，strategy_parent_id記錄策略來源。每代有10個offspring，mutation_rate=1且Strategy probability=1。先serial決定計畫，再並行reflection，最後按slot順序整合。

來源：eagle/evolution/offspring.py；eagle/operators/crossover.py；eagle/execution.py

## 10. Strategy Reflection 的證據來源




流程節點：parent=記錄的 strategy_parent_id；worst=已完成 matches / 恰好選一場 worst；commentator=Match Commentator / 單場 trace → diagnosis；summary=parent 全場摘要 / global summary；coach=Coach / 單場診斷＋全場摘要；dsl=JSONL 完整 rules / 驗證 → 新 policy
連線：parent → worst；worst → commentator；parent → summary；commentator → coach；summary → coach；coach → dsl

單場診斷提供具體失敗證據；全場摘要保留整體表現

詳細解說：選擇只從記錄的strategy_parent_id對應parent已完成matches中挑最低有限performance的一場；若無有限score，依loss=-100、draw=0、win=100 fallback。stablematch_id打破tie；failedmatches排除。Commentator看到該場canonicaltrace；Coach看到一份diagnosis與parent全部matches的global summary。JSONL結果經驗證後形成策略基因。缺trace不換成另一場。

來源：eagle/operators/context.py；eagle/operators/strategy.py；docs/architecture/mutation.md

## 11. JSONL：合法規則子集可形成策略



- 每個實體行是一筆 strategy_rule record；Coach 使用 new_strategy_prompt，contract rewrite 使用 revised_strategy_prompt。
- 每條 rule 獨立驗證 actor／when／action；丟棄 malformed、錯欄位或語意不合法的整條規則，保留合法行順序。
- 至少一條合法 rule 才成功；零條合法規則最多 3 次嘗試。耗盡可保留原 policy；transport exception 仍可能中止 run。

固定 compiler 接收的是完整、正規化 policy，不是未驗證的原始 JSONL

詳細解說：Coach輸出rule-per-lineJSONL，每個record使用new_strategy_prompt；策略contractrewrite使用revised_strategy_prompt。Parser獨立驗證每條rule，不修補非法子樹，按原始行序保留合法規則。Coach回應需要至少一條合法strategy_rule；這與完整DSL空rules的idle語意不同。最多三次嘗試，正常解析失敗耗盡可保留parentpolicy；backend/server例外仍可能中止run。

來源：eagle/strategy_dsl.py；eagle/operators/strategy.py；prompts/coach_refine.txt

## 12. 確定性 Java 物化與失敗邊界




流程節點：policy=完整 canonical DSL policy；ir=validate／normalize / 建立 typed IR；emit=固定 compiler＋scaffold / 完整 Java phenotype；validate=source validation / 單次 javac、Integration；game=語意 probe、matches / fitness、diagnostics；evidence=phenotype、hashes / result、lineage、timing
連線：policy → ir；ir → emit；emit → validate；validate → game；game → evidence

編譯失敗：保留原階段證據與失敗候選；沒有 Java LLM fallback

詳細解說：DSLcompiler先validate/normalize，生成typedIR，再用eagle-dsl-java-v1與固定scaffold發射完整source。下游一般validation、單次javac與integration維持，probe/matches有自身diagnostics。deterministic模式沒有JavaGeneration、CodeReflection、PromptReflection或compile-repairLLM。compiler/validation/javacfailure保持實際failurestage與source/hash，不假裝進入遊戲。

來源：eagle/generation/dsl_java_compiler.py；eagle/evaluation/decoding.py；eagle/evaluation/pipeline.py

## 13. 評估規模與 fitness




| 項目 | 本設定 | 用途 |
| --- | --- | --- |
| Search matrix | 10 slots × 3 maps<br>× 3 rounds × 2 sides = 180 | 每個候選完成一次評估<br>slots 可重複同一來源 |
| 地圖與 tick limit | 8×8：1500；16×16：3000<br>24×24：4000 | 雙方換邊、固定 match seeds<br>超時／失敗保留診斷 |
| Game Performance | 勝／和／敗基分 + bounded shaping<br>跨 completed matches 聚合 | 唯一 optimizer objective<br>Code Quality 只作診斷 |
| Champion final-test | 10 opponents × 3 maps<br>× 10 games × 2 sides = 600 | 正常完成後的共同測試<br>與 search fitness 分開 |



詳細解說：game_performance使用每場result100/0/-100加[-10,10]shaping，以詳細telemetry計算資源及軍力等訊號，不等同winrate。semanticprobe為1.0tier tie新穎度，不能突破fitness tiers。finaltest若非mock且未skip在正常runcomplete後進行；中斷/失敗時不跑。180與600是定義的matrix大小，不是已完成場數。

來源：eagle/evaluation/game_performance.py；eagle/evaluation/game_metrics.py；eagle/opponent_cases.py；eagle/final_test.py

## 14. 平行執行與固定整合順序



- Runtime 固定 2 request slots、每 slot context 32768；每代 10 個 offspring 的反思工作以最多 2 個同時請求處理。
- DSL／Java preparation 可平行；完成全部 preparation 後才建立對手 pool。每個候選的 matches 用 10 workers。
- parallel_map 按輸入順序回傳；父代／operator 計畫與 survivor 整合保留固定順序，跨 run 仍依序執行。



詳細解說：LLM_WORKERS=2、MODEL_THREADS=8、MATCH_WORKERS=10為固定執行政策。每slotcontext32768使serverctx-size=65536。Population10代表每代10個offspring，不代表10個LLMslots；獨立反思最多兩請求並行。Candidate preparation可並行，全部完成後才建立對手pool；候選評估按序，每候選180matches用10workers。parallel_map依輸入順序回傳，taskseed穩定，三個runs依序執行。

來源：eagle/execution.py；eagle/runtime/processes.py；eagle/evaluation/pipeline.py；eagle/evaluation/matches.py

## 15. 三次 replicate 與資料夾續跑




| 階段 | experiment.yaml／run | 恢復行為 |
| --- | --- | --- |
| 展開 config | random_seeds [8]、runs 3<br>有效序列 [8,8,8] | run1、run2、run3<br>各自獨立目錄與 checkpoint |
| 保存索引 | 每個 YAML filename<br>對應有序 run paths 清單 | 按 replicate slot 更新<br>不覆蓋其他 slot |
| --resume folder | 核對每槽 config／effective seed<br>先處理未完成 indexed runs | 已完成跳過<br>未啟動 replicate 接續建立 |
| 中斷時 | 以最後完整 generation 恢復<br>gen0 前失敗無 checkpoint | 無可用 checkpoint 可建替代run<br>原始失敗證據保留 |



詳細解說：索引schemaeagle-experiment-index-v1；source config的runs跟random_seeds展開成orderedslots。路徑是實際run_dirs，由on_run_created更新。resume不可將不相容policyformat/compiler/scaffold默默轉換。三次同seed是重複性檢查，不能把它當三個獨立randomseed樣本；GPU/runtime差異仍需用hash與timing檢查。

來源：eagle/experiment.py；eagle/evolution/resume.py；docs/operations/running_eagle.md

## 16. GPU 啟動與全層 offload 驗證




| 檢查 | 固定行為 | 不通過時 |
| --- | --- | --- |
| 裝置 preflight | llama-server --list-devices<br>確認 CUDA／NVIDIA backend | 停止啟動，不退回 CPU |
| 要求全層 | --n-gpu-layers 999<br>--fit off | 禁止自動記憶體 fitting<br>載入失敗即保留錯誤 |
| 證據可見性 | --log-verbosity 4 | core INFO 才輸出 offload 行<br>server ready 不代表驗證成功 |
| 實際 full offload | 只讀這次 child 的新 log<br>要求 offloaded N/N，N > 0 | 缺失／部分／stale 證據<br>停止 owned process |



詳細解說：Runtime先以--list-devices確認CUDA/NVIDIAbackend，再以--n-gpu-layers999、--fitoff要求完整model-layeroffload。--log-verbosity4讓core模型資訊可見。啟動成功需要serverhealth與本次ownedchild的新log都通過；offloadedN/N且N>0才接受。缺失、部分或stale證據停止ownedprocess。此要求針對model-layerGPU執行，其他CPU上的runtime或MicroRTS工作仍依一般流程進行。

來源：eagle/runtime/processes.py；eagle/runtime/config.py；tests/test_runtime_workflow.py

## 17. 執行與資料夾 resume 指令



- 開始：
./experiment.sh \
  configs/experiments/1015_deterministic_dsl_20x10_seed8_3runs
- 中斷後接續：
./experiment.sh --resume \
  configs/experiments/1015_deterministic_dsl_20x10_seed8_3runs
- 檢查 experiment.yaml 的 3 個 run paths；每次保存 gen0、gen1–20 與 final-test。



詳細解說：從EAGLErepo root執行experiment.sh。config保持deterministic_dsl、runs3與random_seeds[8]。首次執行建立每個run目錄與有序索引；folderresume依experiment.yaml找到未完成的run，從最後完整checkpoint接續，完成者跳過。gen0前沒有可用checkpoint時可建立替代run。正常完成且未指定skip-final-test時，run接著執行champion共同final-test。

來源：experiment.sh；eagle/cli/experiment.py；eagle/experiment.py
