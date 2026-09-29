import fs from 'node:fs/promises';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
const root='D:/Project/EAGLE';
const skill='C:/Users/cinna/.codex/plugins/cache/openai-primary-runtime/presentations/26.915.20218/skills/presentations';
const runtime='C:/Users/cinna/.cache/codex-runtimes/codex-primary-runtime/dependencies';
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const build=path.join(root,'Meeting/20261001_self_play/.codex-build');
const output=path.join(root,'Meeting/20261001_self_play');
const validation=path.join(root,'.codex-presentation-validation');
const {importRuntimeModule}=await import(pathToFileURL(path.join(skill,'container_tools/runtime_helpers.mjs')).href);
const {Presentation,PresentationFile}=await importRuntimeModule('@oai/artifact-tool');
const {finalizePresentation,applyPresentationChartFont}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const palette=JSON.parse(await fs.readFile(path.join(root,'Meeting/template/EAGLE.palette.json'),'utf8'));
const C={ink:palette.heading,body:palette.body,rose:palette.rose,bg:palette.background,header:palette.table.headerFill,highlight:palette.table.highlightFill};
const F=palette.font;
const p=Presentation.create({slideSize:{width:1280,height:720}});
const tableSlides=[],chartSlides=[];
function text(s,t,x,y,w,h,size=24,color=C.body,bold=false){const o=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});o.text=t;o.text.style={typeface:F,fontSize:size,color,bold,autoFit:'none'};return o;}
function slide(title,sub='',source=''){const s=p.slides.add();s.background.fill=C.bg;const n=p.slides.items.length;text(s,title,58,38,1164,68,38,C.ink,true);if(sub)text(s,sub,60,110,1160,54,20,C.body);text(s,'EAGLE　2026/10/01',60,676,650,22,14,C.body);text(s,String(n).padStart(2,'0'),1170,674,60,24,16,C.body);s.speakerNotes.textFrame.setText(`資料截點：2026-09-29\n${source}`);return s;}
function takeaway(s,t,y=615){text(s,t,60,y,1150,52,24,C.ink,true);}
function table(s,values,y=178,h=360,widths=null,size=22){const t=s.tables.add({rows:values.length,columns:values[0].length,left:60,top:y,width:1160,height:h,values,...(widths?{columnWidths:widths}:{})});t.borders.assign({fill:palette.table.border,width:0.6});t.cells.block({row:0,column:0,rowCount:values.length,columnCount:values[0].length}).assign({margins:{top:3,bottom:3,left:8,right:8}});for(let r=0;r<values.length;r++){t.rows[r].height=h/values.length;for(let c=0;c<values[0].length;c++){const cell=t.getCell(r,c);cell.fill=r===0?C.header:(['Total','G17','缺少'].includes(String(values[r][0]))?C.highlight:palette.table.bodyFill);cell.text.style={typeface:F,fontSize:size,color:palette.table.bodyText,bold:r===0,autoFit:'none'};}}tableSlides.push(p.slides.items.length);return t;}
function chart(s,categories,series,pos={left:70,top:175,width:1130,height:390},opts={}){const ch=s.charts.add('bar',{position:pos,categories,series,barOptions:{direction:'column',grouping:'clustered',gapWidth:100,...opts.barOptions},hasLegend:series.length>1,legend:{position:'bottom',textStyle:{fontSize:18,typeface:F}},chartFill:C.bg,plotAreaFill:C.bg,xAxis:{textStyle:{fontSize:17,typeface:F}},yAxis:{min:0,textStyle:{fontSize:16,typeface:F},...opts.yAxis},dataLabels:{showValue:true,position:'outEnd',textStyle:{fontSize:18,typeface:F},...opts.dataLabels}});applyPresentationChartFont(ch,{fontFamily:F});chartSlides.push(p.slides.items.length);return ch;}

let s=slide('EAGLE 實驗比較與結果校核','研究會議｜實驗資料截至 2026/09/29','來源：Meeting/20261001/README.md；Notion MicroRTS EAGLE 實驗資料庫。');
text(s,'Self-play 結果、歷史對照與缺漏實驗',62,210,1120,78,42,C.ink,true);
text(s,'所有結果先按 run ID、resolved config 與共同 600 場 final test 校核',64,310,1110,50,26,C.body);
text(s,'涵蓋 09/07–09/29 分析文件與 Notion 0924 後 4 次 self-play runs',64,375,1110,40,22,C.body);

s=slide('原草稿需更新的數字與比較口徑','舊版資料仍有參考價值，但不能當作最新 10×20 結果','Meeting/20261001_self_play/20261001_palette.pptx；Meeting/20261001/README.md；Notion 0925–0927 pages.');
table(s,[['校核項目','校正後口徑'],['0923 10×20 與 0927 10×20','不同 run。0927 semantic tie-break 為 0/444/156/0 W/L/D/E；舊 0923 為 0/449/151/0。'],['0925 5×40 identity','以 config 與 run ID 判斷；manifest experiment_name 誤寫為 self_play_10x20。'],['比分順序','全簡報統一使用 W/L/D/E；不得混用 W/D/L。'],['fitness 比較','Self-play snapshot 每 5 代換對手 context；跨 snapshot/run 不直接比較 GP。'],['因果結論','舊草稿的 5×40 優勢是觀察結果；selection 版本、refresh hash 漂移與 repository revision 仍是混淆因子。']],180,350,[300,860],20);

takeaway(s,'外部泛化統一看共同 600 場 fixed-roster final test 的 W/L/D/E');

s=slide('FFE：先固定 regular offspring 預算','採 generations × population size 作為同預算比較口徑；初始族群與 refresh 評估另計','本地 configs/experiments/0925_self_play/*.yaml、0926_self_play_sent/self_play_10x20.yaml；Notion run pages.');
table(s,[['配比','Regular offspring FFE','可比較問題'],['10×10','100','較大族群、較淺搜尋'],['5×20','100','較小族群、較深搜尋'],['10×20','200','較大族群、較淺搜尋'],['5×40','200','較小族群、較深搜尋']],190,300,[300,330,530],23);
text(s,'10×20 和 5×40 的 regular offspring 都是 200；總 artifacts 不等於 FFE，因 gen0、snapshot refresh 和 repairs 會增加評估。',62,523,1135,55,22,C.body);
takeaway(s,'同預算比較的是「族群規模／搜尋深度配置」，不是單獨改 generations');

s=slide('生成模型：Ministral-only 與雙模型 pipeline','20×10、模型角色是主要配置差異；結果只代表兩次完整 run','Meeting/20261001/analysis_md/20260910_generation_model_comparison.md；runs 20260908_121222_306081、20260909_032729_611766.');
table(s,[['指標','Ministral-only','Ministral → Qwen3.5'],['Best / mean GP','−47.52 / −58.99','−81.91 / −87.62'],['Final population W/L/D','542 / 1,056 / 202','5 / 1,284 / 511'],['Java generation success','186/200 (93.0%)','195/200 (97.5%)'],['First-attempt success','140/200 (70.0%)','183/200 (91.5%)'],['Unique Java hashes','10','5']],180,337,[340,405,415],20);
text(s,'雙模型較容易生成可編譯 Java，卻未把成功率轉成對戰表現。兩組獨立抽樣初始 policy，10 個 policy hash 只有 1 個相同。',62,546,1140,48,20,C.body);
takeaway(s,'方向明確，模型因果仍需同起始 policies 的重複對照');

s=slide('初始族群：全 Worker Rush 與 Mixed policies','兩組都是 20×10；此配對比較的是完整初始化方案','Meeting/20261001/analysis_md/20260912_initial_population_comparison.md；runs 20260910_160655_907573、20260911_072610_382082.');
table(s,[['Final test / run 狀態','全 Worker Rush','Mixed policies'],['Wins / 600','24 (4.0%)','256 (42.7%)'],['W/L/D','24 / 435 / 141','256 / 332 / 12'],['Run time','15.21 h','16.72 h'],['Candidate failures','3/210','23/210']],182,270,[390,380,390],22);
text(s,'Mixed 將 policy 組成、Java seed 和 gen0 materialization 一起改變；結果支持 Mixed 初始化方案整體較佳，不能單獨歸因於 policy 多樣性。',62,493,1140,70,22,C.body);
takeaway(s,'戰力提高伴隨較多失敗；後續需固定 Java 初始化流程拆出單一因素');

s=slide('父代評估：reuse cached 對 regenerate genotype','此為歷史資料中控制最完整的單變因配對','Meeting/20261001/analysis_md/20260914_parent_regeneration_comparison.md；common gen0 fork；20×10.');
table(s,[['指標','reuse_cached','regenerate_same_genotype'],['Best / mean GP','−50.51 / −65.35','−79.34 / −87.29'],['Search W/L/D','510 / 1,121 / 169','88 / 1,328 / 384'],['Committed time','16.43 h','26.25 h'],['Case-wise maxima','9/10 較高','1/10 較高']],182,275,[350,405,405],21);
text(s,'兩組從同一 gen0 checkpoint 出發，實質差異只有 parent evaluation mode。Treatment 未做獨立 final test，比分是搜尋 evaluation matrix。',62,494,1140,62,20,C.body);
takeaway(s,'單次配對支持保留已驗證 phenotype 與 fitness');

s=slide('Reflection 測試證明流程能運作，未估計一般效果','5×3、5 代、15 個 offspring 的 report 是 pipeline assessment','Meeting/20261001/analysis_md/20260907_reflection_ratio_full_report.md；configs/experiments/0914_reflection_ablation_20x10/; experiment_results_after_0907.md.');
table(s,[['可確認','仍不能確認'],['Strategy / Prompt / Code Reflection 均有執行記錄','0.33/0.33/0.34 不是三組 operator 比較'],['Code revision 多次需要 compile repair','15 個 offspring 樣本不足以估計勝率或 operator 因果'],['部分 genotype 有實際變化，但不少 Java 差異很小','child 的 crossover、mutation 與 match randomness 同時影響 GP']],180,292,[550,610],22);
text(s,'09/08 版本加入 generation-wide materialization 與可選 generation_model，模型比較之後才能維持相同 20×10 搜尋條件。',62,502,1135,55,20,C.body);
takeaway(s,'operator schedule 的效果尚無乾淨、足量的單因子對照');

s=slide('0924 後 self-play 四組 run','Notion 記錄與本地 README 的 run ID、配置和 final test 相符','本地 Meeting/20261001/README.md；Notion：0925 5×40、0926 10×10、0926 5×20、0927 10×20 pages.');
table(s,[['Run / protocol','Gen × pop','FFE','Final test W/L/D/E'],['0925 5×40 legacy lexicase','40 × 5','200','197 / 392 / 11 / 0'],['0926 10×10 semantic tie-break','10 × 10','100','257 / 321 / 22 / 0'],['0926 5×20 semantic tie-break','20 × 5','100','0 / 388 / 212 / 0'],['0927 10×20 semantic tie-break','20 × 10','200','0 / 444 / 156 / 0']],178,340,[390,220,150,400],20);
text(s,'四組都完成 600 場 final test，Integration 7/7，match errors = 0。10×10 的 final test wins 最高：257/600（42.83%）。',62,542,1140,42,20,C.body);

s=slide('100 FFE：10×10 明顯優於 5×20，但只有單次觀察','兩組使用 semantic tie-break、相同 9 個 semantic probes 與 600 場 final test','Meeting/20261001/analysis_md/20260928_self_play_10x10_vs_5x20.md；Notion 0926 pages.');
chart(s,['10×10','5×20'],[{name:'Wins',values:[257,0],fill:palette.chart.win},{name:'Draws',values:[22,212],fill:palette.chart.draw},{name:'Losses',values:[321,388],fill:palette.chart.loss}],{left:80,top:175,width:1080,height:365},{barOptions:{grouping:'stacked'},dataLabels:{position:'center'},yAxis:{max:600,majorUnit:100}});
text(s,'10×10：42.83% 勝率；5×20：0% 勝率。5×20 搜尋期 180 場全和，正 GP 來自資源／兵力 shaping。',62,555,1145,42,21,C.body);
takeaway(s,'同 FFE 的結果差距很大，refresh phenotype 漂移阻止強因果歸因',620);

s=slide('100 FFE：差異涵蓋多數對手，不只單一 matchup','每個對手 60 場；列出 wins，來源完整 W/L/D 見分析文件','Notion 0926 Self-play 10×10 與 5×20 pages；Meeting/20261001/analysis_md/20260928_self_play_10x10_vs_5x20.md.');
table(s,[['Opponent','10×10 wins','5×20 wins'],['PassiveAI / RandomAI','60 / 60','0 / 0'],['RandomBiasedAI','46','0'],['LightRush / HeavyRush','20 / 30','0 / 0'],['WorkerRush / AllInBot','10 / 10','0 / 0'],['Mayari / COAC','11 / 10','0 / 0'],['TMA','0','0'],['Map wins: 8×8 / 16×16 / 24×24','130 / 77 / 50','0 / 0 / 0']],180,360,[430,365,365],20);
text(s,'10×10 勝率隨地圖放大下降：65.0% → 38.5% → 25.0%；5×20 三張圖均無勝場。',62,558,1140,40,20,C.body);

s=slide('200 FFE：缺少 5×40 semantic-tie-break run','這組缺漏讓 10×20 vs 5×40 的配置比較暫時不成立','Notion 0925 / 0927 pages；configs/experiments/0929/README.md.');
table(s,[['已有實驗','配置','協定','W/L/D/E'],['0927 run 20260928_115653_334420','10×20, 200 FFE','semantic tie-break','0 / 444 / 156 / 0'],['0925 run 20260925_134245_911171','5×40, 200 FFE','legacy lexicase','197 / 392 / 11 / 0'],['0929 待跑 config','5×40, 200 FFE','semantic tie-break','待測']],180,290,[315,205,330,310],20);
text(s,'0925 legacy 5×40 和 0927 semantic 10×20 不能當作只改人口／世代的對照，selection protocol 不同。',62,504,1135,55,21,C.body);
takeaway(s,'新增的 5×40 semantic config 同時補齊 FFE allocation 與 selection-method 配對');

s=slide('同為 10×20 的兩次 self-play 結果不能合併','舊草稿 0/151/449 是 0923 run，不是 0927 semantic-tie-break run','Meeting/20261001/analysis_md/20260923_self_play_20x10.md；Notion 0927 Self-play 10×20 page.');
table(s,[['Run','Search protocol','Final test W/L/D/E','Refresh audit'],['0923 20260923_134743_200030','較早 self-play protocol','0 / 449 / 151 / 0','舊版分析資料'],['0927 20260928_115653_334420','semantic tie-break','0 / 444 / 156 / 0','14/50 Java hashes preserved']],180,240,[340,330,300,190],20);
text(s,'表現差異可描述，不能只歸因於 semantic tie-break：source revision、refresh Java 漂移、候選 failures 和 initial population 都不同。',62,472,1135,60,21,C.body);
takeaway(s,'保留 run ID，避免以相同 10×20 標籤覆蓋不同協定');

s=slide('Semantic tie-break 有界：只保留同 fitness tier 的行為差異','tie-break 無法跨過 fitness 差距補回已消失的語意多樣性','Meeting/20261001/analysis_md/20260928_self_play_10x10_vs_5x20.md；Notion 0926 pages.');
table(s,[['觀察','10×10','5×20'],['Final unique semantic signatures','1 / 10','2 / 5'],['最高 tier 的候選池','多代只有 1 種語意','G8 曾有 10 種，末代剩 2 種'],['Final self-play W/D/L','60 / 60 / 60','0 / 180 / 0'],['Fixed-roster wins','257','0']],180,285,[390,385,385],21);
text(s,'9 個 fixed probe states 只描述局部 action semantics，無法單獨保證整場比賽會進攻、追擊或結束。',62,500,1135,50,21,C.body);

s=slide('Refresh Java 漂移與 candidate failures 是主要有效性風險','所有 4 個 Notion runs 的 final tests 無 match errors；演化路徑仍有紀錄完整性 caveat','Notion 0925–0927 pages；Meeting/20261001/analysis_md/20260928_self_play_10x10_vs_5x20.md.');
table(s,[['Run','Refresh records','Java hash 保留','Candidate failures'],['0925 5×40 legacy','40','14/40','2 / 245'],['0926 10×10 semantic','20','5/20','5 / 130'],['0926 5×20 semantic','25','8/25','3 / 130'],['0927 10×20 semantic','50','14/50','28 / 260']],180,300,[330,240,270,320],21);
text(s,'0927 的 28 failures：validation 19、generation 7、compilation 2。0926 5×20 多出 generation 4 migration refresh。',62,512,1135,50,20,C.body);
takeaway(s,'固定對手 final test 可讀作實際策略結果；演化機制歸因需先修正 refresh invariant');

s=slide('整體結果：高 FFE 或較多世代沒有保證更強','本批四組單次 runs 中，10×10 的共同外部測試勝場最多','Notion MicroRTS EAGLE runs dated 2026-09-25 to 2026-09-28.');
chart(s,['0925 5×40 legacy','0926 10×10 sem.','0926 5×20 sem.','0927 10×20 sem.'],[{name:'Wins',values:[197,257,0,0],fill:palette.chart.win},{name:'Draws',values:[11,22,212,156],fill:palette.chart.draw},{name:'Losses',values:[392,321,388,444],fill:palette.chart.loss}],{left:70,top:170,width:1140,height:370},{barOptions:{grouping:'stacked'},dataLabels:{position:'center'},yAxis:{max:600,majorUnit:100}});
text(s,'Observed ordering: 10×10 > legacy 5×40 > semantic 5×20 ≈ semantic 10×20 by wins. Protocol and refresh differences prevent ranking config effects.',62,565,1140,35,18,C.body);
takeaway(s,'優先以 10×10 作可重現的近期戰力基準，先釐清 phenotype-preserving refresh');

s=slide('0929 實驗矩陣：缺漏 arm 與可回答問題','新增參數只定義待跑條件，尚未聲稱已有實驗結果','configs/experiments/0929/README.md; self_play_5x40_semantic_tiebreak.yaml.');
table(s,[['比較組','已存在','0929 補缺','單一問題'],['100 FFE allocation','10×10 vs 5×20 semantic','已各跑一次；重跑需修 refresh','族群深度配置'],['200 FFE allocation','10×20 semantic','5×40 semantic','族群深度配置'],['5×40 selection','legacy lexicase','semantic tie-break','selection protocol']],180,260,[300,340,330,190],19);
text(s,'每個新 run 固定模型、seed prompt、地圖、mutation、refresh 間隔與 final-test roster；固定同一初始族群 artifact 後再做多個獨立 replicates。',62,477,1140,70,20,C.body);
takeaway(s,'0929 新增 config 可同時作為兩個 200 FFE 配對的共用對照組');

s=slide('新增 config 的參數與預期控制條件','config 源自 semantic 10×20；僅更改 experiment name、generations 和 population size','configs/experiments/0929/self_play_5x40_semantic_tiebreak.yaml；對照 configs/experiments/0926_self_play_sent/self_play_10x20.yaml.');
table(s,[['參數','0929 設定'],['Algorithm / tie-break','game_performance_semantic_tiebreak；fitness tie tolerance 1.0'],['Generations × population','40 × 5 = 200 regular offspring'],['Model / EA seed','ministral3_8b / 7'],['Self-play refresh','每 5 代；10 個 self-play slots 沿用源 config'],['Semantic probes','3 maps × early/mid/late = 9 states'],['Maps / rounds / sides','8×8、16×16、24×24；3 rounds；swap sides'],['Mutation / crossover','0.33 / 0.33 / 0.34；0.75 / 1.0']],178,335,[360,800],19);
text(s,'FFE 同額指 offspring 數；gen0、refresh replicas 和 retries 另計。執行前先確保 refresh 不會重生或改寫 Java phenotype。',62,548,1140,46,19,C.body);

s=slide('來源與數據限制','以 canonical run artifacts 為優先；本次可用的 0924 後彙整為 Notion page + meeting snapshot','Notion database MicroRTS EAGLE; Meeting/20261001/README.md and analysis_md/*.md.');
table(s,[['來源組','納入文件／記錄'],['Self-play','Notion 0925、0926 10×10、0926 5×20、0927 10×20；README.md 與 3 份 self-play analysis'],['Earlier controlled studies','09/07 reflection、09/10 model、09/12 initialization、09/14 parent regeneration'],['Cross-cutting','experiment_results_after_0907.md；version_summary_after_0907.md；model_parameter_audit.md'],['Limit','本地 runs 資料夾未提供 0925–0927 原始 run artifacts；近期細節以 Notion page 和同步的 analysis_md 為證據。']],180,300,[340,820],19);
text(s,'Notion sources: https://app.notion.com/p/3eac9b9735d9810d87b4ce89769bd4b6 ; https://app.notion.com/p/3eac9b9735d981f78c00e9a7706af646 ; https://app.notion.com/p/3eac9b9735d98115b78be874b606a195 ; https://app.notion.com/p/3eac9b9735d981518b7cf0dfe691ade7',62,515,1150,62,14,C.body);

await fs.mkdir(build,{recursive:true});
await fs.mkdir(validation,{recursive:true});
const authored=path.join(build,'authored.pptx');
const draft=path.join(build,'template-candidate.pptx');
await(await PresentationFile.exportPptx(p)).save(authored);
const template=path.join(root,'Meeting/template/EAGLE.potx');
const reference=path.join(build,'EAGLE-reference.pptx');
await fs.copyFile(template,reference);
execFileSync(path.join(runtime,'python/python.exe'),[path.join(root,'Meeting/20261001_self_play/apply_template.py'),authored,template,draft],{stdio:'inherit'});
const finalPath=path.join(output,'20261001_verified.pptx');
try{await fs.access(finalPath);throw new Error(`Refusing to overwrite ${finalPath}`);}catch(e){if(e.code!=='ENOENT')throw e;}
const result=await finalizePresentation({workspaceDir:root,candidatePath:draft,finalPath,pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15925800,8963025','--validate-heading-fit',...tableSlides.flatMap(n=>['--require-native-table-slide',String(n)])],explicitTotalSlideCount:18,requiredNativeTableOwnerSlides:tableSlides,requiredNativeChartOwnerSlides:chartSlides,materializeLiteralChartWorkbooks:true,fontPolicy:{basis:'reference',families:[F],referencePath:reference,referenceSha256:createHash('sha256').update(await fs.readFile(reference)).digest('hex')},verifyArtifactToolImport:true,receiptPath:path.join(validation,'20261001_verified.validation.json')});
console.log(JSON.stringify({finalPath:result.finalPath,receiptPath:result.receiptPath,slides:p.slides.items.length,tables:tableSlides,charts:chartSlides}));
