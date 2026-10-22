import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {renderPrimary} from './visual_pages_a.mjs';
import {renderSecondary} from './visual_pages_b.mjs';
import {stabilityPages,renderStability,STABILITY_SLIDE_COUNT,STABILITY_CHART_SLIDES,STABILITY_TABLE_SLIDES} from './stability_slides.mjs';

const work=path.dirname(fileURLToPath(import.meta.url));
const build=path.join(work,'.codex-build/opponent-pool-template-restored');
const runtime='C:/Users/cinna/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const skill='C:/Users/cinna/.codex/plugins/cache/openai-primary-runtime/presentations/26.1020.11127/skills/presentations';
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const {importRuntimeModule}=await import(pathToFileURL(path.join(skill,'container_tools/runtime_helpers.mjs')).href);
const {Presentation,PresentationFile,FileBlob}=await importRuntimeModule('@oai/artifact-tool');
const {finalizePresentation,applyPresentationChartFont}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const source=JSON.parse(await fs.readFile(path.join(work,'visual_source.json'),'utf8'));
if(source.slides.length!==source.source_slide_count || source.slides.some(p=>!p.title||!p.notes))throw new Error('Incomplete edited source');
const poolContent=JSON.parse(await fs.readFile(path.join(work,'opponent_pool_content.json'),'utf8'));
const reportData=JSON.parse(await fs.readFile(path.join(work,'stability_report_data.json'),'utf8'));
const reportPath=path.resolve(work,'../..',reportData.source.path);
if(createHash('sha256').update(await fs.readFile(reportPath)).digest('hex')!==reportData.source.sha256)throw new Error('Stability report changed; refresh the extracted data');
const slides=[...source.slides.map(p=>({...p,...poolContent[p.page]})),...stabilityPages(reportData)];
if(slides.length!==source.source_slide_count+STABILITY_SLIDE_COUNT)throw new Error('Incomplete result section');
const editedPath=path.join(work,'deliverables',source.source_file);
if(createHash('sha256').update(await fs.readFile(editedPath)).digest('hex')!==source.source_sha256)throw new Error('The edited source changed; refresh the source snapshot before building');
await fs.mkdir(build,{recursive:true});
const C={bg:'#FCF8F5',ink:'#47171C',text:'#423C3B',rose:'#CF8792',blush:'#DEB4BA',gold:'#FAEDC6',pale:'#F4E7E7',muted:'#887575',light:'#EEE9E4'};
const F='Source Han Serif TW';
function T(s,value,x,y,w,h,{size=30,color=C.text,bold=false,align='left'}={}){
  const o=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  o.text=value;o.text.insets=0;o.text.style={typeface:F,fontSize:size,color,bold,alignment:align,verticalAlignment:'middle',autoFit:'none'};return o;
}
function R(s,x,y,w,h,{fill=C.bg,line='none',width=1,radius=false}={}){
  return s.shapes.add({geometry:radius?'roundRect':'rect',position:{left:x,top:y,width:w,height:h},fill,line:{fill:line,width:line==='none'?0:width},...(radius?{borderRadius:16}:{})});
}
function B(s,value,x,y,w,h,{fill=C.blush,line='none',size=30,color=C.text,bold=false,align='center'}={}){
  const o=R(s,x,y,w,h,{fill,line,radius:true});o.text=value;o.text.insets=12;o.text.style={typeface:F,fontSize:size,color,bold,alignment:align,verticalAlignment:'middle',autoFit:'none'};return o;
}
function Cn(s,a,b,fromSide='right',toSide='left',{color=C.rose,width=2}={}){
  return s.shapes.connect(a,b,{kind:'elbow',fromSide,toSide,line:{fill:color,width},tail:{type:'triangle',width:'med',length:'med'}});
}
function L(s,x1,y1,x2,y2,{color=C.rose,width=2,arrow=false}={}){
  return s.shapes.add({geometry:'connector',kind:'straight',position:{left:Math.min(x1,x2),top:Math.min(y1,y2),width:Math.abs(x2-x1),height:Math.abs(y2-y1),horizontalFlip:x2<x1,verticalFlip:y2<y1},line:{fill:color,width},...(arrow?{tail:{type:'triangle',width:'med',length:'med'}}:{})});
}
function tag(s,v,x,y,w,{fill=C.blush,size=24}={}){return B(s,v,x,y,w,44,{fill,size,bold:true});}
function dot(s,v,x,y,{fill=C.rose,size=24,r=24}={}){
  const o=s.shapes.add({geometry:'ellipse',position:{left:x,top:y,width:r*2,height:r*2},fill,line:{fill:'none',width:0}});o.text=v;o.text.insets=0;o.text.style={typeface:F,fontSize:size,color:C.ink,bold:true,alignment:'center',verticalAlignment:'middle'};return o;
}
function tiles(s,n,x,y,{cols=5,cell=42,gap=10,fill=C.blush,labelPrefix=''}={}){
  return Array.from({length:n},(_,i)=>B(s,labelPrefix?labelPrefix+(i+1):'',x+(i%cols)*(cell+gap),y+Math.floor(i/cols)*(cell+gap),cell,cell,{fill,size:21}));
}
const sub=(s,v)=>T(s,v,66,122,1518,50,{size:27,color:C.muted});
const foot=(s,v)=>T(s,v,66,848,1465,46,{size:24,color:C.ink});
const H={T,R,B,Cn,L,tag,dot,tiles,C,sub,foot,F,applyChartFont:applyPresentationChartFont};
const templatePath=path.resolve(work,'../template/EAGLE.potx');
const templateProto=(await PresentationFile.importPptx(await FileBlob.load(templatePath))).toProto();
const master=templateProto.layouts.find(l=>l.type==='master');
const artwork=master.elements.find(e=>e.name==='EAGLE geometric full-slide background');
// A native background fill survives both PowerPoint and Artifact Tool rendering.
const backgroundFill=artwork?.fill ?? master.background.fill;
if(!backgroundFill?.imageReference)throw new Error('EAGLE template background is missing');
templateProto.slides=[];templateProto.charts=[];
for(const layout of templateProto.layouts){
  layout.background={fill:backgroundFill};
  layout.elements=layout.elements.filter(e=>e!==artwork&&!e.paragraphs?.some(p=>p.runs?.some(r=>r.fieldType==='slidenum')));
}
let deck=Presentation.load(templateProto);
const blank=deck.layouts.items.find(l=>l.name==='空白');
let md='# EAGLE Opponent Pool 圖解流程\n\n搜尋採 self_play 與 tournament-v1，使用單一 Game Performance fitness、語意同分處理、靜態突變與父代快取重用。正式 Final Test 是獨立的固定基準測試。\n\n保留刪頁後的 38 頁順序。來源 SHA-256：`'+source.source_sha256+'`。\n';
for(const p of slides){
  const s=deck.slides.add({layoutId:blank.id,width:1672,height:941});
  s.background.fill={type:'image',imageReference:backgroundFill.imageReference};
  T(s,p.title,64,36,1544,82,{size:p.title.length>29?43:53,color:C.ink,bold:true});
  if(!renderPrimary(s,p,H)&&!renderSecondary(s,p,H)&&!renderStability(s,p,H,reportData))throw new Error('No visual layout for '+p.page);
  T(s,`${p.page} / ${slides.length}`,1450,906,155,28,{size:19,color:C.muted,align:'right'});
  const notes=p.page===5?'slot 是固定 Java 模板中的可替換位置。bundle 先定義每個 slot 的型別、合法值與表達式選單；候選只保存值或 choice_id。範例中 worker_target 從 2 到 8 的整數選 6，attack_weight 從 0、0.25、0.5、0.75、1 選 0.75，target_policy 選 lowest_hp。attack_weight、target_policy 與其選單為型別教學示例，不代表目前 bundle 的實際欄位。number 同樣是有限離散選單，0.6 在此例不合法。expression_choice 保存最低血量選項的 ID，由 bundle 中預先定義的 Java 表達式取代模板 marker，不生成新表達式。完整 genome 必須包含該 bundle 的全部 slot，不能只交這三項。\n\n程式來源：eagle/generation/framework_slots.py:304-340、445-470。worker_target 實例來源：configs/framework_bundles/fixed_worker_combat/bundle.json。\n\n'+p.notes:p.notes;
  s.speakerNotes.textFrame.setText(notes);
  md+='\n## '+p.page+'. '+p.title+'\n\n'+notes+'\n';
}
await fs.writeFile(path.join(work,'visual_workflow_explained.md'),md.trimEnd()+'\n');
const numbered=deck.toProto();
for(const [i,s] of numbered.slides.entries()){
  const footer=s.elements.at(-1),run=footer.paragraphs[0].runs[0];
  footer.name='Slide Number';footer.placeholderType='sldNum';footer.placeholderIndex=90;
  footer.paragraphs[0].runs=[{...run,id:`{${randomUUID().toUpperCase()}}`,text:String(i+1),fieldType:'slidenum'},{...run,text:` / ${slides.length}`}];
}
const masterNumber=structuredClone(numbered.slides[0].elements.at(-1));
masterNumber.paragraphs[0].runs=masterNumber.paragraphs[0].runs.slice(0,1);
numbered.layouts.find(l=>l.type==='master').elements.push(masterNumber);
deck=Presentation.load(numbered);
const candidatePath=path.join(build,'candidate.pptx');
await(await PresentationFile.exportPptx(deck)).save(candidatePath);
const finalPath=path.join(work,'deliverables/EAGLE_20261021_opponent_pool_template_restored.pptx');
const receiptPath=path.join(build,'visual-workflow.validation.json');
const result=await finalizePresentation({workspaceDir:work,candidatePath,finalPath,pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15925800,8963025','--validate-heading-fit',...STABILITY_TABLE_SLIDES.flatMap(n=>['--require-native-table-slide',String(n)])],explicitTotalSlideCount:slides.length,requiredNativeTableOwnerSlides:STABILITY_TABLE_SLIDES,requiredNativeChartOwnerSlides:STABILITY_CHART_SLIDES,nativeChartTargetApplication:'portable',materializeLiteralChartWorkbooks:true,fontPolicy:{basis:'reference',families:[F],referencePath:editedPath,referenceSha256:source.source_sha256},verifyArtifactToolImport:true,receiptPath});
const final=await PresentationFile.importPptx(await FileBlob.load(result.finalPath));
await fs.mkdir(path.join(build,'render'),{recursive:true});
for(let i=0;i<final.slides.items.length;i++){
  const png=await final.slides.items[i].export({format:'png',scale:1});
  await fs.writeFile(path.join(build,'render',`slide-${i+1}.png`),new Uint8Array(await png.arrayBuffer()));
  console.log('render',i+1,'/',slides.length);
}
console.log(JSON.stringify({finalPath,receiptPath,slides:slides.length,sourceSha256:source.source_sha256,reportSha256:reportData.source.sha256}));
