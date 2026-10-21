# EAGLE Opponent Pool 圖解流程

搜尋採 self_play 與 tournament-v1，使用單一 Game Performance fitness、語意同分處理、靜態突變與父代快取重用。正式 Final Test 是獨立的固定基準測試。

保留刪頁後的 38 頁順序。來源 SHA-256：`0ceb9dd90620d68e255ebb9a5922616f4617384331ec4bd666734ac0b1db80e5`。

## 1. EAGLE Opponent Pool 流程

本流程固定採 evaluation.mode=self_play 與 self_play_pool_policy=tournament-v1。長期 opponent pool 保存內建對手與經入池規則保留的歷代策略；每個評估快照只用十個對手欄位。候選對戰時執行完整 Java，沒有即時 LLM 決策。Java materialization 與反思方式仍依所選模式啟用，但搜尋評估與選擇規則統一使用 opponent pool。正式 Final Test 是獨立的固定基準測試。

來源：eagle/config.py:360-388、747-760；eagle/opponent_pool.py:136-219；eagle/final_test.py。

## 2. Opponent Pool 搜尋流程

本流程先由 ChatGPT 人工準備固定 Java framework。G0 用十個內建對手完成初始候選評估，已評估族群開始按規則加入長期 opponent pool。後續每代在刷新到期時凍結四個保護對手加六個抽樣對手，保留父代 Java 並重新評估其分數，才選繁殖父代。子代評估使用同一快照；合併父代與子代選下一代後，所有已評估子代按入池規則挑戰或加入 pool，最後保存世代。尚未停止則繼續；停止後獨立執行固定內建對手的 Final Test。

來源：eagle/evolution/search.py:208-270；eagle/evolution/generation.py:94-285；eagle/opponent_pool.py:136-219。

## 3. 策略 DSL 的執行語意

版本截點：2026-10-21。程式版本：fcc8b770。
策略的 actor、when、action 都使用閉合的 MicroRTS 詞彙與可觀察狀態，允許合法策略多樣性。DSL 是基因資料，不是對戰時呼叫 LLM 的文字指令。deterministic_dsl 會經 typed IR 編譯；llm 則要求 Generator 實作同一份 DSL。合法動作守衛與 fallthrough 規則屬於共用語意。

程式來源（此版本的一基行號）：
docs/eagle_architecture_spec.md:49-78
eagle/strategy_dsl.py:1-120
docs/architecture/overview.md:112-127

## 4. Framework 的一次性建立與凍結

版本截點：2026-10-21。程式版本：fcc8b770。
有外部 bundle_path 時直接驗證該檔並凍結 run-owned copy，不再呼叫 bootstrap。沒有時依 backend 建立，預設 Groq，亦支援 Mistral 與 local。原始回應在解析前保存，失敗有界重試。每個 replicate 預設各自 bootstrap；要共用架構必須明確指定同一個 bundle。搜尋期間 Java 模板、槽位 domain 與表達式不變，resume 也不重新設計。

程式來源（此版本的一基行號）：
docs/architecture/framework_slots.md:24-75
docs/architecture/framework_slots.md:113-157
docs/eagle_architecture_spec.md:747-820

## 5. Framework 的有限選項

slot 是固定 Java 模板中的可替換位置。bundle 先定義每個 slot 的型別、合法值與表達式選單；候選只保存值或 choice_id。範例中 worker_target 從 2 到 8 的整數選 6，attack_weight 從 0、0.25、0.5、0.75、1 選 0.75，target_policy 選 lowest_hp。attack_weight、target_policy 與其選單為型別教學示例，不代表目前 bundle 的實際欄位。number 同樣是有限離散選單，0.6 在此例不合法。expression_choice 保存最低血量選項的 ID，由 bundle 中預先定義的 Java 表達式取代模板 marker，不生成新表達式。完整 genome 必須包含該 bundle 的全部 slot，不能只交這三項。

程式來源：eagle/generation/framework_slots.py:304-340、445-470。worker_target 實例來源：configs/framework_bundles/fixed_worker_combat/bundle.json。

版本截點：2026-10-21。程式版本：fcc8b770。
初始設計提示要求至少 24 個非恆定槽位，含至少 6 個 expression_choice 且各有至少 4 個選項，覆蓋經濟、生產、目標、戰鬥、條件與優先順序。這是設計目標，不能保證行為多樣性。候選人只保存槽值或 choice_id，不能生成新的 Java 表達式。相同 bundle、genome 與 materializer 應產生相同 Java bytes。

程式來源（此版本的一基行號）：
docs/architecture/framework_slots.md:24-75
eagle/generation/framework_slots.py:189-340

## 6. Framework 的 local 與 llm_coach

版本截點：2026-10-21。程式版本：fcc8b770。
兩種政策共享相同凍結 bundle、hash、renderer、下游評估與倖存者規則。llm_coach 回應必須恰好包含 schema_version、framework_bundle_sha256 與完整 control_genome。突變失敗不隨機改寫、不部分套用；初始選擇失敗保留採樣 genome 並在初始化階段標記該候選失敗。兩種模式都不進行 Prompt Reflection、Code gate、Java Generation 或 compile repair。

程式來源（此版本的一基行號）：
docs/architecture/framework_slots.md:13-75
eagle/operators/strategy.py:448-865
eagle/operators/framework_slots.py:1-200

## 7. Opponent Pool 的每個世代

一般世代產生 population_size 個子代；到期刷新對手快照時，繁殖前先重評父代。父代與子代必須在同一快照下比較。完成者以 Game Performance 分層，語意差異僅在層內輔助選擇。選擇之後更新 opponent pool，入池來源為所有已評估子代，不限倖存者。self_play 要求 static 反思操作；對手池挑戰與更新不會立即改變已凍結的評估快照。

來源：eagle/evolution/generation.py:94-285；eagle/config.py:747-760。

## 8. Opponent Pool 的繁殖父代選擇

繁殖父代來自目前 population，與用來提供評估對手的歷史 opponent pool 分開。使用單一 Game Performance fitness；從目前最高分往下 tolerance 以內形成頂層，預設 tolerance=1.0 且包含邊界，不採相鄰分數串連。第一父代以 seeded RNG 從有完整語意簽章者抽樣；若沒有完整簽章則從頂層候選抽樣。第二父代以第一父代為參照，優先選相容動作簽章距離最大者，距離相同時 seeded 抽樣；沒有可比資料時保留 fallback。兩次選擇沒有強制父代 ID 相異。

來源：eagle/operators/selection.py:42-68、200-215、245-282；eagle/evolution/offspring.py:91-119。

## 9. Opponent Pool 的父代選擇示例

教學示例，非實驗結果。A、B、C、D 的 fitness 分別為 100、99.4、99.0、98.8，tolerance=1.0，因此頂層只有 A、B、C。C 剛好在含邊界的門檻；D 不會因距離 C 很近而串連進來。假設第一父代 seeded 選到 B，且相容的九個 probes 中 A 與 B 有八個動作不同，C 與 B 有兩個不同，則第二父代選 A。D 已在頂層外，不能因行為新穎而越級。

來源：eagle/operators/selection.py:42-68、200-215、245-282、311-320。

## 10. 交配與來源譜系

版本截點：2026-10-21。程式版本：fcc8b770。
直接父代列表與每個成分實際來源是不同資訊，均需保存。兩位父代可以提供不同成分，即使文字或值相同也不能省略來源。Framework 的 Coach 證據父代是 parent A，不會因某槽位從 donor B 繼承就改用 B 的比賽。crossover_rate 控制是否交配，未交配時沿用單一來源。

程式來源（此版本的一基行號）：
docs/eagle_architecture_spec.md:216-223
eagle/operators/crossover.py:1-170
eagle/operators/framework_slots.py:1-155

## 11. LLM 模式的交配前 Code gate

版本截點：2026-10-21。程式版本：fcc8b770。
所有實際貢獻來源都必須健康才可進入正常交配與突變。Code v6 只檢查 strategy_fidelity 與 code_correctness；不因勝率、外觀或可簡化而要求修正。ambiguous_strategy 配合正確 Java 不需 revision。有缺陷就產生一位保留原基因的 corrective child，跳過交配與一般突變；診斷失敗也不能當健康通過。Code gate 沒有 AOS 操作機率。DSL 與 framework 模式不執行此 gate。

程式來源（此版本的一基行號）：
docs/eagle_architecture_spec.md:49-78
eagle/operators/code.py:29-180
eagle/evolution/offspring.py:125-280

## 12. Strategy Reflection 的證據路徑

版本截點：2026-10-21。程式版本：fcc8b770。
最差場次只從記錄的策略來源父代中取，不能任意從 child、donor 或整個 run 換一場。Match Commentator 看一場詳細 trace；Coach 同時取得全場 global summary 與此一 diagnosis，以免只看局部比賽。LLM/DSL 模式改 policy，framework llm_coach 則改完整 genome。策略反思失敗保留既有資料並走失敗分支，沒有自動換賽事補救。

程式來源（此版本的一基行號）：
docs/eagle_architecture_spec.md:248-275
eagle/operators/strategy.py:202-447
eagle/operators/strategy.py:576-865
eagle/operators/strategy.py:1222-1308

## 13. 最差場次與策略回應的驗證

版本截點：2026-10-21。程式版本：fcc8b770。
每場 performance 包含 shaping，因此同為敗場也能分辨較差表現。JSONL 是 field-targeted 完整規則紀錄，不能把零碎 condition/action 修成另一個沒有被模型完整提出的規則。舊的整份 JSON 回應仍採 all-or-nothing 驗證。framework Coach 使用另一份完整 genome schema，不能套用 DSL 的合法子集合邏輯。

程式來源（此版本的一基行號）：
docs/eagle_architecture_spec.md:248-275
eagle/operators/strategy.py:1222-1308
eagle/operators/strategy.py:1638-1710

## 14. Prompt Reflection 的資料邊界

版本截點：2026-10-21。程式版本：fcc8b770。
Prompt Reflection 改良的是可重用的 policy-to-Java 翻譯規則。Reviewer 不接收勝敗、fitness、對手分數、比賽 trace 或其他 gameplay evidence。預設模式比較來源父代的 policy 與 Java；inherited 模式比較 child 選中的 policy 與 inherited Java。新 prompt 不直接修改策略基因，最後仍由 Generator 生成 Java。只在 llm materialization 啟用。

程式來源（此版本的一基行號）：
docs/eagle_architecture_spec.md:277-309
eagle/operators/prompt.py:268-525

## 15. 三條 Java 產生路徑

版本截點：2026-10-21。程式版本：fcc8b770。
LLM 回應必須先滿足完整檔案的 package、class、建構子、lifecycle 與單一 strategy-marker 區域等外框，再以固定 scaffold 加上抽出的策略區域建立 normalized Java。固定區域中的模型改動保留為證據，但不進表型。結構非法的回應不能靠 normalization 變成合法。確定性兩條路徑沒有 LLM fallback。

程式來源（此版本的一基行號）：
docs/eagle_architecture_spec.md:313-405
docs/eagle_architecture_spec.md:700-820
eagle/evaluation/decoding.py:1-130

## 16. LLM 生成與有界修復

版本截點：2026-10-21。程式版本：fcc8b770。
attempt 1 通常是普通生成，corrective child 則直接使用 Code Reflection 已回傳的完整 Java。完整 source 的驗證或編譯失敗可在 generation_max_attempts 內用專門 compile-repair prompt 修復。每次 request、raw response、抽取 source、normalized source 與 hash 都保存。第一個 validation＋compilation 成功即停止；Integration 或 runtime 失敗不回到 decoder。

程式來源（此版本的一基行號）：
docs/eagle_architecture_spec.md:350-405
eagle/evaluation/decoding.py:1-160

## 17. Validation、編譯與七項 Integration

版本截點：2026-10-21。程式版本：fcc8b770。
Java contract 同時限制 network、process execution、未授權 I/O 與 runtime modification；它不是一般用途 Java sandbox。編譯保留結構化去重診斷與 warning。Integration 前置檢查失敗會阻擋後面的檢查與對戰。獨立實例檢查確保 getAction 與 PlayerAction 在有單位的真實地圖可運作，成功仍不能證明所有對戰情境都正確。

程式來源（此版本的一基行號）：
docs/eagle_architecture_spec.md:378-424
eagle/generation/java_agent_generator.py:256-329
eagle/evaluation/microrts_runner.py:1-140

## 18. 搜尋評估的 180 場矩陣

搜尋評估使用凍結的 opponent-pool 十欄快照：四個保護對手與六個抽樣對手。只有通過 materialization、validation、compilation 與 Integration 的候選能進入對戰。每欄三張地圖、三回合、雙方位置，共十八場，十欄共一百八十場。每場使用衍生 seed、地圖 tick cap 與 timeout。矩陣必須完整才有有效 fitness。同一快照內父代與子代使用同一名單；長期 pool 更新不立即更換這個名單。

來源：eagle/evaluation/match_matrix.py；eagle/evaluation/matches.py；eagle/self_play.py:24-79。

## 19. Game Performance 與分數彙總

Opponent-pool 搜尋使用單一 Game Performance fitness。單場結果的敗、和、勝基分為 -100、0、100，再加最多正負十的物資、資源與存活 shaping。每個對手十八場先取平均，十個對手欄位再等權平均；因每欄場數相同，也等於完整一百八十場的平均。四個保護對手沒有較高評分權重。語意距離只在分數同層內輔助選擇，不另加 fitness。必要階段失敗或矩陣未完成使用 -1000 sentinel；失敗候選保留診斷但不能擠掉足夠的完整評估候選。AllInBot 被 adapter containment 的上游故障以中性零分和局記錄，另列 opponent fault。

來源：eagle/evaluation/game_performance.py:207-219；eagle/config.py:372-388；eagle/operators/selection.py:93-129；eagle/evaluation/matches.py。

## 20. Opponent Pool 的十個起始對手

初始 pool 含十個內建來源。PassiveAI、RandomAI、RandomBiasedAI、LightRush、HeavyRush、WorkerRush 是六個可替換成員；AllInBot、Mayari、COAC、TMA 是四個永久保護成員。G0 評估使用全部十個內建對手。後續可替換區累積經規則入池的歷代策略，每個刷新快照保留四個保護對手，再從非保護成員抽六名。這是 pool 的初始化名單，並不表示整個演化期間固定對戰這十位。搜尋評分十欄等權。

來源：eagle/opponents.py:1-145；eagle/opponent_pool.py:22-35、136-219；eagle/self_play.py:24-79。

## 21. Opponent Pool 的起始與容量

版本截點：2026-10-21。程式版本：fcc8b770。
長期 opponent pool 與每次凍結的十個評估欄位分開保存。Pool 初始是所有十個內建對手，之後納入合法且新穎的歷代候選策略。它不是只存當代十個策略，也不是只收歷代冠軍。總容量 50 是設定預設，不代表每次評估要跑五十個對手。

程式來源（此版本的一基行號）：
docs/eagle_architecture_spec.md:461-481
eagle/opponent_pool.py:22-35
eagle/opponent_pool.py:162-219

## 22. 新策略的來源與入池挑戰

版本截點：2026-10-21。程式版本：fcc8b770。
第 0 代 update_pool 接收 evaluated_population，後續每代接收 evaluated_offspring，並非只傳下一代倖存者。候選須通過可執行與完整評估條件，去除 ID、source 或 semantic phenotype 的重複項。滿池時每個 novel entrant 對一個 seeded 守擂者跑完 18 場；勝和敗分別計 1、0.5、0，只有 wins > losses 才 promotion，平手保留守擂者。失敗或未完成保留證據但不能晉級。

程式來源（此版本的一基行號）：
eagle/evolution/search.py:208-219
eagle/evolution/generation.py:254-262
eagle/opponent_pool.py:162-219
eagle/opponent_pool.py:400-430

## 23. 凍結的十個評估對手

版本截點：2026-10-21。程式版本：fcc8b770。
這裡的十個是評估對手欄位，不是當代子代人口數。刷新預設 interval 5，第 1 代即刷新，之後第 6、11、16 代。Pool 在世代結束可以更新，但已凍結 context 不立即跟著改變。新入池策略要等後續快照刷新才可能被抽到。四保護 case IDs 固定，六個動態 diagnostic slots 為 self_play_000 到 self_play_005，來源寫在 context rows。

程式來源（此版本的一基行號）：
docs/eagle_architecture_spec.md:482-511
eagle/opponent_pool.py:136-159
eagle/self_play.py:24-79

## 24. 對手快照刷新與父代重評

self_play 要求 parent_evaluation_mode=reuse_cached。快照不變時沿用父代 Java 與已完成分數。快照刷新是協定內的必要重評：建立新 ID 父代複本，保留原 Java 表型，使用新十欄名單跑完評估，不覆寫舊 context 的分數與證據。刷新評估先完成，才做繁殖選擇；子代也在該快照中評估，讓父代與子代的 fitness 可在倖存選擇時比較。

來源：eagle/config.py:747-760；eagle/evolution/generation.py:94-170；eagle/evolution/parent_refresh.py。

## 25. 父代重用與對手快照重評

本流程只有兩種父代評估情境。對手快照不變時，reuse_cached 保留 Java 與原分數；到期刷新時，快照協定自動建立父代評估複本，用新名單重新對戰，但不重新生成 Java。self_play 設定驗證要求 reuse_cached，不能使用 regenerate_same_genotype 診斷模式。父代先完成新情境評分才能繁殖，子代隨後使用同一快照完成評估。

來源：eagle/config.py:747-760；eagle/evolution/generation.py:94-170；eagle/evolution/parent_refresh.py。

## 26. 語意探針與同分處理

Opponent-pool 流程強制啟用語意探針。固定三張地圖的三個階段共九個 probe，記錄實際 Java 動作簽章，距離為動作 hash 不同的 probe 比例；dataset、probe 次序與簽章需相容。繁殖時第二父代在頂層內偏好與第一父代距離較遠者。倖存者只有名額切分同一分數層時才使用 seeded max-min 子集，不能越過分數層。精確相同行為亦用於 opponent pool 的表型去重。語意不構成另一個 fitness 目標。

來源：eagle/config.py:747-750；eagle/operators/selection.py:174-282、311-320；eagle/opponent_pool.py:499-540。

## 27. Opponent Pool 的倖存者選擇

將當代父代與已評估子代合併並按 ID 去重，只讓完整評估候選參與下一代。目標為固定人口 N。依當前剩餘候選的最高分作錨點，往下預設 1.0 分以內形成一層，不採相鄰串連；例如 100、99.2 同層，98.4 屬下一層。整層放得下就整層保留；名額切在一層內才用 seeded farthest-first max-min，最大化對已選者與本層已挑者的最小語意距離。低分層不能靠新穎性越級。若所有子代失敗但仍有 N 位完整評估父代，父代可全數留下；完整者不足 N 時 run 明確失敗。

來源：eagle/operators/selection.py:70-145、174-282；eagle/evolution/generation.py:214-229。

## 28. Opponent Pool 的靜態突變操作

self_play 設定明確要求 reflection_operator_mode=static，不使用 AOS Opponents rank、EMA 或 head-to-head reward 更新機率。交配後依固定 mutation_rate 決定是否突變；未觸發時保留交配後基因。Framework local 至多更換一個槽位為另一合法值；Framework Coach 回傳完整 control_genome。LLM／DSL 依各自可用的反思操作與靜態配比選擇，功能是否啟用仍由 materialization 模式決定。對戰提供 Game Performance 與反思證據，不動態調整操作機率。十八場 pool 入池挑戰是另一個機制，不能和 AOS head-to-head 混用。

來源：eagle/config.py:747-760；eagle/evolution/offspring.py:281-300、430-480；eagle/operators/adaptive.py:215-230。

## 29. 失敗、重試與停止的邊界

版本截點：2026-10-21。程式版本：fcc8b770。
失敗分類包括初始化、反思、生成、驗證、編譯、Integration 與 runtime 等。候選失敗與 run 失敗需分開：只要完成的父代與子代足夠，下一代仍可成立。程序中斷會取消排隊工作、drain active worker，保留未完成證據後從最後完成世代恢復。Pipeline 安全邊界不能以看起來可執行的 fallback 代替。

程式來源（此版本的一基行號）：
docs/eagle_architecture_spec.md:350-424
docs/evaluation/game_performance.md:33-40
eagle/operators/selection.py:99-123

## 30. 每個 run 的保存與稽核

版本截點：2026-10-21。程式版本：fcc8b770。
Generation snapshot 先原子寫成功，再更新 manifest.latest_generation。只有 manifest 指定的完成快照作為 resume 起點，不能因資料夾有較新檔就推論已提交世代。每次 LLM request 的 endpoint/model、prompt、raw response、attempt、hash 與 timing 都屬證據；秘密憑證不可寫入。compact artifact 模式省去 XML replay，但保留需要的 trace 與對戰摘要。

程式來源（此版本的一基行號）：
eagle/run_artifacts.py:160-197
eagle/run_artifacts.py:363-375
docs/artifacts/artifact_schema.md:37-92
docs/eagle_architecture_spec.md:567-629

## 31. 中斷後的恢復流程

版本截點：2026-10-21。程式版本：fcc8b770。
Resume 不是繼續使用任意半成品，也不重新 bootstrap。先檢查目前版本與凍結身分能否相容；protocol、bundle hash、framework evolution mode 或 runtime/map 身分不合時拒絕。未提交候選與 LLM 證據先移入 interrupted_work，保留後再以穩定 ID 重播。這維持可追查性，但外部 LLM 回應與 wall-clock timeout 仍可能讓重播結果不同。

程式來源（此版本的一基行號）：
eagle/evolution/resume.py:1-150
eagle/run_artifacts.py:686-703
docs/eagle_architecture_spec.md:162-215
docs/architecture/framework_slots.md:140-149

## 32. 多組設定、replicate 與資料夾續跑

版本截點：2026-10-21。程式版本：fcc8b770。
明確 random_seeds 時 runs 是每個 seed 的重複次數。省略 random_seeds 則沿用 random_seed、random_seed+1 的歷史排程。Index 保存有序的 absolute run paths，每個 slot 都檢查 seed 與 config 身分。Framework fresh replicate 預設各自生成 bundle，若研究需控制架構差異，必須指定相同外部 bundle。Folder rerun 會處理未開始、未完成與缺 final test 的不同情況。

程式來源（此版本的一基行號）：
eagle/config.py:863-879
eagle/experiment.py:355-540
docs/artifacts/artifact_schema.md:491-529

## 33. 可重現性與相同版本續跑

版本截點：2026-10-21。程式版本：fcc8b770。
執行總是對可控制的隨機性設 seed，沒有另一個 deterministic_mode 開關。模型 provider 可能忽略 seed 或更新權重；GPU batching、浮點數、第三方對手二進位與 wall-clock 搜尋都可能改變結果。Deterministic materialization 的 byte-identical Java 契約不等於整場實驗逐位元相同。重現承諾需限定同程式、資料、設定與確定的 task outputs。

程式來源（此版本的一基行號）：
docs/eagle_architecture_spec.md:162-215
eagle/evaluation/determinism.py:1-170
eagle/execution.py:14-68

## 34. 停止條件與正式 Final Test

搜尋階段使用會刷新的 opponent-pool 快照，停止後的正式 Final Test 另外使用固定十個內建對手，是獨立 benchmark，不改變搜尋協定。停止條件為演化世代上限或 active selection-state signature 的 stagnation。預設從末代選可執行代表，獨立重新編譯並跑七項 Integration，再執行十對手、三地圖、十回合、雙方位置，共六百場。mock 或 skip-final-test 可略過。十八場入池挑戰只決定長期池成員替換，一百八十場搜尋評估決定 fitness，六百場 Final Test 作正式測試，三者各自保存證據。

來源：eagle/final_test.py；eagle/experiment.py:409-423；eagle/opponent_pool.py:217-430。

## 35. 跨世代的公平比較

版本截點：2026-10-21。程式版本：fcc8b770。
python -m eagle.fixed_evaluation 只讀取 completed run 的明確指定世代，不缺代替代、不用 run-wide best 取代 snapshot 代表。每位代表重編與 Integration，不呼叫 LLM。protocol 記錄對手、地圖 hash、tick cap、scoring 與 runtime source identity。缺場或錯誤矩陣的 aggregate score 與 win rate 為 null 並 nonzero exit。mean_match_score 是不加權 benchmark 平均，不能直接當搜尋 fitness。

程式來源（此版本的一基行號）：
docs/evaluation/evaluation_pipeline.md:160-166
eagle/fixed_evaluation.py:1-170

## 36. 結果、時間與比較的解讀

版本截點：2026-10-21。程式版本：fcc8b770。
時間來源以已提交 generation timing 與 run records 為準，不能將 partial terminal output 當單代耗時。當對手情境改變，search fitness 的跨代上升並不能單獨證明一般化能力。比較現行多主機串流與先前排程時，需要相同模型、硬體、seed、候選規模與失敗條件下的獨立速度實驗。實作文件尚無這組 live benchmark，不能報出加速比。

程式來源（此版本的一基行號）：
docs/evaluation/game_performance.md:42-57
docs/artifacts/timing_schema.md:1-65
docs/implementation/current_status.md:21-34

## 37. GUI、監看與離線分析

版本截點：2026-10-21。程式版本：fcc8b770。
GUI 提供 config parsing 支持的固定選項，儲存前驗證並原子寫入，觀察比賽不改變 fitness。Monitor 從 manifest 和最新已提交 generation 讀取，不控制實驗。離線分析的 generation 指倖存快照世代，birth_generation 才是候選出生時間。使用者可以從這些工具回查分數、行為與 LLM evidence，無需改動 canonical search artifacts。

程式來源（此版本的一基行號）：
docs/implementation/current_status.md:42-66
docs/architecture/evolutionary_flow.md:169-200
eagle/analysis/report.py:1-130

## 38. 目前 Framework Coach 設定範例

版本截點：2026-10-21。程式版本：fcc8b770。
這頁是目前 checked-in config 的具體範例，不是所有模式的預設。頂層 model 為 Qwen 3.5-9B，含本地 managed primary 與一個外部 additional endpoint；機器路徑與位址需配合實際環境。bootstrap_backend 為 mistral、framework.model 為 mistral-small-latest。此配置示範完整流程的實際連接，並不宣稱本次已啟動或完成這組實驗。

程式來源（此版本的一基行號）：
configs/framework_coach.yaml:1-98
eagle/config.py:580-658

## 39. 穩定性比較：相同 framework，兩批重跑

來源：reports/1021_framework_stability_comparison.md；SHA-256 09f96e8b825f43e9e47a40d578afd85dd5108d626332b2b1bad61f28283dde87。報告快照：2026-10-21 13:35 Asia/Taipei。未刷新即時批次狀態。

兩批均為 framework_slots、framework.evolution_mode=local、population_size=10、演化 G1–20、self_play 與 tournament-v1。相同 bundle SHA-256：b2daa0d4baac80e446d46e5d32f6fd94a4300bec51f23b4816723c6d8f90939b。靜態操作，搜尋期間不呼叫 candidate-time LLM。報告指出 resolved config 的實質差異僅 experiment name、seed 清單與 run-owned bundle 路徑，bundle bytes 相同。上次六 run 為 10/19–10/20，本次批次為 10/21。11 個完成 run 的 G20 均 1800/1800、failure_count=0；每個 Final Test 均 600 場、Integration success、0 errors。這支持已測配置與矩陣的執行可靠性，不代表所有情境無錯誤。
完整 run 索引：{"columns":["cohort","seed","run_id","generations_completed","generations_target","final_test_completed","final_test_target","status"],"rows":[{"cohort":"上次","seed":8,"run_id":"20261019_152601_037528","generations_completed":20,"generations_target":20,"final_test_completed":600,"final_test_target":600,"status":"complete"},{"cohort":"上次","seed":9,"run_id":"20261019_182037_312877","generations_completed":20,"generations_target":20,"final_test_completed":600,"final_test_target":600,"status":"complete"},{"cohort":"上次","seed":10,"run_id":"20261019_103405_871333","generations_completed":20,"generations_target":20,"final_test_completed":600,"final_test_target":600,"status":"complete"},{"cohort":"上次","seed":11,"run_id":"20261020_135403_027378","generations_completed":20,"generations_target":20,"final_test_completed":600,"final_test_target":600,"status":"complete"},{"cohort":"上次","seed":12,"run_id":"20261020_170514_392422","generations_completed":20,"generations_target":20,"final_test_completed":600,"final_test_target":600,"status":"complete"},{"cohort":"上次","seed":13,"run_id":"20261020_195907_969170","generations_completed":20,"generations_target":20,"final_test_completed":600,"final_test_target":600,"status":"complete"},{"cohort":"本次","seed":8,"run_id":"20261021_002848_496277","generations_completed":20,"generations_target":20,"final_test_completed":600,"final_test_target":600,"status":"complete"},{"cohort":"本次","seed":9,"run_id":"20261021_034914_985024","generations_completed":20,"generations_target":20,"final_test_completed":600,"final_test_target":600,"status":"complete"},{"cohort":"本次","seed":10,"run_id":"20261021_074505_348782","generations_completed":20,"generations_target":20,"final_test_completed":600,"final_test_target":600,"status":"complete"},{"cohort":"本次","seed":11,"run_id":"20261021_131355_062329","generations_completed":20,"generations_target":20,"final_test_completed":600,"final_test_target":600,"status":"complete"},{"cohort":"本次","seed":12,"run_id":"20261021_165442_013504","generations_completed":20,"generations_target":20,"final_test_completed":600,"final_test_target":600,"status":"complete"},{"cohort":"本次","seed":13,"run_id":"20261021_202021_187555","generations_completed":4,"generations_target":20,"final_test_completed":null,"final_test_target":null,"status":"running"}],"reported_completed_runs":11,"reported_pending_runs":1}
未完成項：{"cohort":"本次","seed":13,"run_id":"20261021_202021_187555","status_at_report_snapshot":"running","report_snapshot_generations":"4/20","final_test_status":"尚未開始","generation_0_to_4_each_matches":"1800/1800","generation_0_to_4_failure_count":0,"generation_4_best":-11.475,"generation_4_population_mean":-12.435,"live_status_checked":false,"note":"僅保存報告截點，不代表目前即時狀態。"}

## 40. G20 搜尋分數：重跑差異因 seed 而異

來源：reports/1021_framework_stability_comparison.md；SHA-256 09f96e8b825f43e9e47a40d578afd85dd5108d626332b2b1bad61f28283dde87。報告快照：2026-10-21 13:35 Asia/Taipei。未刷新即時批次狀態。

縱軸為各 run G20 population best Game Performance，非 population mean。主圖只並列 seed 8–12；上次 seed13 另列，避免將本次未完成 seed13 填成零。各 run 的 opponent-pool 快照可能不同，這些值只描述各自搜尋情境，不是固定難度的能力比較。上次六 seed best 平均 5.884，本次五 seed 1.861；樣本不齊，不能以 -4.023 推論架構退化。seed10 的兩個 G20 best 差 0.004 是觀察，不足以歸因其他 run 差異的原因。
G20 全部 best、population mean、population sd、semantic unique：{"previous":{"runs":6,"columns":["seed","best","population_mean","population_sd","semantic_unique","population_size"],"rows":[{"seed":8,"best":5.592,"population_mean":4.307,"population_sd":0.675,"semantic_unique":1,"population_size":10},{"seed":9,"best":25.733,"population_mean":24.711,"population_sd":0.691,"semantic_unique":2,"population_size":10},{"seed":10,"best":-32.037,"population_mean":-38.789,"population_sd":3.609,"semantic_unique":2,"population_size":10},{"seed":11,"best":10.988,"population_mean":9.419,"population_sd":0.696,"semantic_unique":1,"population_size":10},{"seed":12,"best":6.761,"population_mean":5.639,"population_sd":0.698,"semantic_unique":1,"population_size":10},{"seed":13,"best":18.267,"population_mean":15.719,"population_sd":1.029,"semantic_unique":4,"population_size":10}],"reported_mean_best":5.884,"computed_mean_best_from_displayed_rows":5.884,"semantic_unique_counts":[1,2,2,1,1,4]},"current_completed":{"runs":5,"columns":["seed","best","population_mean","population_sd","semantic_unique","population_size"],"rows":[{"seed":8,"best":-3.342,"population_mean":-5.262,"population_sd":0.801,"semantic_unique":3,"population_size":10},{"seed":9,"best":23,"population_mean":21.126,"population_sd":1.073,"semantic_unique":1,"population_size":10},{"seed":10,"best":-32.033,"population_mean":-38.788,"population_sd":3.613,"semantic_unique":2,"population_size":10},{"seed":11,"best":13.118,"population_mean":12.466,"population_sd":0.307,"semantic_unique":1,"population_size":10},{"seed":12,"best":8.561,"population_mean":7.886,"population_sd":0.41,"semantic_unique":1,"population_size":10}],"reported_mean_best":1.861,"computed_mean_best_from_displayed_rows":1.8608,"semantic_unique_counts":[3,1,2,1,1]},"reported_mean_best_delta_current_minus_previous":-4.023}

## 41. 搜尋軌跡：同 seed 的形狀多次接近

來源：reports/1021_framework_stability_comparison.md；SHA-256 09f96e8b825f43e9e47a40d578afd85dd5108d626332b2b1bad61f28283dde87。報告快照：2026-10-21 13:35 Asia/Taipei。未刷新即時批次狀態。

六個圖共用相同縱軸 -80 到 40，橫軸 G0、G5、G10、G15、G20，數值為該世代 population best。上次用玫瑰色，本次用酒紅色。seed13 只有上次完整軌跡，本次 G4 不放入 G20 曲線。對手快照會刷新，曲線僅描述 run 內的搜尋情境，不能視為固定對手難度下的能力成長。seed10 兩次軌跡接近且 G20 回落至約 -32；這是可觀察的搜尋路徑，不能單憑曲線判定因果。
完整軌跡：{"columns":["seed","cohort","g0","g5","g10","g15","g20"],"rows":[{"seed":8,"cohort":"上次","g0":-57.328,"g5":-1.36,"g10":6.184,"g15":5.124,"g20":5.592},{"seed":8,"cohort":"本次","g0":-57.338,"g5":-1.108,"g10":5.643,"g15":5.716,"g20":-3.342},{"seed":9,"cohort":"上次","g0":-71.714,"g5":-58.547,"g10":-18.482,"g15":22.95,"g20":25.733},{"seed":9,"cohort":"本次","g0":-71.713,"g5":-58.572,"g10":-19.243,"g15":22.496,"g20":23},{"seed":10,"cohort":"上次","g0":-70.592,"g5":-49.131,"g10":-41.481,"g15":-14.999,"g20":-32.037},{"seed":10,"cohort":"本次","g0":-70.59,"g5":-49.136,"g10":-41.493,"g15":-15.003,"g20":-32.033},{"seed":11,"cohort":"上次","g0":-69.304,"g5":4.586,"g10":24.21,"g15":22.45,"g20":10.988},{"seed":11,"cohort":"本次","g0":-69.3,"g5":7.34,"g10":20.633,"g15":24.229,"g20":13.118},{"seed":12,"cohort":"上次","g0":-70.457,"g5":0.01,"g10":9.678,"g15":23.498,"g20":6.761},{"seed":12,"cohort":"本次","g0":-70.451,"g5":0.007,"g10":12.555,"g15":24.649,"g20":8.561},{"seed":13,"cohort":"上次","g0":-70.967,"g5":-11.476,"g10":-2.799,"g15":-5.855,"g20":18.267}]}

## 42. 正式測試：零執行錯誤，勝率約三成

來源：reports/1021_framework_stability_comparison.md；SHA-256 09f96e8b825f43e9e47a40d578afd85dd5108d626332b2b1bad61f28283dde87。報告快照：2026-10-21 13:35 Asia/Taipei。未刷新即時批次狀態。

相同正式測試協定，每 run 為十對手、三地圖、每邊十場，共六百場。圖中各組百分比由 W、D、L 除以該組 matches 計算；W/D/L/E 欄位順序固定。兩批分母為 3600 與 3000，本次排除 seed13。報告勝率 32.33% 與 30.17% 是各批聚合，不是相同 seed 配對效果，不能據此判定架構退化。所有 11 個完成 Final Test Integration success、0 errors。
完整正式測試資料：{"protocol_matches_per_run":600,"columns":["cohort","runs","wins","losses","draws","errors","matches","aggregate_win_rate_percent"],"cohorts":[{"cohort":"上次六 seed","runs":6,"wins":1164,"losses":2284,"draws":152,"errors":0,"matches":3600,"aggregate_win_rate_percent":32.33},{"cohort":"本次已完成五 seed","runs":5,"wins":905,"losses":1950,"draws":145,"errors":0,"matches":3000,"aggregate_win_rate_percent":30.17}],"source_note":"Cohort counts are report totals; win rate is wins divided by all matches."}

## 43. Hard opponents 仍是共同弱點

來源：reports/1021_framework_stability_comparison.md；SHA-256 09f96e8b825f43e9e47a40d578afd85dd5108d626332b2b1bad61f28283dde87。報告快照：2026-10-21 13:35 Asia/Taipei。未刷新即時批次狀態。

本次已完成 seed8–12，每個對手五 run × 六十場=三百場。AllInBot、Mayari、COAC、TMA 合計 1200 場、11 勝、14 和、1175 敗、0 errors；勝率 0.92% 為計算值。COAC 的十勝集中於 seed11。其餘能力剖面依報告：PassiveAI／RandomAI 穩定取勝或打平；RandomBiasedAI 有較多勝場但 seed 間差異明顯；三種 Rush 尚無一致 counter。報告未提供這六個對手的逐項勝和敗數，不另造數值。
四個 hard opponents 原始資料：{"cohort":"本次已完成 seed 8–12","runs":5,"columns":["opponent","wins","draws","losses","errors","matches","runs"],"rows":[{"opponent":"AllInBot","wins":1,"draws":3,"losses":296,"errors":0,"matches":300,"runs":5},{"opponent":"Mayari","wins":0,"draws":11,"losses":289,"errors":0,"matches":300,"runs":5},{"opponent":"COAC","wins":10,"draws":0,"losses":290,"errors":0,"matches":300,"runs":5},{"opponent":"TMA","wins":0,"draws":0,"losses":300,"errors":0,"matches":300,"runs":5}],"source_note":"Errors are 0 per report statement that all five completed final tests had zero errors."}

## 44. 九狀態探針：末代行為多樣性偏低

來源：reports/1021_framework_stability_comparison.md；SHA-256 09f96e8b825f43e9e47a40d578afd85dd5108d626332b2b1bad61f28283dde87。報告快照：2026-10-21 13:35 Asia/Taipei。未刷新即時批次狀態。

圖中為 G20 semantic unique／population10，並列 seed8–12；上次 seed13=4 另列，本次 seed13未納入。上次六 run 為 [1,2,2,1,1,4]，本次五 run 為 [3,1,2,1,1]。多數 run 在九個固定探針中只剩一到兩種行為簽章，不等於在所有遊戲狀態中只有一到兩種行為。Framework 不使用 Strategy DSL niche；known_signature_count=0 不能拿來判定 framework 行為沒有多樣性。population mean 和 population sd 請見完整 G20 資料。
完整 G20 資料：{"previous":{"runs":6,"columns":["seed","best","population_mean","population_sd","semantic_unique","population_size"],"rows":[{"seed":8,"best":5.592,"population_mean":4.307,"population_sd":0.675,"semantic_unique":1,"population_size":10},{"seed":9,"best":25.733,"population_mean":24.711,"population_sd":0.691,"semantic_unique":2,"population_size":10},{"seed":10,"best":-32.037,"population_mean":-38.789,"population_sd":3.609,"semantic_unique":2,"population_size":10},{"seed":11,"best":10.988,"population_mean":9.419,"population_sd":0.696,"semantic_unique":1,"population_size":10},{"seed":12,"best":6.761,"population_mean":5.639,"population_sd":0.698,"semantic_unique":1,"population_size":10},{"seed":13,"best":18.267,"population_mean":15.719,"population_sd":1.029,"semantic_unique":4,"population_size":10}],"reported_mean_best":5.884,"computed_mean_best_from_displayed_rows":5.884,"semantic_unique_counts":[1,2,2,1,1,4]},"current_completed":{"runs":5,"columns":["seed","best","population_mean","population_sd","semantic_unique","population_size"],"rows":[{"seed":8,"best":-3.342,"population_mean":-5.262,"population_sd":0.801,"semantic_unique":3,"population_size":10},{"seed":9,"best":23,"population_mean":21.126,"population_sd":1.073,"semantic_unique":1,"population_size":10},{"seed":10,"best":-32.033,"population_mean":-38.788,"population_sd":3.613,"semantic_unique":2,"population_size":10},{"seed":11,"best":13.118,"population_mean":12.466,"population_sd":0.307,"semantic_unique":1,"population_size":10},{"seed":12,"best":8.561,"population_mean":7.886,"population_sd":0.41,"semantic_unique":1,"population_size":10}],"reported_mean_best":1.861,"computed_mean_best_from_displayed_rows":1.8608,"semantic_unique_counts":[3,1,2,1,1]},"reported_mean_best_delta_current_minus_previous":-4.023}

## 45. 結論：執行可靠，探索與能力仍待改善

來源：reports/1021_framework_stability_comparison.md；SHA-256 09f96e8b825f43e9e47a40d578afd85dd5108d626332b2b1bad61f28283dde87。報告快照：2026-10-21 13:35 Asia/Taipei。未刷新即時批次狀態。

報告結論分開理解：11 個已完成 run 支持此配置與已測矩陣的執行可靠性；跨 seed 結果與 hard-opponent 能力仍不一致；末代九狀態簽章多為一到兩類。現有搜尋分數受快照情境影響，不足以作架構退化或一般化能力改善的因果判定。建議先等報告中的 seed13完成，再補齊同六 seed 的正式測試比較；若目標是策略品質，控制條件測試語意探索與 hard-opponent coverage，而非先改 materialization。建議尚未執行，沒有啟動新實驗。
耗時證據缺口：{"available":false,"scope":"No measured wall-time value was accessible from the named run artifacts in this checkout.","sample_run_ids_checked":["20261019_152601_037528","20261021_002848_496277","20261021_165442_013504"],"missing_paths_checked":["runs/20261019_152601_037528/manifest.json","runs/20261019_152601_037528/summary.json","runs/20261019_152601_037528/timing.jsonl","runs/20261019_152601_037528/final_test/final_test_summary.json","runs/20261021_002848_496277/manifest.json","runs/20261021_002848_496277/summary.json","runs/20261021_002848_496277/timing.jsonl","runs/20261021_002848_496277/final_test/final_test_summary.json","runs/20261021_165442_013504/manifest.json","runs/20261021_165442_013504/summary.json","runs/20261021_165442_013504/timing.jsonl","runs/20261021_165442_013504/final_test/final_test_summary.json"],"initialization_separation":"No timing.jsonl was available to separate initialization from completed evolutionary generations. Do not derive per-generation or total wall time from the report tables."}。報告沒有 run wall time、G0 與 G1–20 完成世代耗時；不能由分數表推導時間，也不報加速比。
