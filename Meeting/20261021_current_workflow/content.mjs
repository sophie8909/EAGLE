// Source-grounded slide content; illustrative values are explicitly marked.
const slides = [];
const spec = 'docs/eagle_architecture_spec.md';
function page(title, body, notes, sources, extra = {}) {
  slides.push({title, body, notes, sources, ...extra});
}
function tab(title, table, notes, sources, extra = {}) {
  slides.push({title, table, notes, sources, ...extra});
}
function flow(title, nodes, edges, notes, sources, extra = {}) {
  slides.push({title, diagram: {nodes, edges}, notes, sources, ...extra});
}
const box = (id, text, x, y, w = 360, h = 100, size = 30) => ({id,text,x,y,w,h,size});

page('EAGLE 完整流程', ['離線演化 MicroRTS Java agent', '三種 Java 產生模式與兩種評估模式', '來源截點 2026-10-21　版本 fcc8b770'],
  'EAGLE 在對戰之前以演化與選配的 LLM 工作改良候選策略。對戰當中執行的是完整 Java agent，沒有即時 LLM 決策。本簡報以目前程式為準，涵蓋所有啟用中的模式。各機制分頁說明，實驗設定範例不等於全域預設。',
  [`${spec}:9-47`, 'docs/architecture/overview.md:1-35'],
  {type:'cover',hero:'策略、Java 與對戰證據的演化迴圈'});

flow('完整搜尋流程', [
  box('config','設定與模型服務',185,240),box('init','初始化第 0 代',655,240),box('eval','產生 Java 與初始評估',1125,240),
  box('variation','刷新情境、選父代與變異',1125,475),box('survive','子代評估、選倖存者',655,475),box('stop','達到停止條件？',185,475),
  box('final','Final Test',185,700),box('output','摘要、譜系與證據檔',655,700)
], [['config','init'],['init','eval'],['eval','variation','bottom','top'],['variation','survive','left','right'],['survive','stop','left','right'],['stop','variation','top','top'],['stop','final','bottom','top'],['final','output']],
  '設定解析後先準備模型端點；framework 模式會在搜尋前建立並凍結 bundle。第 0 代完成評估後才有可供繁殖的族群。每個演化世代先確保父代分數與評估情境有效，再產生與評估固定數量子代，選出下一代並原子保存。未達停止條件就回到下一代，停止後由 experiment orchestrator 執行正式最終測試。',
  [`${spec}:80-160`,'eagle/evolution/search.py:119-270','eagle/experiment.py:355-423'],
  {subtitle:'初始化一次，之後重複世代迴圈',diagramLabels:[{text:'否：下一代',x:580,y:410,w:250},{text:'是',x:250,y:620,w:90}]});

tab('模式設定與獨立的邊界', [
  ['設定軸','可選值','決定的行為'],
  ['Java 產生方式','llm / deterministic_dsl\nframework_slots','LLM 翻譯、DSL 編譯或凍結模板填槽'],
  ['Java 的候選狀態','generated_phenotype\ninherited_genotype','Java 是否也是可繼承的基因成分'],
  ['評估方式','fixed_roster / self_play','固定十對手案例或凍結自我對弈名單'],
  ['Framework 演化','local / llm_coach','本地有限域操作或 LLM 完整 genome 選擇']
], '這些設定軸需分開理解。deterministic_dsl 與 framework_slots 都要求 generated_phenotype 與 reuse_cached，因此只有 llm 可使用 inherited_genotype。framework.evolution_mode 只適用 framework_slots。固定名單採十個案例 lexicase，自我對弈則採 Game Performance 與語意同分處理。',
  [`${spec}:19-47`,`${spec}:700-820`,'eagle/config.py:580-658'], {size:27,widths:[290,492,560]});

tab('候選個體保存的內容', [
  ['模式','演化中的基因','衍生表型與共同證據'],
  ['LLM 預設','策略 DSL＋generation prompt','完整 Java、class tree、分數、失敗狀態'],
  ['LLM 繼承 Java','策略 DSL＋generation prompt\n＋完整 inherited Java','保存生成前 Java 與新產生 Java 的來源'],
  ['Deterministic DSL','完整策略 DSL','版本化編譯器的 Java 與 hash'],
  ['Framework slots','完整 control_genome','凍結 bundle＋槽值渲染的 Java']
], '每個候選人另有唯一 ID、出生世代、直接父代、各成分來源、操作類型、驗證與編譯結果、對戰紀錄與時間。generation-qualified ID 只用於定位，讀取歷史資料時不重新命名。基因、用於生成的輸入與執行表型各自保存，避免把評估輸出覆寫回基因。',
  [`${spec}:19-47`,'eagle/candidate.py:1-190','docs/architecture/candidate_model.md:1-105'], {size:27,widths:[290,492,560]});

flow('實驗啟動與信任檢查', [
  box('yaml','YAML、seed 與路徑',185,250),box('valid','解析並驗證設定',655,250),box('runtime','準備固定模型端點',1125,250),
  box('bundle','Framework：載入或 bootstrap',1125,490,360,125,28),box('freeze','凍結設定與 bundle 身分',655,490,360,125,28),box('g0','建立初始族群',185,490,360,125)
], [['yaml','valid'],['valid','runtime'],['runtime','bundle','bottom','top'],['bundle','freeze','left','right'],['freeze','g0','left','right']],
  '只在 framework_slots 執行 bundle 步驟，其他模式直接進入初始族群。所有啟用的模型端點先通過有界 chat preflight。受管本地服務需要 CUDA 與完整 GPU offload；不符合時明確失敗。外部服務由使用者預先啟動，EAGLE 不採用或停止該程序。',
  ['eagle/experiment.py:355-423',`${spec}:132-160`,'docs/architecture/framework_slots.md:113-157'],
  {subtitle:'Framework 步驟僅在 framework_slots 模式執行',foot:'Preflight 或 bootstrap 失敗會留下證據，尚未開始正常演化'});

tab('LLM 角色與固定服務', [
  ['角色','綁定的服務','主要輸入與輸出'],
  ['初始策略、賽評與 Coach','model','策略／對戰證據，輸出策略或完整 genome'],
  ['Code gate 診斷','model','來源 policy 與 Java，輸出忠實度／正確性診斷'],
  ['Prompt Reviewer／Rewriter','model','Java 與 API 診斷，輸出 reusable-rule delta'],
  ['Java 生成、修正與編譯修復','generation_model\n省略時共用 model','基因與約束，輸出完整 Java'],
  ['Framework bootstrap','bootstrap backend','design_brief，輸出 bundle；搜尋前執行']
], '不同模型使用各自固定的 server host/port，不再於階段之間切換模型。model 與 generation_model 各可加一個依序設定的外部 endpoint。canonical task index 決定使用哪個 endpoint，重試固定留在原路由，沒有跨端點自動故障切換。framework 模式的 Java 產生在本地完成，因此不呼叫 generation_model。',
  [`${spec}:132-157`,`${spec}:334-350`,'docs/operations/running_eagle.md:198-256'],{size:26,widths:[400,380,562]});

flow('相依關係驅動的串流執行', [
  box('gate','來源檢查\n2 個有界 worker',185,285,360,120),box('prepare','每個子代反思、生成與編譯\n2 個 preparation worker',655,285,360,120,28),box('match','就緒候選進入對戰\n1 個矩陣、10 個 match worker',1125,285,360,120,28),
  box('ordered','依固定 candidate 順序收結果',1125,555,360,115,28),box('commit','AOS、選擇、pool 更新\n與世代原子保存',655,555,360,115,28),box('next','下一世代',185,555,360,115)
], [['gate','prepare'],['prepare','match'],['match','ordered','bottom','top'],['ordered','commit','left','right'],['commit','next','left','right']],
  '後面的候選可在前一位對戰時繼續來源檢查與準備。任一 normalized server origin 的所有角色共用兩個 active request slots，不同 origin 可獨立工作。輸入 ordinal、seed 與路由不隨完成速度改變。父代分數刷新必須先於繁殖；AOS、倖存者選擇、pool 更新、checkpoint 與清理仍等待所需評估完成。中斷時取消排隊工作並等待正在執行的 worker 收尾。圖示為排程機制，沒有實測加速幅度。',
  [`${spec}:132-160`,'eagle/evaluation/pipeline.py:57-340','eagle/execution.py:14-68'],
  {foot:'固定模型端點與固定輸入順序，允許有相依關係的工作安全重疊'});

tab('第 0 代的建立方式', [
  ['分支','初始族群','Java 來源'],
  ['LLM 預設 phenotype','每個 configured seed policy 各一位\n不自動複製補滿人口','checked-in callable no-op seed\n不呼叫 Generator'],
  ['LLM inherited / seeds','單一 policy 複製至 population_size','每位獨立呼叫 Generator'],
  ['llm_generated_policies','保留全部設定 seed policies\n剩餘名額由 LLM 產生並去重','LLM 模式逐位 Generator\nDSL 模式本地編譯'],
  ['DSL / Framework','DSL：設定或 LLM 產生的 policy\nFramework：每槽位一個完整 genome','本地編譯或本地渲染']
], 'LLM inherited configured_seeds 要求一個種子策略，每個候選以相同 inherited Java 作為生成上下文。llm_generated_policies 在 inherited 模式因設定限制只有一個 seed；deterministic_dsl 則可保留多個設定 seed，再為剩餘人口產生合法策略。重複回應依候選順序有界重試。此處以初始化程式與 config 驗證為準，較舊概覽的一個 seed 描述只覆蓋 inherited 情況。Framework 的 local 與 llm_coach 都建立 population_size 個候選；前者採樣有限域，後者請模型選完整 genome。第 0 代與後續世代工作量不同，時間應分開解讀。',
  ['eagle/operators/initialization.py:185-250','eagle/config.py:761-791','docs/architecture/framework_slots.md:13-75'], {size:26,widths:[370,532,440]});

page('策略 DSL 的執行語意', [
  'version 固定為 eagle-strategy-dsl-v1，規則依序包含 actor、when、action',
  '先匹配單位與條件，再檢查內建合法動作限制；無法發出動作時繼續後續規則',
  '策略離線轉成 Java；對戰時直接執行 Java，空 rules 代表 idle',
  'LLM 產生的新策略必須通過詞彙與結構驗證，歷史自然語言策略僅供讀取'
], '策略的 actor、when、action 都使用閉合的 MicroRTS 詞彙與可觀察狀態，允許合法策略多樣性。DSL 是基因資料，不是對戰時呼叫 LLM 的文字指令。deterministic_dsl 會經 typed IR 編譯；llm 則要求 Generator 實作同一份 DSL。合法動作守衛與 fallthrough 規則屬於共用語意。',
  [`${spec}:49-78`,'eagle/strategy_dsl.py:1-120','docs/architecture/overview.md:112-127']);

flow('Framework 的一次性建立與凍結', [
  box('brief','未指定 bundle_path\ndesign_brief',185,250,360,120),box('backend','Groq / Mistral / local\n有界 bootstrap',655,250,360,120),box('validate','完整 schema 與 Java 檢查',1125,250,360,120,28),
  box('external','已有 bundle_path\n讀取外部 bundle',185,510,360,120),box('externalcheck','完整 schema 與 Java 檢查',655,510,360,120,28),box('ea','凍結 exact bytes 與 hash\n開始 genome 演化',1125,510,360,120,28)
], [['brief','backend'],['backend','validate'],['validate','ea','bottom','top'],['external','externalcheck'],['externalcheck','ea']],
  '有外部 bundle_path 時直接驗證該檔並凍結 run-owned copy，不再呼叫 bootstrap。沒有時依 backend 建立，預設 Groq，亦支援 Mistral 與 local。原始回應在解析前保存，失敗有界重試。每個 replicate 預設各自 bootstrap；要共用架構必須明確指定同一個 bundle。搜尋期間 Java 模板、槽位 domain 與表達式不變，resume 也不重新設計。',
  ['docs/architecture/framework_slots.md:24-75','docs/architecture/framework_slots.md:113-157',`${spec}:747-820`],
  {foot:'Bootstrap 屬於搜尋啟動階段；EA 只改 control_genome'});

tab('Framework 的有限選項', [
  ['槽位類型','合法值','演化時保存的內容'],
  ['integer','minimum 到 maximum 的 step 格點','一個合法整數'],
  ['number','minimum 到 maximum 的有限格點','一個合法數值'],
  ['expression_choice','bundle 事先宣告的 choices','choice_id；Java expression 保持凍結'],
  ['完整 genome','每個 slot_id 恰好一次','拒絕缺項、未知 key 與越界值']
], '初始設計提示要求至少 24 個非恆定槽位，含至少 6 個 expression_choice 且各有至少 4 個選項，覆蓋經濟、生產、目標、戰鬥、條件與優先順序。這是設計目標，不能保證行為多樣性。候選人只保存槽值或 choice_id，不能生成新的 Java 表達式。相同 bundle、genome 與 materializer 應產生相同 Java bytes。',
  ['docs/architecture/framework_slots.md:24-75','eagle/generation/framework_slots.py:189-340'],{size:28,widths:[290,492,560]});

tab('Framework 的 local 與 llm_coach', [
  ['階段','local','llm_coach'],
  ['初始族群','seeded 有限域採樣','LLM 每位選完整合法 genome'],
  ['交配','逐槽獨立 uniform crossover','同樣逐槽交配並記錄 donor'],
  ['策略突變','至多一個槽位改成另一合法值','最差單場賽評＋Coach\n回傳完整 genome'],
  ['Java 與失敗','本地渲染，沒有 LLM 修復','本地渲染；非法 Coach 回應\n保留原 genome 並標記失敗']
], '兩種政策共享相同凍結 bundle、hash、renderer、下游評估與倖存者規則。llm_coach 回應必須恰好包含 schema_version、framework_bundle_sha256 與完整 control_genome。突變失敗不隨機改寫、不部分套用；初始選擇失敗保留採樣 genome 並在初始化階段標記該候選失敗。兩種模式都不進行 Prompt Reflection、Code gate、Java Generation 或 compile repair。',
  ['docs/architecture/framework_slots.md:13-75','eagle/operators/strategy.py:448-865','eagle/operators/framework_slots.py:1-200'],{size:27,widths:[290,526,526]});

flow('每一個演化世代', [
  box('context','必要時刷新 self-play 情境\n先重評父代',185,245,360,120,28),box('parents','依評估模式選父代',655,245,360,120),box('ops','依 Java 模式交配與突變',1125,245,360,120,28),
  box('evaluate','每個子代產生 Java 並評估',1125,515,360,120,28),box('select','父代＋子代選下一代',655,515,360,120),box('save','更新 pool 與 checkpoint',185,515,360,120,28)
], [['context','parents'],['parents','ops'],['ops','evaluate','bottom','top'],['evaluate','select','left','right'],['select','save','left','right']],
  'LLM 模式在變異前還有每個來源獨立 Code gate，DSL 與 framework 略過此 gate。一般 generation 產生 population_size 個子代。AOS 僅在設定的 adaptive 模式下於子代評估後收 reward。self-play pool 於選擇之後更新，使用所有已評估子代而非只有倖存者。最後原子保存 generation，再更新 manifest。',
  ['eagle/evolution/generation.py:62-285',`${spec}:99-160`],
  {foot:'人口為 10 的例子：10 位父代＋10 位子代，選出 10 位下一代'});

tab('繁殖父代如何選', [
  ['模式','第一父代','第二父代與限制'],
  ['Fixed roster','隨機排列十個案例\n依序留下當案最高分者','獨立 seeded lexicase 抽樣\n可與第一父代相同'],
  ['Self-play','距最高 Game Performance\n不超過 1.0 的頂層中選取','同分層內可優先選與第一父代\n行為距離較遠者'],
  ['共同規則','使用當前已評估族群','root seed 衍生獨立 RNG\n父代選擇不讀 code_quality']
], '繁殖父代用來提供下一批子代的基因。這個抽樣既不是從 opponent pool 挑對手，也不是世代結束時的倖存者選擇。Self-play 的語意距離只在適應度容忍範圍內破同分，不能讓明顯低分候選因新穎而越級。第二父代缺少相容完整行為簽章時保留 seeded fallback。',
  ['eagle/operators/selection.py:23-68','eagle/evolution/offspring.py:101-123'],{size:28,widths:[290,526,526]});

tab('Lexicase 的案例篩選示例', [
  ['候選策略','對手案例 X','對手案例 Y'],
  ['A','90','20'],['B','90','70'],['C','80','95']
], '教學示例只顯示兩個案例，正式固定名單使用十個。若本次案例順序是 X、Y，第一輪保留 A 與 B，第二輪選 B。若順序是 Y、X，第一輪直接選 C。因此某個特定對手的專長可以影響被選機會，不等同於依總分排序。每次重新抽父代或不放回抽倖存者時都產生自己的 seeded 案例順序。',
  ['eagle/operators/selection.py:23-40','eagle/opponent_cases.py:1-60'],
  {example:true,subtitle:'教學示例，非實驗量測',foot:'順序 X、Y 選 B；順序 Y、X 選 C',size:32,widths:[440,451,451]});

tab('交配與來源譜系', [
  ['模式','交配單位','必須保留的來源'],
  ['LLM phenotype','策略與 generation prompt 各自選 A 或 B','strategy_parent_id\ngeneration_prompt_parent_id'],
  ['LLM inherited','再獨立選完整 Java 成分','另保留 java_parent_id 與生成前 Java'],
  ['Deterministic DSL','整個 policy 的複製／交配','完整策略來源；不做 rule 級交配'],
  ['Framework slots','每個 slot 分別選 A 或 B','slot_parent_ids；Coach 另記 evidence parent']
], '直接父代列表與每個成分實際來源是不同資訊，均需保存。兩位父代可以提供不同成分，即使文字或值相同也不能省略來源。Framework 的 Coach 證據父代是 parent A，不會因某槽位從 donor B 繼承就改用 B 的比賽。crossover_rate 控制是否交配，未交配時沿用單一來源。',
  [`${spec}:216-223`,'eagle/operators/crossover.py:1-170','eagle/operators/framework_slots.py:1-155'],{size:27,widths:[330,502,510]});

flow('LLM 模式的交配前 Code gate', [
  box('source','每個被選中的來源\n自己的 policy＋自己的 Java',185,245,360,120,27),box('gate','獨立 Code 診斷',655,245,360,120),box('healthy','健康\n正常交配與 Strategy／Prompt',1125,245,360,120,27),
  box('defect','缺陷\n單一父代 corrective child',655,515,360,120,28),box('failed','診斷失敗\n失敗子代與證據',185,515,360,120,28),box('revise','依診斷修正原 Java\n保留兩個 prompt 基因',1125,515,360,120,28)
], [['source','gate'],['gate','healthy'],['gate','defect','bottom','top'],['gate','failed','left','top'],['defect','revise']],
  '所有實際貢獻來源都必須健康才可進入正常交配與突變。Code v6 只檢查 strategy_fidelity 與 code_correctness；不因勝率、外觀或可簡化而要求修正。ambiguous_strategy 配合正確 Java 不需 revision。有缺陷就產生一位保留原基因的 corrective child，跳過交配與一般突變；診斷失敗也不能當健康通過。Code gate 沒有 AOS 操作機率。DSL 與 framework 模式不執行此 gate。',
  [`${spec}:49-78`,'eagle/operators/code.py:29-180','eagle/evolution/offspring.py:125-280'],
  {foot:'修正 Java 的輸出直接進入 materialization，不再被普通 Generator 覆寫'});

flow('Strategy Reflection 的證據路徑', [
  box('parent','策略來源父代\n或 framework evidence parent',185,245,360,120,27),box('worst','該父代的一場\n最差已完成對戰',655,245,360,120),box('comment','Match Commentator\n分析該場 trace',1125,245,360,120,28),
  box('coach','Coach：全場摘要\n＋該一場診斷',1125,515,360,120),box('valid','驗證新 DSL\n或完整 control_genome',655,515,360,120,28),box('java','離線產生 Java\n再走正常評估',185,515,360,120)
], [['parent','worst'],['worst','comment'],['comment','coach','bottom','top'],['coach','valid','left','right'],['valid','java','left','right']],
  '最差場次只從記錄的策略來源父代中取，不能任意從 child、donor 或整個 run 換一場。Match Commentator 看一場詳細 trace；Coach 同時取得全場 global summary 與此一 diagnosis，以免只看局部比賽。LLM/DSL 模式改 policy，framework llm_coach 則改完整 genome。策略反思失敗保留既有資料並走失敗分支，沒有自動換賽事補救。',
  [`${spec}:248-275`,'eagle/operators/strategy.py:202-447','eagle/operators/strategy.py:576-865','eagle/operators/strategy.py:1222-1308']);

page('最差場次與策略回應的驗證', [
  '優先取最低有限 per-match performance；缺值時以敗 −100、和 0、勝 100 排序',
  '平分用穩定 match_id 排序，排除失敗比賽；trace 不可用時不改選另一場',
  'DSL Coach 以 JSONL 逐行輸出完整規則；保留合法規則的原順序',
  '非法整行規則捨棄並記錄；至少一條合法規則才成功，不修補規則的子樹'
], '每場 performance 包含 shaping，因此同為敗場也能分辨較差表現。JSONL 是 field-targeted 完整規則紀錄，不能把零碎 condition/action 修成另一個沒有被模型完整提出的規則。舊的整份 JSON 回應仍採 all-or-nothing 驗證。framework Coach 使用另一份完整 genome schema，不能套用 DSL 的合法子集合邏輯。',
  [`${spec}:248-275`,'eagle/operators/strategy.py:1222-1308','eagle/operators/strategy.py:1638-1710']);

flow('Prompt Reflection 的資料邊界', [
  box('evidence','Policy＋可編輯 Java 區域\n＋對應 compiler／validation',185,265,360,140,27),box('review','Prompt Reviewer\n分析翻譯實作問題',655,265,360,140),box('rewrite','Prompt Rewriter\n產生 reusable-rule delta',1125,265,360,140,28),
  box('gene','僅更新 generation_prompt',1125,560,360,110,28),box('generator','普通 Java Generator',655,560,360,110),box('eval','驗證與對戰評估',185,560,360,110)
], [['evidence','review'],['review','rewrite'],['rewrite','gene','bottom','top'],['gene','generator','left','right'],['generator','eval','left','right']],
  'Prompt Reflection 改良的是可重用的 policy-to-Java 翻譯規則。Reviewer 不接收勝敗、fitness、對手分數、比賽 trace 或其他 gameplay evidence。預設模式比較來源父代的 policy 與 Java；inherited 模式比較 child 選中的 policy 與 inherited Java。新 prompt 不直接修改策略基因，最後仍由 Generator 生成 Java。只在 llm materialization 啟用。',
  [`${spec}:277-309`,'eagle/operators/prompt.py:268-525'],
  {foot:'Strategy Reflection 改「策略」；Prompt Reflection 改「如何把策略翻成 Java」'});

tab('三條 Java 產生路徑', [
  ['路徑','輸入與處理','成功輸出與失敗政策'],
  ['LLM','策略＋generation prompt\n＋選配 inherited Java','完整 Java；允許有界 validation／compile 修復'],
  ['Deterministic DSL','Canonical DSL 經 typed IR 編譯','完整 Java；編譯器或 javac 失敗即終止'],
  ['Framework slots','凍結 template＋完整 control_genome','完整 Java；渲染失敗即終止'],
  ['共同下游','Validation、javac、Integration\nMicroRTS；語意 probe 可選配','Self-play 必須啟用 probe\n成功的 source／classes 才可對戰']
], 'LLM 回應必須先滿足完整檔案的 package、class、建構子、lifecycle 與單一 strategy-marker 區域等外框，再以固定 scaffold 加上抽出的策略區域建立 normalized Java。固定區域中的模型改動保留為證據，但不進表型。結構非法的回應不能靠 normalization 變成合法。確定性兩條路徑沒有 LLM fallback。',
  [`${spec}:313-405`,`${spec}:700-820`,'eagle/evaluation/decoding.py:1-130'],{size:27,widths:[300,512,530]});

flow('LLM 生成與有界修復', [
  box('input','權威基因與固定 scaffold',185,250),box('response','完整 Java 回應與抽取',655,250),box('check','外框檢查、normalize\nValidation＋javac',1125,250,360,120,28),
  box('repair','前次完整 Java＋該次診斷\n保持策略與基因不變',655,535,360,120,27),box('failure','耗盡 attempts\n標記最後失敗階段',185,535,360,120,28),box('success','第一份成功的 source／classes\n提升為唯一 canonical 表型',1125,535,360,120,26)
], [['input','response'],['response','check'],['check','success','bottom','top'],['check','repair','left','top'],['repair','response','top','bottom'],['repair','failure','left','right']],
  'attempt 1 通常是普通生成，corrective child 則直接使用 Code Reflection 已回傳的完整 Java。完整 source 的驗證或編譯失敗可在 generation_max_attempts 內用專門 compile-repair prompt 修復。每次 request、raw response、抽取 source、normalized source 與 hash 都保存。第一個 validation＋compilation 成功即停止；Integration 或 runtime 失敗不回到 decoder。',
  [`${spec}:350-405`,'eagle/evaluation/decoding.py:1-160'],
  {foot:'圖中的重試僅適用 llm；Integration／runtime 失敗不觸發 compile repair'});

page('Validation、編譯與七項 Integration', [
  'Validation：package、CandidateAgent 外框、固定 scaffold、策略 marker 與 API 安全限制',
  'javac：每個 attempt 最多編譯一次，成功 class tree 直接提升，不重複編譯',
  'Integration：載入、繼承、建構子、reset、clone、getAction、有效 PlayerAction',
  'getAction 在真實 8×8 地圖、雙方位置、獨立狀態驗證動作與一個 cycle'
], 'Java contract 同時限制 network、process execution、未授權 I/O 與 runtime modification；它不是一般用途 Java sandbox。編譯保留結構化去重診斷與 warning。Integration 前置檢查失敗會阻擋後面的檢查與對戰。獨立實例檢查確保 getAction 與 PlayerAction 在有單位的真實地圖可運作，成功仍不能證明所有對戰情境都正確。',
  [`${spec}:378-424`,'eagle/generation/java_agent_generator.py:256-329','eagle/evaluation/microrts_runner.py:1-140']);

tab('搜尋評估的 180 場矩陣', [
  ['維度','數量','意義'],
  ['對手欄位','10','固定名單或凍結 self-play 名單'],
  ['地圖','3','可設定每張 tick_limit'],
  ['回合與位置','3 × 2','不同 round_index，候選分別在 p0／p1'],
  ['每個候選總場數','10 × 3 × 3 × 2 = 180','同一份 Java 與 classes 跑完整矩陣']
], '只有通過 materialization、validation、compilation 與 Integration 的候選才能進入對戰。每場有獨立衍生 seed、地圖、回合、位置與 timeout。每個對手欄位 18 場，矩陣依 canonical order 聚合。每張地圖 tick cap 會沿用到普通評估、AOS head-to-head 與 final test。候選的矩陣必須完整才有有效 fitness。',
  [`${spec}:425-459`,'eagle/evaluation/match_matrix.py:1-180','eagle/evaluation/matches.py:1-125'],{size:29,widths:[330,400,612]});

page('Game Performance 與分數彙總', [
  '單場分數＝結果分數＋bounded shaping；勝 +100、和 0、敗 −100',
  'Shaping 合併物資、終局資源與存活時間，總範圍限制在 [−10, +10]',
  'Fixed roster：十個對手分數各為一個案例；0.5／1／2 加權均分只用於報表',
  'Self-play：十個欄位等權平均，game_performance 是唯一演化目標'
], '固定名單的三個弱基準各權重 0.5，三個 Rush 各 1，四個保護級對手各 2，總分母 12.5。這個報表加權平均不替代 lexicase 的十個分量。self-play 各欄位等權平均，語意只在同分範圍內輔助選擇。任一 required stage 失敗或矩陣未完成，fitness 使用 −1000 sentinel，部分對戰仍保留。AllInBot 被 adapter containment 的上游故障以中性零分和局記錄並另列 opponent fault。',
  ['docs/evaluation/game_performance.md:1-57','eagle/evaluation/game_performance.py:207-219','eagle/opponent_cases.py:22-70',`${spec}:451-459`]);

tab('Fixed roster 的十個對手', [
  ['對手群','完整名單','報表權重'],
  ['基礎基準','PassiveAI、RandomAI、RandomBiasedAI','每個 0.5'],
  ['Rush 基準','LightRush、HeavyRush、WorkerRush','每個 1'],
  ['進階基準','AllInBot、Mayari、COAC、TMA','每個 2'],
  ['演化用目標','每個對手的 18 場平均各成一個案例','十案例 lexicase']
], '對手名單由 SEARCH_OPPONENT_REGISTRY 定義，普通 fixed_roster 評估沒有從歷代策略抽換對手。進階基準權重只影響 Game Performance 報表代表，不讓它在 lexicase 過濾時自動重複或加權。Self-play 起始同樣使用這十個內建來源，但後續採另一個 pool 維護與快照抽樣機制。',
  [`${spec}:433-459`,'eagle/opponents.py:1-145','eagle/opponent_cases.py:22-70'],{size:29,widths:[290,752,300]});

tab('Self-play Opponent Pool 的起始與容量', [
  ['成員區域','起始內容','後續規則'],
  ['永久保護 4 個','AllInBot、Mayari、COAC、TMA','不參加 pool 挑戰賽、不被替換'],
  ['可替換基準 6 個','Passive、Random、RandomBiased\nLightRush、HeavyRush\nWorkerRush','可作為守擂者被挑戰'],
  ['歷代入池策略','初始時尚無生成候選成員','跨代累積；滿額後挑戰替換'],
  ['容量','預設總容量 50，最少 10','包含 4 個保護成員']
], '長期 opponent pool 與每次凍結的十個評估欄位分開保存。Pool 初始是所有十個內建對手，之後納入合法且新穎的歷代候選策略。它不是只存當代十個策略，也不是只收歷代冠軍。總容量 50 是設定預設，不代表每次評估要跑五十個對手。',
  [`${spec}:461-481`,'eagle/opponent_pool.py:22-35','eagle/opponent_pool.py:162-219'],{size:26,widths:[300,522,520]});

flow('新策略的來源與入池挑戰', [
  box('new','第 0 代初始族群\n＋後續每代已評估子代',185,245,360,120,28),box('eligible','可執行、完整評估、去重\nID／source／語意表型',655,245,360,120,27),box('room','未滿：直接加入 pool',1125,245,360,120,28),
  box('full','已滿：seeded 抽 1 個\n非保護守擂者',655,525,360,120,28),box('duel','18 場挑戰賽\n3 地圖 × 3 回合 × 2 邊',1125,525,360,120,27),box('promote','完整、無錯誤且勝場 > 敗場\n才替換守擂者',185,525,360,120,26)
], [['new','eligible'],['eligible','room'],['eligible','full','bottom','top'],['full','duel'],['duel','promote','bottom','bottom']],
  '第 0 代 update_pool 接收 evaluated_population，後續每代接收 evaluated_offspring，並非只傳下一代倖存者。候選須通過可執行與完整評估條件，去除 ID、source 或 semantic phenotype 的重複項。滿池時每個 novel entrant 對一個 seeded 守擂者跑完 18 場；勝和敗分別計 1、0.5、0，只有 wins > losses 才 promotion，平手保留守擂者。失敗或未完成保留證據但不能晉級。',
  ['eagle/evolution/search.py:208-219','eagle/evolution/generation.py:254-262','eagle/opponent_pool.py:162-219','eagle/opponent_pool.py:400-430'],
  {foot:'入池資格不要求先成為倖存者；pool 的成功入池成員可留到後續世代'});

tab('凍結的十個評估對手', [
  ['使用期間','固定成分','六個變動欄位'],
  ['第 0 代','保護 4 個','其餘 6 個內建基準'],
  ['第 1–5 代','同樣保護 4 個','第 1 代從非保護 pool seeded 抽 6 個'],
  ['第 6–10 代','同樣保護 4 個','第 6 代刷新後維持不變'],
  ['之後每 5 代','依設定 refresh_interval','第 11、16…代再取新快照']
], '這裡的十個是評估對手欄位，不是當代子代人口數。刷新預設 interval 5，第 1 代即刷新，之後第 6、11、16 代。Pool 在世代結束可以更新，但已凍結 context 不立即跟著改變。新入池策略要等後續快照刷新才可能被抽到。四保護 case IDs 固定，六個動態 diagnostic slots 為 self_play_000 到 self_play_005，來源寫在 context rows。',
  [`${spec}:482-511`,'eagle/opponent_pool.py:136-159','eagle/self_play.py:24-79'],{size:28,widths:[300,340,702]});

flow('對手快照刷新與父代重評', [
  box('refresh','到達 self-play 刷新邊界',185,275),box('snapshot','凍結 4＋6 名單\n保存 context hash',655,275,360,120),box('replica','父代保留 phenotype\n建立新 ID 複本',1125,275,360,120,28),
  box('score','以新情境重跑父代評估',1125,555,360,110,28),box('offspring','再選繁殖父代與產生子代',655,555,360,110,28),box('same','同一 context 下選下一代',185,555,360,110,28)
], [['refresh','snapshot'],['snapshot','replica'],['replica','score','bottom','top'],['score','offspring','left','right'],['offspring','same','left','right']],
  '平常 reuse_cached 保留父代 Java 與分數，但 self-play 評估對手變更是必要例外。刷新時 Java 表型不重生，透過新 ID 複本保存重評結果，避免覆寫舊情境的證據。父代分數是繁殖選擇的輸入，所以刷新評估必須先完成。新舊 context 的分數不能直接混入同一選擇池；context 與 runtime/map 身分也用於快取與 resume 驗證。',
  ['eagle/evolution/generation.py:94-170',`${spec}:493-511`,'eagle/evolution/parent_refresh.py:1-160'],
  {foot:'不能把不同對手名單下的 search fitness 直接當作跨世代改進'});

tab('父代重用與兩種重評情境', [
  ['情境','Java 是否重生','選擇使用的候選'],
  ['reuse_cached，正式預設','保留既有 Java 與 classes','一般世代沿用既有父代評估'],
  ['Self-play 對手快照刷新','保留 phenotype，新 ID 重評','同一新 context 的父代複本＋子代'],
  ['regenerate_same_genotype','基因不變，但重新 Generator 與評估','僅限 inherited Java＋static\n用新父代複本＋子代，排除舊 ID']
], '第三列的 self-play refresh 是正常協定的一部分。第四列是明確的非正式診斷處理，將同一基因重新 materialize，因此同時量到 Java 再生成與對戰重新抽樣的總效應，不能視為只改變一個 selection 選項。舊父代 artifacts 不被覆寫，sidecar 保存來源與新複本 hash、評估和是否倖存。Deterministic DSL 與 framework_slots 不允許這個診斷模式。',
  [`${spec}:124-140`,'eagle/evolution/parent_refresh.py:1-160','docs/architecture/evolutionary_flow.md:75-91'],{size:26,widths:[390,432,520]});

tab('語意探針與同分處理', [
  ['資料','實際取得的內容','用途'],
  ['Probe dataset','3 地圖 × 3 階段，共 9 個固定狀態','讓同一 agent 回答一組可重現狀態'],
  ['Action signature','各 probe 的完整動作與 hash\n再保存 global hash','精確辨識行為是否相同'],
  ['Parent tie','同一 Game Performance 頂層','第二父代可最大化與第一父代距離'],
  ['Survivor tie','只在分數層的邊界需要淘汰時','seeded max-min 距離選子集合']
], '語意距離來自實際 Java 在固定 map×phase states 的動作，不是 LLM 的文字評分，也不是 code_quality。Dataset、probe 順序與 action hash 必須相容才比較。只在 inclusive 1.0 score tier 內破同分，不形成額外演化目標。精確相同行為可協助 pool 去重與離線等價類分析。探針開關與相關限制依設定驗證。',
  [`${spec}:523-551`,'eagle/operators/selection.py:42-68','eagle/operators/selection.py:174-215','docs/architecture/overview.md:173-188'],{size:27,widths:[300,522,520]});

tab('倖存者選擇與固定人口', [
  ['步驟','Fixed roster','Self-play'],
  ['候選集合','父代與子代聯集，依 ID 去重','同一 context 的父代與子代聯集'],
  ['有效資格','只用完整評估的候選填人口','相同；失敗者保留診斷'],
  ['選擇方式','重複 lexicase，選出者移除','由高到低建立非串連的分數層'],
  ['邊界與不足','選滿 population_size、不放回\n完成者不足就明確失敗','切分同分層才用語意 max-min\n年齡不破同分']
], '一般情況下父代與子代各 N，從 2N 中選 N，是 mu_plus_lambda。若所有子代失敗但仍有 N 位完成評估的父代，父代可以完整留下。Self-play 每層用剩餘者當前最高分作錨點，差距不超過 1.0 的人屬同一層；不以相鄰分數一路串接。例：100、99.2、98.4 只把前兩者歸在第一層。這個例子只解釋分層規則，不是實驗結果。',
  ['eagle/operators/selection.py:70-145','eagle/operators/selection.py:174-225',`${spec}:119-130`],{size:27,widths:[300,521,521]});

tab('反思操作的 static 與 AOS', [
  ['模式','Reward 來源','額外工作與限制'],
  ['static','固定 Strategy／Prompt 機率','不計 reward；framework 與 self-play 使用此模式'],
  ['aos_opponent','雙方可執行時比較十對手 rank\n否則先按執行狀態給 reward','不加對戰；只適用固定名單'],
  ['aos_head2head','mutation evidence parent 對 offspring','雙方可執行才加 18 場\n失敗時跳過，改用執行狀態 reward'],
  ['共用 updater','EMA α = 0.20\nprobability matching＋最低機率','更新操作選擇；Code gate 不計 AOS credit']
], 'AOS 比較父代依 mutation context 的實際成分來源決定：Strategy 用 strategy_parent_id；預設 Prompt 用 generation_prompt_parent_id；inherited Prompt 用 java_parent_id。它不是直接父代列表的固定第一位。Opponent reward 是 execution-first：修復可執行性、破壞可執行性與雙方失敗各有對應分支，雙方成功才比較 rank。Head-to-head 只在 child 與比較父代都可執行時加 18 場；其分數不加入搜尋 fitness 或 final test，不能執行時走對應 reward。兩種 adaptive 模式都只改未來操作機率，不改 fitness 契約。',
  [`${spec}:224-247`,'eagle/operators/adaptive.py:410-442','eagle/operators/adaptive.py:730-833'],{size:26,widths:[300,522,520]});

tab('失敗、重試與停止的邊界', [
  ['發生位置','允許的處理','留下的結果'],
  ['Bootstrap／LLM 回應','各自 attempts 內重試，原始回應先保存','失敗 manifest 或候選失敗與診斷'],
  ['LLM validation／compile','在 generation_max_attempts 內修復','最後 attempt 決定失敗階段'],
  ['DSL／Framework 或 Integration','終止該候選，不回到 LLM 修 Java','保留既有基因與失敗證據'],
  ['Runtime／矩陣／選擇','未完成矩陣無有效 fitness\n不足有效人口則終止 run','−1000 sentinel、部分對戰、可恢復 checkpoint']
], '失敗分類包括初始化、反思、生成、驗證、編譯、Integration 與 runtime 等。候選失敗與 run 失敗需分開：只要完成的父代與子代足夠，下一代仍可成立。程序中斷會取消排隊工作、drain active worker，保留未完成證據後從最後完成世代恢復。Pipeline 安全邊界不能以看起來可執行的 fallback 代替。',
  [`${spec}:350-424`,'docs/evaluation/game_performance.md:33-40','eagle/operators/selection.py:99-123'],{size:26,widths:[360,502,480]});

tab('每個 run 的保存與稽核', [
  ['位置','主要內容','支持的追查'],
  ['config.yaml\nmanifest.json','resolved config、狀態\n與 latest_generation','知道實際設定與完成邊界'],
  ['generations/\ncandidates/','族群快照、基因、譜系\nLLM 與評估證據','重建每個成分如何產生與被選'],
  ['framework/\narchives/','凍結 bundle、pool、context\n與未提交工作的封存','恢復架構與對手情境'],
  ['timing.jsonl\nfinal_test/','時間事件、對戰結果與最終測試','區分各階段成本與獨立 benchmark']
], 'Generation snapshot 先原子寫成功，再更新 manifest.latest_generation。只有 manifest 指定的完成快照作為 resume 起點，不能因資料夾有較新檔就推論已提交世代。每次 LLM request 的 endpoint/model、prompt、raw response、attempt、hash 與 timing 都屬證據；秘密憑證不可寫入。compact artifact 模式省去 XML replay，但保留需要的 trace 與對戰摘要。',
  ['eagle/run_artifacts.py:160-197','eagle/run_artifacts.py:363-375','docs/artifacts/artifact_schema.md:37-92',`${spec}:567-629`],{size:27,widths:[380,492,470]});

flow('中斷後的恢復流程', [
  box('manifest','讀 manifest 的最後完成世代',185,260,360,120,28),box('identity','檢查 protocol、config\nbundle／runtime／map identity',655,260,360,120,27),box('archive','保留未提交工作\ninterrupted_work/',1125,260,360,120,27),
  box('restore','還原族群、pool 與 context\n操作狀態、archive 與停滯計數',1125,545,360,120,26),box('replay','用穩定 ID 與 seed 重播\n未完成世代',655,545,360,120,28),box('continue','繼續演化與 Final Test',185,545,360,120,28)
], [['manifest','identity'],['identity','archive'],['archive','restore','bottom','top'],['restore','replay','left','right'],['replay','continue','left','right']],
  'Resume 不是繼續使用任意半成品，也不重新 bootstrap。先檢查目前版本與凍結身分能否相容；protocol、bundle hash、framework evolution mode 或 runtime/map 身分不合時拒絕。未提交候選與 LLM 證據先移入 interrupted_work，保留後再以穩定 ID 重播。這維持可追查性，但外部 LLM 回應與 wall-clock timeout 仍可能讓重播結果不同。',
  ['eagle/evolution/resume.py:1-150','eagle/run_artifacts.py:686-703',`${spec}:162-215`,'docs/architecture/framework_slots.md:140-149']);

tab('多組設定、replicate 與資料夾續跑', [
  ['層級','排程方式','恢復判斷'],
  ['設定資料夾','依 YAML 檔名排序，逐組執行','experiment.yaml 記每組 run slots'],
  ['明確 seeds','random_seeds: [7,8,9]，runs: 2','依序排 7,7,8,8,9,9'],
  ['每個 replicate','獨立 run 目錄與 resolved config','未完成優先；已完成可跳過'],
  ['完成條件','完整 EA manifest；正式 run 還需 Final Test','可恢復中斷、補 final test\n未提交 G0 可建立替代 run']
], '明確 random_seeds 時 runs 是每個 seed 的重複次數。省略 random_seeds 則沿用 random_seed、random_seed+1 的歷史排程。Index 保存有序的 absolute run paths，每個 slot 都檢查 seed 與 config 身分。Framework fresh replicate 預設各自生成 bundle，若研究需控制架構差異，必須指定相同外部 bundle。Folder rerun 會處理未開始、未完成與缺 final test 的不同情況。',
  ['eagle/config.py:863-879','eagle/experiment.py:355-540','docs/artifacts/artifact_schema.md:491-529'],{size:27,widths:[300,502,540]});

page('可重現性與相同版本續跑', [
  'Root random_seed 衍生初始化、選擇、操作、LLM request 與每場 JVM seed',
  'Seed 與 endpoint 由固定 task identity／index 決定，不依 thread 或完成順序',
  '保存 source、bundle、runtime、map 與 request／response hashes 以核對身分',
  '相同輸出才有相同軌跡；外部模型、GPU kernel、私有 RNG 與時間上限仍有變異'
], '執行總是對可控制的隨機性設 seed，沒有另一個 deterministic_mode 開關。模型 provider 可能忽略 seed 或更新權重；GPU batching、浮點數、第三方對手二進位與 wall-clock 搜尋都可能改變結果。Deterministic materialization 的 byte-identical Java 契約不等於整場實驗逐位元相同。重現承諾需限定同程式、資料、設定與確定的 task outputs。',
  [`${spec}:162-215`,'eagle/evaluation/determinism.py:1-170','eagle/execution.py:14-68']);

flow('停止條件與正式 Final Test', [
  box('stop','generations 上限\n或 stagnation 條件',185,250,360,120),box('represent','選可執行代表策略\n保留原 canonical Java',655,250,360,120,28),box('recompile','獨立 recompile\n再執行七項 Integration',1125,250,360,120,28),
  box('matrix','10 對手 × 3 地圖\n× 每邊 10 場 × 2 邊',1125,530,360,120),box('result','600 場結果\nW／L／D／E 與分數',655,530,360,120),box('finish','輸出 JSON／CSV／Markdown\n完成 run 交付',185,530,360,120,27)
], [['stop','represent'],['represent','recompile'],['recompile','matrix','bottom','top'],['matrix','result','left','right'],['result','finish','left','right']],
  'generations=20 包括 G0 初始化後的演化世代 1 到 20。stagnation 依 active selection-state signature 判斷，不是只看平均分數。正式 experiment run 在 EA 完成後執行 Final Test；mock 或 skip-final-test 可略過。Final Test 使用固定十內建對手與獨立 classes；明確 candidate-id 不可自動替代，預設末代無可執行策略才搜尋較新的已完成世代代表。',
  ['eagle/final_test.py:1-125','docs/evaluation/evaluation_pipeline.md:152-158','eagle/experiment.py:409-423','docs/operations/running_eagle.md:258-268'],
  {foot:'搜尋每位 180 場；pool 挑戰 18 場；正式最終測試 600 場'});

tab('跨世代的公平比較', [
  ['項目','Search fitness','固定跨世代 benchmark'],
  ['對手情境','Self-play 隨快照刷新','所有代表使用同一固定 protocol'],
  ['代表選擇','用於當代演化選擇','各指定快照內最高有限 GP 的 runnable survivor'],
  ['測試規模','每位 180 場','每個代表各 600 場'],
  ['Seed 與輸出','候選與對手身分衍生','paired seeds 不依候選 ID／出生代\nfixed_evaluation/ 與搜尋證據分開']
], 'python -m eagle.fixed_evaluation 只讀取 completed run 的明確指定世代，不缺代替代、不用 run-wide best 取代 snapshot 代表。每位代表重編與 Integration，不呼叫 LLM。protocol 記錄對手、地圖 hash、tick cap、scoring 與 runtime source identity。缺場或錯誤矩陣的 aggregate score 與 win rate 為 null 並 nonzero exit。mean_match_score 是不加權 benchmark 平均，不能直接當搜尋 fitness。',
  ['docs/evaluation/evaluation_pipeline.md:160-166','eagle/fixed_evaluation.py:1-170'],{size:27,widths:[300,442,600]});

page('結果、時間與比較的解讀', [
  '依 generation snapshot 檢視倖存者軌跡，另保留 birth_generation 與逐場分佈',
  '總 wall time、初始化與已完成演化世代分開報；stage sums 可能因重疊大於 wall time',
  '比較策略能力先固定 benchmark；比較速度另控制模型、硬體、seed、工作量與失敗比例',
  '目前沒有多主機 live speedup benchmark；不能由串流排程設計推論已加速多少'
], '時間來源以已提交 generation timing 與 run records 為準，不能將 partial terminal output 當單代耗時。當對手情境改變，search fitness 的跨代上升並不能單獨證明一般化能力。比較現行多主機串流與先前排程時，需要相同模型、硬體、seed、候選規模與失敗條件下的獨立速度實驗。實作文件尚無這組 live benchmark，不能報出加速比。',
  ['docs/evaluation/game_performance.md:42-57','docs/artifacts/timing_schema.md:1-65','docs/implementation/current_status.md:21-34']);

tab('GUI、監看與離線分析', [
  ['工具','支援工作','與搜尋狀態的關係'],
  ['eagle gui','設定選項、YAML、啟停、resume\n瀏覽族群與視覺對戰','啟動前凍結 launch snapshot'],
  ['eagle monitor','原子狀態、PID／liveness、資源與失敗摘要','唯讀；異常結束與正常完成分開'],
  ['eagle analyze','各對手分數、勝率、單場分佈與 AOS 圖表','由保存的快照與證據產生'],
  ['analyze --semantics','探針表、唯一性與精確等價類','讀既有 wrapper／cache，不重跑 agent']
], 'GUI 提供 config parsing 支持的固定選項，儲存前驗證並原子寫入，觀察比賽不改變 fitness。Monitor 從 manifest 和最新已提交 generation 讀取，不控制實驗。離線分析的 generation 指倖存快照世代，birth_generation 才是候選出生時間。使用者可以從這些工具回查分數、行為與 LLM evidence，無需改動 canonical search artifacts。',
  ['docs/implementation/current_status.md:42-66','docs/architecture/evolutionary_flow.md:169-200','eagle/analysis/report.py:1-130'],{size:27,widths:[300,592,450]});

tab('目前 Framework Coach 設定範例', [
  ['項目','configs/framework_coach.yaml 的值','意義'],
  ['架構與演化','framework_slots＋llm_coach\nMistral bootstrap','一次建立框架，之後選完整槽值'],
  ['搜尋預算','20 generations，population 10\nruns 1，seed 8','G0 之後最多 20 個演化世代'],
  ['評估與 pool','self_play，refresh 5，capacity 50','固定四保護與抽樣六對手'],
  ['操作與對戰','crossover 0.75，mutation 1.0\n地圖 tick caps 1500／3000／4000','全部採 Strategy 路徑；數值屬範例設定']
], '這頁是目前 checked-in config 的具體範例，不是所有模式的預設。頂層 model 為 Qwen 3.5-9B，含本地 managed primary 與一個外部 additional endpoint；機器路徑與位址需配合實際環境。bootstrap_backend 為 mistral、framework.model 為 mistral-small-latest。此配置示範完整流程的實際連接，並不宣稱本次已啟動或完成這組實驗。',
  ['configs/framework_coach.yaml:1-98','eagle/config.py:580-658'],{size:27,widths:[300,542,500]});

export default {revision:'fcc8b770',date:'2026-10-21',slides};
