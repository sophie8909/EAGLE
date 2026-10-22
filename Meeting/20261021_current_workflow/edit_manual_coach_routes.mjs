import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createHash,randomUUID} from 'node:crypto';

const work=path.dirname(fileURLToPath(import.meta.url));
const build=path.join(work,'.codex-build/manual-coach-routes');
const runtime='C:/Users/cinna/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const skill='C:/Users/cinna/.codex/plugins/cache/openai-primary-runtime/presentations/26.1020.11127/skills/presentations';
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const {importRuntimeModule}=await import(pathToFileURL(path.join(skill,'container_tools/runtime_helpers.mjs')).href);
const {Presentation,PresentationFile,FileBlob}=await importRuntimeModule('@oai/artifact-tool');
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
await fs.mkdir(path.join(build,'output'),{recursive:true});
const source=path.join(build,'cloud-before.pptx');
await fs.copyFile('J:/我的雲端硬碟/Lab/Meeting/EAGLE_20261022_opponent_pool_data_only.pptx',source,1);
const sourceHash=createHash('sha256').update(await fs.readFile(source)).digest('hex');
const template=(await PresentationFile.importPptx(await FileBlob.load(path.resolve(work,'../template/EAGLE.potx')))).toProto();
const master=template.layouts.find(l=>l.type==='master');
const art=master.elements.find(e=>e.name==='EAGLE geometric full-slide background');
const background=art?.fill??master.background.fill;
if(!background.imageReference)throw new Error('Missing original EAGLE background');
template.slides=[];template.charts=[];
for(const layout of template.layouts){layout.background={fill:background};layout.elements=layout.elements.filter(e=>e!==art&&!e.paragraphs?.some(p=>p.runs?.some(r=>r.fieldType==='slidenum')));}
let deck=Presentation.load(template);
const s=deck.slides.add({layoutId:deck.layouts.items.find(l=>l.name==='空白').id,width:1672,height:941});
s.background.fill={type:'image',imageReference:background.imageReference};
const F='Source Han Serif TW',C={ink:'#47171C',text:'#423C3B',rose:'#CF8792',blush:'#DEB4BA',pale:'#F4E7E9',gold:'#FAEDC6',muted:'#897574'};
function text(v,x,y,w,h,size=28,bold=false,color=C.text,align='left'){
 const o=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 o.text=v;o.text.insets=0;o.text.style={typeface:F,fontSize:size,bold,color,alignment:align,verticalAlignment:'middle',autoFit:'none'};return o;
}
function box(v,x,y,w,h,fill=C.pale,size=28){
 const o=s.shapes.add({geometry:'roundRect',position:{left:x,top:y,width:w,height:h},fill,line:{fill:'none',width:0},borderRadius:16});
 o.text=v;o.text.insets=12;o.text.style={typeface:F,fontSize:size,color:C.ink,alignment:'center',verticalAlignment:'middle',autoFit:'none'};return o;
}
function connect(a,b){s.shapes.connect(a,b,{kind:'elbow',fromSide:'right',toSide:'left',line:{fill:C.rose,width:3},tail:{type:'triangle',width:'med',length:'med'}});}
text('50/50 子代生成流程',64,36,1544,82,53,true,C.ink);
text('新設定：先分流，再由 Coach 或傳統交配各自產生子代',66,122,1518,50,27,false,C.muted);
const framework=box('準備並凍結 framework\n固定 Java 與合法槽位選單',65,215,430,85,C.pale,27);
const initial=box('G0：Coach 為每位候選\n選出完整 JSON 基因',620,215,430,85,C.gold,27);
const initialEval=box('填入 Java、編譯與對戰\n建立已評估的初代族群',1175,215,430,85,C.pale,27);
connect(framework,initial);connect(initial,initialEval);
text('後續每代',65,345,330,50,32,true,C.ink);
const parent=box('選父代 A\n當代已評估族群',65,500,300,125,C.blush,29);
text('50% Coach',480,315,600,50,36,true,C.ink,'center');
const coach=box('最差單場交給 Commentator 賽評\nCoach 讀賽評與父代全場摘要\n直接產生完整 JSON 子代基因',480,375,600,140,C.gold,28);
text('50% 傳統演化',480,555,600,50,36,true,C.ink,'center');
const traditional=box('再選父代 B\n逐槽交配（rate 0.75）\nlocal 單槽突變（rate 1.0）',480,625,600,140,C.pale,28);
const evaluation=box('驗證完整 JSON 基因\n填入固定 Java\n編譯、語意探針與對戰',1250,500,355,125,C.blush,26);
connect(parent,coach);connect(parent,traditional);connect(coach,evaluation);connect(traditional,evaluation);
text('父代＋子代選下一代，維護對手池並重複演化。搜尋結束後進行 Final Test',65,787,1540,48,26,false,C.ink);
text('既有結果仍為 local，本頁為新設定。50/50 是抽樣機率；Coach 失敗不會轉走傳統路徑',66,848,1465,46,23,false,C.ink);
text('5 / 44',1450,906,155,28,19,false,C.muted,'right');
s.speakerNotes.textFrame.setText('本頁對應新 config：configs/experiments/1022_framework_coach50_traditional50_20x10_seed8_13_1run/qwen3_5_9b_framework_coach50_traditional50_20x10_seed8_13_1run.yaml。framework.evolution_mode=llm_coach，coach_offspring_probability=0.5。G0 沿用 Coach 模式，為每位候選選完整合法基因並評估。後續每位子代先從當代已評估族群選父代 A，再用獨立 seeded RNG 決定生成路徑。Coach 路徑只複製父代 A 的完整基因，取父代 A 恰好一場最差已完成對戰交給 Match Commentator，Coach 收到賽評與父代全場摘要後回傳完整合法基因。此路徑不選父代 B、不交配、不做 local 突變，且不受 mutation_rate 控制。傳統路徑再選父代 B，保留原有 crossover_rate=0.75 的逐槽交配或複製，並依 mutation_rate=1.0 進行最多一槽的 local 突變。兩路共用固定 Java 渲染、驗證、編譯、Integration、語意探針與對手池對戰、父子代倖存選擇及後續 pool 更新與快照刷新重評。搜尋結束後執行獨立固定基準 Final Test。50/50 是依種子可重現的機率，不保證每代固定五名對五名。Coach 回覆不合法時保留原基因並標記 reflection 失敗，不會改走傳統路徑。既有簡報結果仍為 local，尚未執行此新 config。來源：eagle/evolution/offspring.py 的 _iter_framework_slot_offspring；docs/architecture/framework_slots.md；實作提交 4f37f5f6。');
const proto=deck.toProto(),footer=proto.slides[0].elements.at(-1),run=footer.paragraphs[0].runs[0];
footer.name='Slide Number';footer.placeholderType='sldNum';footer.placeholderIndex=90;
footer.paragraphs[0].runs=[{...run,id:`{${randomUUID().toUpperCase()}}`,text:'5',fieldType:'slidenum'},{...run,text:' / 44'}];
deck=Presentation.load(proto);
const candidate=path.join(build,'candidate.pptx');
await(await PresentationFile.exportPptx(deck)).save(candidate);
await finalizePresentation({workspaceDir:work,candidatePath:candidate,finalPath:path.join(build,'output/page.pptx'),pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15925800,8963025','--validate-heading-fit'],explicitTotalSlideCount:1,fontPolicy:{basis:'reference',families:[F],referencePath:source,referenceSha256:sourceHash},verifyArtifactToolImport:true,receiptPath:path.join(build,'validation.json')});
await fs.writeFile(path.join(build,'source.sha256'),sourceHash+'\n');
console.log(JSON.stringify({page:path.join(build,'output/page.pptx'),sourceHash}));
