import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';

const work=path.dirname(fileURLToPath(import.meta.url));
const build=path.join(work,'.codex-build/manual-local-coach');
const cloud='J:/我的雲端硬碟/Lab/Meeting/EAGLE_20261022_opponent_pool_data_only.pptx';
const runtime='C:/Users/cinna/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const skill='C:/Users/cinna/.codex/plugins/cache/openai-primary-runtime/presentations/26.1020.11127/skills/presentations';
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const {importRuntimeModule}=await import(pathToFileURL(path.join(skill,'container_tools/runtime_helpers.mjs')).href);
const {Presentation,PresentationFile}=await importRuntimeModule('@oai/artifact-tool');
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
await fs.mkdir(build,{recursive:true});
await fs.mkdir(path.join(build,'validated'),{recursive:true});
const source=path.join(build,'cloud-before.pptx');
try{await fs.copyFile(cloud,source,1);}catch(e){if(e.code!=='EEXIST')throw e;}
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const sourceHash=hash(await fs.readFile(source));
const sourceCount=Number(execFileSync(path.join(runtime,'python/python.exe'),['-c',"import sys,zipfile,xml.etree.ElementTree as E; z=zipfile.ZipFile(sys.argv[1]); print(len(E.fromstring(z.read('ppt/presentation.xml')).find('{http://schemas.openxmlformats.org/presentationml/2006/main}sldIdLst')))",source],{encoding:'utf8'}).trim());
// Author only the changed foregrounds; importing the manually saved full deck can fail in the renderer.
const edited=Presentation.create({slideSize:{width:1672,height:941}});
const local=edited.slides.add(),coach=edited.slides.add();
const F='Source Han Serif TW';
const C={ink:'#47171C',text:'#423C3B',rose:'#CF8792',blush:'#DEB4BA',pale:'#F4E7E9',gold:'#FAEDC6',bg:'#FCF8F5',muted:'#897574'};
function text(s,value,x,y,w,h,size=28,bold=false,color=C.text,align='left'){
  const o=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  o.text=value;o.text.insets=0;o.text.style={typeface:F,fontSize:size,bold,color,alignment:align,verticalAlignment:'middle',autoFit:'none'};return o;
}
function box(s,value,x,y,w,h,fill=C.pale,size=28){
  const o=s.shapes.add({geometry:'roundRect',position:{left:x,top:y,width:w,height:h},fill,line:{fill:'none',width:0},borderRadius:16});
  o.text=value;o.text.insets=12;o.text.style={typeface:F,fontSize:size,color:C.ink,alignment:'center',verticalAlignment:'middle',autoFit:'none'};return o;
}
function arrow(s,x,y,w,h=0){s.shapes.add({geometry:'connector',kind:'straight',position:{left:x,top:y,width:w,height:h},line:{fill:C.rose,width:3},tail:{type:'triangle',width:'med',length:'med'}});}
text(local,'Framework 的 local 演化流程',64,36,1544,82,53,true,C.ink);
text(local,'演化的是完整 JSON 槽位基因，Java 框架與合法選單保持固定',66,122,1518,50,27,false,C.muted);
const phases=[
  ['初始化 G0','每個槽位從合法範圍抽值\n為每位候選組成完整基因'],
  ['逐槽交配','每個槽位各自從兩位父代擇一\n組成子代的完整基因'],
  ['單槽突變','若觸發突變，最多改一個槽位\n換成另一個合法值'],
];
phases.forEach(([title,body],i)=>{
  const x=80+i*530;
  text(local,title,x,250,450,65,39,true,C.ink,'center');
  box(local,body,x,350,450,150,i===2?C.gold:C.pale,29);
  if(i<2)arrow(local,x+460,425,60);
});
box(local,'完整 JSON 基因',160,660,370,90,C.blush,32);
arrow(local,550,705,95);
box(local,'填入凍結 Java 模板',665,660,430,90,C.pale,32);
arrow(local,1115,705,95);
box(local,'驗證、編譯與對戰',1230,660,360,90,C.gold,30);
text(local,'G0 初始化一次。後續世代由選出的父代交配、突變，再評估子代',80,555,1510,55,29);
text(local,'local 演化期間不呼叫 LLM。genome 代表一位候選的完整槽位設定',66,848,1465,46,25,false,C.ink);
local.speakerNotes.textFrame.setText('local 模式先依凍結 bundle 的合法槽位範圍，為 G0 每位候選採樣完整 control_genome。後續交配對每個槽位獨立選取父代 A 或 B 的值。若指派突變，選一個有替代值的槽位，改成不同的合法值；沒有可變槽位時維持原值。完整基因通過驗證後填入固定 Java 模板，再進行驗證、編譯、Integration、語意探針及 MicroRTS 評估。local 演化不呼叫候選階段 LLM。來源：docs/architecture/framework_slots.md:15-22；eagle/generation/framework_slots.py:267-340；eagle/operators/framework_slots.py:65-200。');

text(coach,'Framework 含 Coach 的完整流程',64,36,1544,82,53,true,C.ink);
text(coach,'llm_coach 為可選模式，目前這批 local 實驗未啟用',66,122,1518,50,27,false,C.muted);
const topY=225,midY=440,botY=670;
box(coach,'準備並凍結 framework\nJava 模板與合法槽位選單',65,topY,430,105,C.pale,28);
box(coach,'LLM 為每位初代候選\n選出完整 JSON 基因',620,topY,430,105,C.gold,29);
box(coach,'填入 Java、驗證與編譯\nG0 對戰並記錄結果',1175,topY,430,105,C.pale,28);
arrow(coach,505,topY+52,105);arrow(coach,1060,topY+52,105);
text(coach,'每個演化世代',65,365,400,50,30,true,C.ink);
box(coach,'選父代，逐槽交配\n保留突變前子代基因',65,midY,430,105,C.pale,28);
box(coach,'父代 A 最差單場\nMatch Commentator 賽評',620,midY,430,105,C.blush,27);
box(coach,'Coach 讀賽評與全場摘要\n回傳完整子代 JSON 基因',1175,midY,430,105,C.gold,27);
arrow(coach,505,midY+52,105);arrow(coach,1060,midY+52,105);
text(coach,'指派 Strategy mutation 時啟用',620,560,985,38,24,false,C.muted,'center');
arrow(coach,1390,555,0,95);
box(coach,'驗證 JSON，填入固定 Java\n編譯、語意探針與子代對戰',1175,botY,430,105,C.pale,27);
box(coach,'父代與子代合併選擇\n留下下一代候選',620,botY,430,105,C.blush,28);
box(coach,'維護 Opponent Pool\n到期凍結 roster 並刷新重評',65,botY,430,105,C.pale,26);
// Native connectors carry the loop and keep the workflow editable.
coach.shapes.add({geometry:'connector',kind:'straight',position:{left:1060,top:botY+52,width:105,height:0,horizontalFlip:true},line:{fill:C.rose,width:3},tail:{type:'triangle',width:'med',length:'med'}});
coach.shapes.add({geometry:'connector',kind:'straight',position:{left:505,top:botY+52,width:105,height:0,horizontalFlip:true},line:{fill:C.rose,width:3},tail:{type:'triangle',width:'med',length:'med'}});
text(coach,'未達停止條件時，回到父代選擇。搜尋結束後，使用固定基準進行 Final Test',65,792,1540,43,24,false,C.ink);
text(coach,'Coach 回覆不合法：保留突變前基因並標記失敗。未指派突變時，交配子代直接進入評估',66,848,1465,46,23,false,C.ink);
coach.speakerNotes.textFrame.setText('完整 llm_coach 路徑：準備或載入 framework 並凍結 bundle。LLM 為每個 G0 候選選擇完整合法 control_genome，之後本地渲染 Java、驗證、編譯、Integration、語意探針與對戰。每代選父代並逐槽交配。指派 Strategy mutation 時，使用已評估的 mutation-context parent A 作證據，不使用尚未評估子代的對戰。取父代 A 恰好一場最差已完成對戰，由 Match Commentator 診斷；Coach 同時收到賽評、父代全場摘要、父代與交配後子代的基因、凍結 bundle，並回傳完整合法子代基因。未指派 Strategy mutation 的子代直接進入評估。Coach 失敗時保留突變前完整子代基因與 lineage，標記 reflection 失敗，不隨機補值或部分套用；初代選值失敗保留採樣基因並標記 initialization 失敗。下游評估後進行父子代選擇；維護 opponent pool，快照刷新時依協定重評，再進入下一代。完成搜尋後進行獨立固定基準 Final Test。此圖介紹可選模式，目前這批實驗使用 local。來源：docs/architecture/framework_slots.md:15-75；eagle/operators/strategy.py:448-865；eagle/operators/framework_slots.py:65-200；docs/eagle_architecture_spec.md 的 opponent-pool 協定。');

const authored=path.join(build,'authored.pptx');
await(await PresentationFile.exportPptx(edited)).save(authored);
await finalizePresentation({workspaceDir:work,candidatePath:authored,finalPath:path.join(build,'validated/authoring.pptx'),pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15925800,8963025','--validate-heading-fit'],explicitTotalSlideCount:2,fontPolicy:{basis:'reference',families:[F],referencePath:source,referenceSha256:sourceHash},verifyArtifactToolImport:true,receiptPath:path.join(build,'authoring.validation.json')});
// Splice only authored foreground/notes into the authoritative package to retain manual edits.
execFileSync(path.join(runtime,'python/python.exe'),[path.join(work,'merge_manual_local_coach.py'),source,authored,path.join(build,'candidate.pptx')],{stdio:'inherit'});
const finalPath=path.join(work,'deliverables/EAGLE_20261022_opponent_pool_local_coach.pptx');
for(const [validator,args] of [['inspect_presentation_package_integrity.py',[]],['inspect_presentation_layout_geometry.py',['--expected-slide-size-emu','15925800,8963025','--validate-heading-fit']]]){
  const report=execFileSync(path.join(runtime,'python/python.exe'),[path.join(skill,'container_tools',validator),path.join(build,'candidate.pptx'),...args],{encoding:'utf8'});
  await fs.writeFile(path.join(build,validator+'.json'),report);
}
await fs.copyFile(path.join(build,'candidate.pptx'),finalPath,1);
await fs.writeFile(path.join(build,'source.sha256'),sourceHash+'\n');
console.log(JSON.stringify({finalPath,sourceHash,slides:sourceCount+1,cloudDestination:cloud}));
