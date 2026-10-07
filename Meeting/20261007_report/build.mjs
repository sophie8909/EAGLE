import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';

const root='D:/Project/EAGLE';
const workspaceDir=path.join(root,'Meeting/20261007_report');
const build=path.join(workspaceDir,'.codex-build');
const skill='C:/Users/cinna/.codex/plugins/cache/openai-primary-runtime/presentations/26.915.20218/skills/presentations';
const runtime='C:/Users/cinna/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const reference=process.env.EAGLE_REFERENCE ?? 'J:/我的雲端硬碟/Lab/Meeting/20261001_0930_self_play.pptx';
const output=process.env.EAGLE_OUTPUT ?? path.join(workspaceDir,'deliverables/20261007.pptx');
const report='reports/20261007_experiment_and_changes_report.md';
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const {importRuntimeModule}=await import(pathToFileURL(path.join(skill,'container_tools/runtime_helpers.mjs')).href);
const {Presentation,PresentationFile,FileBlob}=await importRuntimeModule('@oai/artifact-tool');
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
await fs.mkdir(build,{recursive:true});
await fs.mkdir(path.dirname(output),{recursive:true});

// Preserve the reference theme, layouts, master artwork, and slide dimensions.
const imported=await PresentationFile.importPptx(await FileBlob.load(reference));
const proto=imported.toProto();
proto.slides=[];
proto.charts=[];
const deck=Presentation.load(proto);
const F='Source Han Serif TW';
const C={ink:'#47171C',body:'#423C3B',background:'#FCF8F5',header:'#DEB4BA',rose:'#CF8792'};
const tableSlides=[];
function text(slide,value,x,y,w,h,size=26,color=C.body,bold=false,align='left'){
 const shape=slide.shapes.add({geometry:'textbox',name:`text-${slide.shapes.items.length}`,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 shape.text=value;
 shape.text.style={typeface:F,fontSize:size,color,bold,autoFit:'none',alignment:align};
 return shape;
}
function slide(title,subtitle,section,extraNotes=''){
 const s=deck.slides.add({layoutId:'/ppt/slideLayouts/slideLayout12.xml',width:1672,height:941});
 text(s,title,240,46,1192,110,48,C.ink,true,'center');
 if(subtitle)text(s,subtitle,190,169,1292,66,25,C.body,false,'center');
 text(s,String(deck.slides.items.length),766,890,140,32,22,C.rose,false,'center');
 s.speakerNotes.textFrame.setText(`資料來源：${report}\n章節：${section}\n報告日期範圍：2026-10-01 至 2026-10-07\n分析基準 HEAD：68476fa29fc（報告所載）\n${extraNotes}`);
 return s;
}
function table(s,values,widths,y=263,h=360,size=25){
 const t=s.tables.add({rows:values.length,columns:values[0].length,left:150,top:y,width:1372,height:h,columnWidths:widths,values});
 t.borders.assign({fill:C.body,width:0.6});
 t.cells.block({row:0,column:0,rowCount:values.length,columnCount:values[0].length}).assign({margins:{top:7,bottom:7,left:10,right:10}});
 for(let r=0;r<values.length;r++){
  t.rows[r].height=h/values.length;
  for(let c=0;c<values[0].length;c++){
   const cell=t.getCell(r,c);cell.fill=r===0?C.header:C.background;
   cell.text.style={typeface:F,fontSize:size,color:C.body,bold:r===0,autoFit:'none'};
  }
 }
 tableSlides.push(deck.slides.items.length);
 return t;
}
function conclusion(s,value,y=715){text(s,value,160,y,1352,90,28,C.ink,true);}

let s=slide('EAGLE 實驗與程式變更','2026/10/01–10/07 研究進度','1、5');
text(s,'Deterministic mode 與重複實驗',230,315,1212,85,52,C.ink,true,'center');
text(s,'4×10 mock pipeline 通過同 seed 行為比對',245,441,1182,60,34,C.body,false,'center');
text(s,'實際 LLM 生成層的可重現性仍待驗證',245,531,1182,58,30,C.body,false,'center');

s=slide('10/7 的新增證據','同 seed 比較演化行為，執行時間另外記錄','1、2、5、6');
table(s,[['驗證項目','執行規模','結果'],['3×2 smoke gate','seed 7、8、9，各 2 run','mock complete，同 seed 一致'],['4×10 主實驗','seed 7、8，各 2 run','4 run 完成，同 seed 一致'],['實際 Ministral LLM','本機沒有 CUDA','尚無完整模型生成層證據']],[340,450,582],270,315,28);
conclusion(s,'目前證據涵蓋完整 EA/mock pipeline，實際 LLM 尚待補測');

s=slide('10/2–10/6 的歷史實驗','當時設定以各 run 的 config.yaml 為準','3','歷史 artifact 位於 /home/mhlab/EAGLE/runs/。不得以現在的 config 回推舊 run。');
table(s,[['日期與規模','Runs / 狀態','解讀限制'],['10/2 parallel 20×10','1 run interrupted','保留作效能與 artifact 對照'],['10/2–10/4 self-play 20×10','seed 7、8、9 各完成','GP scalar 與 semantic tie-break'],['10/5 self-play 4×10','seed 7 曾 failed，seed 7/8 完成','temperature 與 GPU runtime 未統一'],['10/6 self-play 10×4','seed 7、8、9 各 2 run 完成','deterministic mode 加入前執行']],[440,435,497],260,380,25);
conclusion(s,'舊 10×4 重複實驗不能作為 deterministic 一致性證據');

s=slide('Deterministic 實驗的驗證順序','10/6 的模型生成嘗試與 10/7 的 mock gates 分開解讀','1、3');
table(s,[['日期與實驗','狀態','可用證據'],['10/6 deterministic 10×4','LLM server timeout，incomplete','僅部分 generation 0'],['10/7 deterministic 3×2','seed 7 gate 後續跑 seed 8/9','6 個 mock run，同 seed 一致'],['10/7 deterministic 4×10','seed 7、8 各兩次','4 個 mock run，同 seed 一致']],[470,450,452],270,325,27);
conclusion(s,'3×2 通過後再擴大至 4×10，模型生成驗證仍未完成');

s=slide('4×10 主實驗設定','4 generations、population 10，seed 7 與 8 各重複兩次','2','設定檔：configs/experiments/1009_determinism_4x10_2seeds/ministral3_8b_determinism_4x10_2seeds.yaml');
table(s,[['項目','設定'],['演化規模','4 generations × population 10'],['Seeds / runs','7、8，各 2 run，共 4 run'],['Self-play evaluation','10 slots × 3 maps × 3 rounds × 2 sides = 180 matches/candidate'],['Reflection','static，Strategy / Prompt / Code = 0.33 / 0.33 / 0.34'],['Reproducibility','deterministic_mode=true、temperature=0、serial match worker'],['Execution','mock，完整 EA/mock pipeline 驗證']],[335,1037],253,410,25);
conclusion(s,'180 matches/candidate 是評估配置，本報告未提供實際 LLM 勝率',735);

s=slide('4×10 同 seed 的行為比對','四個 run 均完成，兩組 seed 內比對皆 PASS','2','Run directories 均位於 runs/。Seed 7: 20261007_133838_331187、20261007_133856_523061。Seed 8: 20261007_133919_738016、20261007_133937_477330。');
table(s,[['Seed','Run 1（runs/）','Run 2（runs/）','比對'],['7','20261007_133838_331187','20261007_133856_523061','PASS'],['8','20261007_133919_738016','20261007_133937_477330','PASS']],[110,560,560,142],300,240,25);
text(s,'比對單位為同 seed 的兩次 run，報告未主張不同 seed 產生相同行為。',160,610,1352,80,28);
conclusion(s,'結果支持 seed 7 與 seed 8 各自的 EA/mock 行為可重現');

s=slide('行為 artifact 的比對範圍','Timing 差異不納入演化行為一致性判定','2、5');
table(s,[['Artifact 類型','同 seed 比對內容','結果'],['Generation / candidate','generation snapshots、candidate ID、lineage','一致'],['Fitness / evaluation','fitness、objectives、evaluation results','一致'],['Match / mutation','match score/vector、mutation/operator 路徑','一致'],['Timing','實際執行耗時','不同，排除於行為比對']],[355,855,162],265,365,27);
conclusion(s,'此次結論關於演化與評估行為，執行時間仍可不同');

s=slide('Seed propagation 的完整路徑','Explicit schedule 與各階段 seed contract','4：10/6','random_seeds: [7,8,9] 與 runs: 2 排程為 7,7,8,8,9,9。Match seed 持久化在 match metadata。');
table(s,[['階段','Deterministic contract'],['Run 排程','random_seeds=[7,8,9]，runs=2，排程為 7,7,8,8,9,9'],['EA 搜尋','EA、selection、crossover、operator choice 共用 seeded RNG'],['MicroRTS match','run seed 與 immutable match identity 派生 JVM seed'],['LLM request','initial policy、reflection、rewrite、Java generation、repair、preflight 均傳 seed']],[350,1022],265,355,26);
conclusion(s,'每場 match seed 寫入 metadata，便於回溯與重跑');

s=slide('Deterministic runtime contract','固定模型取樣與執行條件，降低 runtime 差異','4：10/5、10/6','CPU llama.cpp、threads=1、batch size≥512、parallel=1、match worker=1。Batch 修正避免 GGML_ASSERT(n_tokens_all <= cparams.n_batch)。');
table(s,[['控制面向','設定或變更'],['模型取樣','temperature=0，所有 LLM requests 傳遞 experiment seed'],['llama.cpp','CPU contract、threads=1、batch size≥512、parallel=1'],['MicroRTS','match worker=1，random source 使用 -Deagle.match.seed'],['Server lifecycle','seed trial 與 experiment run 邊界重啟 owned llama-server']],[365,1007],265,360,27);
conclusion(s,'Batch size 修正避免 context decode assertion，維持 deterministic 配置可執行');

s=slide('10/1–10/5：EA、self-play 與執行基礎','搜尋 orchestration、evaluation persistence 與 LLM lifecycle','4：10/1–10/5');
table(s,[['工作面向','主要變更'],['EA 與 self-play','semantic behavior 去重、LocalLearner lifecycle、fresh/resume orchestration 統一'],['Evaluation 與效能','降低 persistence / compact artifacts overhead，平行 match 保留 canonical order'],['Objective 與 runs','semantic tie-aware GP scalar、independent runs、workflow diagram / cleanup'],['LLM 與失敗處理','seed / stability diagnostics、80k prompt bound、failed candidates 與有效 parent pool 隔離']],[355,1017],260,390,25);
conclusion(s,'平行 evaluation 是一般執行能力，deterministic mode 採單 match worker');

s=slide('10/6–10/7：可重現性與 metadata 修正','Seed schedule、deterministic mode 與最後一個 UUID 差異','4：10/6、10/7、6','相關 commits：8b39a3c6c79、b712ec9c9da、cae83dbf851、735bc5796ea、68476fa29fc。Stable ID 以 candidate ID、generation、role、match ID、suffix 經 SHA-256 派生。');
table(s,[['變更','目的與效果'],['Explicit seed schedule','明確執行同 seed 重複 run，支援成對比較'],['Deterministic mode','統一 EA、JVM match、LLM request 與 runtime contract'],['Reflection correlation ID','以 SHA-256 stable ID 取代 uuid4()，消除非行為 artifact 差異'],['Regression 與 smoke configs','新增 request ID regression test，以及 3×2 / 4×10 configs']],[415,957],265,365,26);
conclusion(s,'原 correlation ID 未送入模型，仍會造成同 seed artifact 差異');

s=slide('後續初始化修正：固定 strategy identity','temperature=0 下，9 個 LLM slots 仍收到不同生成目標','3：後續初始化修正','prompts/initial_policy_variants.txt。1009、1007、1008 deterministic configs 已切換回 llm_generated_policies。本頁描述報告中的後續修正，不能視為此次 mock runs 的實際 LLM 生成結果。');
table(s,[['項目','修正後行為'],['初始化模式','1009、1007、1008 configs 使用 llm_generated_policies'],['Policy slots','每個非 WorkerRush slot 指定固定的 strategy identity'],['不同生成目標','9 個 LLM 初始 policy 接收不同目標，同 seed 重跑維持固定身份']],[365,1007],275,300,28);
text(s,'Strategy identities 來自 prompts/initial_policy_variants.txt。',160,622,1352,60,27);
conclusion(s,'這是後續初始化設計修正，實際 LLM 的結果仍需重跑驗證');

s=slide('可重現性的適用範圍','固定環境下的 deterministic contract，與現有證據的界線','5');
table(s,[['範圍','目前結論'],['固定環境 contract','同機器、同 model file、同 llama.cpp build、同 JVM、同 config'],['本次已驗證','EA seed propagation、candidate identity、selection / mutation、self-play 與行為 artifact'],['待補證據','實際 OpenAI-compatible LLM 生成層的 end-to-end reproducibility'],['跨環境限制','不同硬體、quantization、llama.cpp build 或 JVM 不承諾 bitwise 相容']],[370,1002],263,365,26);
conclusion(s,'Mock 一致性支持 EA 層可重現，模型生成層尚未完成驗證');

s=slide('Validation 與下一步','先完成實際 LLM 重複 run，再補齊模型生成層證據','5、6','報告驗證：python -m unittest discover -s tests -q：518 tests passed、1 skipped。本簡報引用報告結果，未重新執行專案測試或實驗。下一步為有 CUDA 的 5080 host，依同一份 config 執行實際 LLM pipeline。');
table(s,[['檢查或工作','狀態'],['Unit tests（報告所載）','518 tests passed，1 skipped'],['Deterministic mock gates','3×2 與 4×10 均完成，同 seed 行為一致'],['5080 host 實際 LLM run','待執行，依同一份 deterministic config 補測']],[440,932],275,285,29);
text(s,'下一步在有 CUDA 的 5080 host 執行實際 LLM pipeline，依同 seed 重複 run 比對模型生成與演化 artifact。',160,615,1352,95,30);
conclusion(s,'目前進度：EA/mock 證據完成，實際 LLM end-to-end 證據待補',770);

const candidate=path.join(build,'candidate.pptx');
await (await PresentationFile.exportPptx(deck)).save(candidate);
const result=await finalizePresentation({
 workspaceDir,candidatePath:candidate,finalPath:output,
 pythonExecutable:path.join(runtime,'python/python.exe'),
 integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','15925800,8963025','--validate-heading-fit',...tableSlides.flatMap(n=>['--require-native-table-slide',String(n)])],
 explicitTotalSlideCount:14,requiredNativeTableOwnerSlides:tableSlides,requiredNativeChartOwnerSlides:[],
 fontPolicy:{basis:'reference',families:[F],referencePath:reference,referenceSha256:createHash('sha256').update(await fs.readFile(reference)).digest('hex')},
 verifyArtifactToolImport:true,receiptPath:path.join(build,`${path.basename(output)}.validation.json`),
});
const finalDeck=await PresentationFile.importPptx(await FileBlob.load(output));
await fs.mkdir(path.join(build,'render'),{recursive:true});
for(let i=0;i<finalDeck.slides.items.length;i++){
 const rendered=await finalDeck.slides.items[i].export({format:'png',scale:1});
 await fs.writeFile(path.join(build,'render',`slide-${i+1}.png`),new Uint8Array(await rendered.arrayBuffer()));
}
console.log(JSON.stringify({output:result.finalPath,receipt:result.receiptPath,slides:finalDeck.slides.items.length}));
