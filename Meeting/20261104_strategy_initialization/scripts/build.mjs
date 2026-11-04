import fs from 'node:fs/promises';
import {Presentation,PresentationFile} from '@oai/artifact-tool';
const root='D:/Project/EAGLE/Meeting/20261104_strategy_initialization';
const bundle=JSON.parse(await fs.readFile('D:/Project/EAGLE/configs/framework_bundles/gpt_finite_rule_market_v1/bundle.json','utf8'));
const p=Presentation.create({slideSize:{width:1672,height:941}});
const C={ink:'#423C3B',wine:'#47171C',blush:'#DEB4BA',paper:'#FCF8F5'};const font='Source Han Serif TW';
function text(s,t,x,y,w,h,size=28,bold=false,color=C.ink){const a=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});a.text=t;a.text.style={fontSize:size,typeface:font,color,bold,insets:0,verticalAlignment:'middle',wrap:'square',autoFit:'none'};return a;}
function page(title,sub){const s=p.slides.add();s.background.fill=C.paper;text(s,title,64,36,1544,82,47,true,C.wine);text(s,sub,66,125,1530,52,27,false,'#877675');s.speakerNotes.text='來源（2026-11-04 查閱）：eagle/candidate.py；configs/framework_bundles/gpt_finite_rule_market_v1/bundle.json；configs/experiments/1030_gpt_framework_slot_ablation_seed8_10/03_gpt_framework_gpt_seed_local_evolution.yaml；eagle/operators/framework_coach.py；eagle/generation/framework_slots.py；prompts/framework_initial_selection.txt、framework_coach_selection.txt、framework_option_selection.txt。框架 SHA-256: f674a580f0db088bd3436232d2dd36d071a231c9886f480a7aaed25669203e2b。24 個 slot 僅指本章 1030 實驗框架，不代表所有框架的固定大小。';return s;}
function foot(s,t){text(s,t,66,844,1535,52,22);}
function table(s,rows,widths,y,h,size=27){const tb=s.tables.add({rows:rows.length,columns:rows[0].length,left:66,top:y,width:1540,height:h,columnWidths:widths,values:rows});tb.borders.assign({fill:'#E8D8D9',width:1,style:'solid'});for(let r=0;r<rows.length;r++)for(let c=0;c<rows[0].length;c++){const cell=tb.getCell(r,c);cell.fill=r===0?C.blush:C.paper;cell.text.style={typeface:font,fontSize:size,color:C.ink,bold:r===0,insets:9};}return tb;}

let s=page('策略描述引導的初始族群','新模式 llm_plus_authored：1 個 LLM 策略＋9 個既有策略，共 10 個個體');
s.speakerNotes.text='設計來源：使用者 2026-11-04 指示。既有策略來源：prompts/framework_initial_strategies.txt 第2–10條。實作來源：eagle/evolution/framework_reflection.py；eagle/operators/initialization.py；configs/experiments/1104_description_guided/experiment.yaml。此新增模式不代表後續1030歷史結果使用這項初始化。現有描述保存欄位為 Candidate.strategy_description；執行基因為 control_genome。';
table(s,[['階段','個體持有的資料','LLM 的工作'],['1  建立策略描述','Index 0：LLM 生成一個自然語言新策略\nIndex 1–9：沿用既有九種策略描述','先產生新策略描述，\n再進行 slot 選值'],['2  依描述填入基因','每個個體保存 strategy_description\n與一組完整 control_genome','參考該個體的描述、框架報告、\nslot 用途與合法值域，填完所有 slots'],['3  驗證與執行','框架版本＋完整合法基因\n展開成 CandidateAgent.java','程式檢查選值，編譯後對戰；\n以結果判斷策略成效']],[320,720,500],220,385,28);
text(s,'例：早期騷擾 → 小型採集經濟、偏好工人目標、提高前進偏好',66,650,1540,65,31,true,C.wine);
text(s,'具體 slot 值由 LLM 在合法範圍內選擇；自然語言描述保留為策略意圖',66,730,1540,65,28);
foot(s,'設定 framework.initial_strategy_mode: llm_plus_authored；先產生描述，再依描述填值。描述不同不保證行為不同。');
s=page('沿用的九種初始策略','新模式沿用舊清單第 2–10 項；原 WorkerRush 位置改為 LLM 新策略');
s.speakerNotes.text='來源：prompts/framework_initial_strategies.txt 第2–10條。九種策略中文為忠實摘要；1＋9初始化由 framework.initial_strategy_mode: llm_plus_authored 選用。WorkerRush 是舊清單第一條，本稿以新LLM策略替代其位置。';
table(s,[['策略','自然語言策略重點'],['輕兵時機進攻','早建兵營、維持小型經濟，集結輕兵打敵方生產設施'],['遠程防守反擊','遠程兵保護基地與採集者，集火接近者，守住首波後反攻'],['持續騷擾','工人與低成本單位干擾採集，避免昂貴屯兵，持續施壓'],['重兵時機進攻','先建立採集供給，集中重兵，取得局部優勢後協同進攻'],['基地防守反擊','守住基地與資源線，優先打威脅工人的敵人，有優勢再反攻'],['經濟與擴張','提高採集效率、取得更多資源，保留防守並轉為持續產兵'],['反快攻生存','先保工人與基地，敵近時停止貪經濟，守住後逐步施壓'],['混合兵種控制','結合輕兵、重兵、遠程兵；爭資源線，局部兵力有利才交戰'],['遠程時機進攻','最低限度防守後投資遠程兵，集結打高價值目標並避開近戰']],[390,1150],210,585,27);
foot(s,'描述作為選值參考；實際可表達的策略受框架機制與有限 slot 選項約束。以下實驗結果仍屬原 1030 設定。');
await(await PresentationFile.exportPptx(p)).save(root+'/build/strategy-v2-draft.pptx');
console.log(JSON.stringify({slides:p.slides.items.length}));
