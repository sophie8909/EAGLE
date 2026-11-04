import fs from 'node:fs/promises';
import {Presentation,PresentationFile} from '@oai/artifact-tool';
const root='D:/Project/EAGLE/Meeting/20261104_genotype';
const bundle=JSON.parse(await fs.readFile('D:/Project/EAGLE/configs/framework_bundles/gpt_finite_rule_market_v1/bundle.json','utf8'));
const p=Presentation.create({slideSize:{width:1672,height:941}});
const C={ink:'#423C3B',wine:'#47171C',blush:'#DEB4BA',paper:'#FCF8F5'};const font='Source Han Serif TW';
function text(s,t,x,y,w,h,size=28,bold=false,color=C.ink){const a=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});a.text=t;a.text.style={fontSize:size,typeface:font,color,bold,insets:0,verticalAlignment:'middle',wrap:'square',autoFit:'none'};return a;}
function page(title,sub){const s=p.slides.add();s.background.fill=C.paper;text(s,title,64,36,1544,82,47,true,C.wine);text(s,sub,66,125,1530,52,27,false,'#877675');s.speakerNotes.text='來源（2026-11-04 查閱）：eagle/candidate.py；configs/framework_bundles/gpt_finite_rule_market_v1/bundle.json；configs/experiments/1030_gpt_framework_slot_ablation_seed8_10/03_gpt_framework_gpt_seed_local_evolution.yaml；eagle/operators/framework_coach.py；eagle/generation/framework_slots.py；prompts/framework_initial_selection.txt、framework_coach_selection.txt、framework_option_selection.txt。框架 SHA-256: f674a580f0db088bd3436232d2dd36d071a231c9886f480a7aaed25669203e2b。24 個 slot 僅指本章 1030 實驗框架，不代表所有框架的固定大小。';return s;}
function foot(s,t){text(s,t,66,844,1535,52,22);}
function table(s,rows,widths,y,h,size=27){const tb=s.tables.add({rows:rows.length,columns:rows[0].length,left:66,top:y,width:1540,height:h,columnWidths:widths,values:rows});tb.borders.assign({fill:'#E8D8D9',width:1,style:'solid'});for(let r=0;r<rows.length;r++)for(let c=0;c<rows[0].length;c++){const cell=tb.getCell(r,c);cell.fill=r===0?C.blush:C.paper;cell.text.style={typeface:font,fontSize:size,color:C.ink,bold:r===0,insets:9};}return tb;}
let s=page('Framework Slots：個體的基因型態','1030 實驗框架：24 個 slot 選值，組成唯一活躍基因 control_genome');
table(s,[['層級','保存內容','在本章實驗中的作用'],['活躍基因','control_genome\n6 個行為選項＋18 個整數參數','逐 slot 交配；一次突變最多改一個值'],['框架輸入','Java 模板、slot 合法範圍與選項\n框架版本雜湊','由實驗固定；界定所有可表達的行為'],['表現型','generated_java\n完整 CandidateAgent.java','由框架與基因確定性展開，再編譯對戰'],['輔助資訊','策略描述、血統、分數、行為簽章','描述可供 Coach 填值；評估與血統不屬活躍基因']],[250,625,665],220,440,28);
text(s,'control_genome → 合法值驗證 → 模板展開 → Java → 對戰',66,700,1540,70,35,true,C.wine);
foot(s,'本章使用固定 gpt_finite_rule_market_v1。其他框架可有不同 slots；reflection 模式另可在世代邊界更新框架。');
s=page('6 個行為選項基因','每個基因皆為 expression_choice：四選一；個體保存 choice_id');
table(s,[['Slot','四種可選行為','作用位置'],['harvest_mode','靠近工人／靠近基地／低危險／資源多','採礦目的地評分'],['build_mode','基地附近／資源附近／向敵前推／低危險','工人相鄰建造位置評分'],['mix_mode','加權平衡／偏輕兵／重兵回應／遠程回應','輕兵、重兵與遠程兵生產評分'],['target_mode','最近／低血量／工人／建築','攻擊與追擊的敵人目標評分'],['move_mode','接近／避開敵軍密集處／射程間距／基地集結','額外移動候選評分'],['condition_mode','隨時／時間達標／兵力達標／附近安全','建造與額外移動的啟用條件']],[340,760,440],215,555,27);
foot(s,'condition_mode 不封鎖直接攻擊與目標追擊；move_mode 的額外移動與追擊候選可同時存在。');
s=page('12 個控制參數基因','合法值由 bundle 宣告；全部為整數，範圍與 step 限定搜尋空間');
const purposes={worker_cap:'工人訓練數量上限',harvester_cap:'依工人 ID 排序，前 N 名可採礦',base_cap:'基地建造數量上限',barracks_cap:'兵營建造數量上限',build_time:'最早建造週期；亦可作時間閘門',reserve:'建造／戰鬥產兵所需資源餘額',threat_radius:'附近敵方攻擊單位的曼哈頓半徑',retreat_hp:'可提出撤退的目前血量上限',retreat_distance:'撤退步的分離距離條件',rally_radius:'距己方基地超過此距離才提出集結',heavy_weight:'重兵生產偏好權重',ranged_weight:'遠程兵生產偏好權重'};
const numeric=bundle.slots.filter(x=>x.kind==='integer'&&!x.slot_id.endsWith('_priority'));
if(numeric.length!==12)throw Error('Expected 12 numeric control slots');
table(s,[['Slot','合法範圍／間距','行為作用'],...numeric.map(x=>[x.slot_id,`${x.minimum}–${x.maximum}；step ${x.step}`,purposes[x.slot_id]])],[380,330,830],200,615,26);
foot(s,'數量上限按當前單位計算。retreat_distance 的比較門檻會截至目前距離＋1；合法性仍由遊戲引擎檢查。');
s=page('6 個優先分數基因','每個值都是整數 0–200；step 與各 slot 的 bundle 定義一致');
const priorityNames={attack_priority:'合法射程內的直接攻擊',economy_priority:'採礦與資源返還',build_priority:'基地／兵營建造',train_priority:'工人與戰鬥單位生產',retreat_priority:'受威脅、低血量時的撤退',advance_priority:'目標追擊與額外移動'};
const priorities=bundle.slots.filter(x=>x.slot_id.endsWith('_priority'));if(priorities.length!==6)throw Error('Expected six priority genes');
table(s,[['Slot','支配的行動候選','合法值'],...priorities.map(x=>[x.slot_id,priorityNames[x.slot_id],`${x.minimum}–${x.maximum}；step ${x.step}`])],[460,730,350],215,420,29);
text(s,'行動分數 ＝ 優先分數 ＋ 距離、危險、兵種等情境分數',66,675,1540,65,34,true,C.wine);
text(s,'每個閒置單位從合法候選中選最高分；先選的行動會預留資源與位置',66,755,1540,55,28);
foot(s,'這些值是評分基準，不是行動機率。提高某個分數不保證一定改變行動；效果取決於局面與其他基因。');
s=page('LLM 選值、驗證與 Java 展開','LLM 一次回傳完整 control_genome；程式負責合法性與執行');
table(s,[['步驟','輸入／輸出','處理方式'],['1  提供選值依據','Slot 用途、範圍／選項說明、框架報告\n加上當前基因或策略描述／評估證據','選值提示詞提供策略資訊；\n一般 selector 不提供 Java 實作全文'],['2  LLM 回傳完整 JSON','schema_version、框架 SHA-256\ncontrol_genome 的全部 24 個值','每個 slot 恰好一次；\n選項回傳 choice_id'],['3  嚴格驗證與展開','欄位、框架版本、每個值的合法範圍','數值替換模板標記；\nchoice_id 對應預先宣告的 Java 表達式'],['4  編譯與評估','完整 Java → 編譯／整合 → 對戰','適應度用於選擇；\n格式合法不代表策略有效']],[320,700,520],210,460,27);
text(s,'本章方法 3：預存 GPT Genome 只放入 G0 Index 0',66,704,1540,55,33,true,C.wine);
text(s,'其餘初始化與所有後代皆用 Local EA；不在每代呼叫 LLM 填值',66,770,1540,50,28);
foot(s,'llm_coach 可依父代結果選完整基因；reflection／option_reflection 另有策略描述修訂與 slot 填值兩階段。');
await(await PresentationFile.exportPptx(p)).save(root+'/build/genotype-draft.pptx');
console.log(JSON.stringify({slides:p.slides.items.length,nativeTables:p.slides.items.map(s=>s.tables.items.length)}));
