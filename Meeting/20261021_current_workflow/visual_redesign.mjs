import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {renderPrimary} from './visual_pages_a.mjs';
import {renderSecondary} from './visual_pages_b.mjs';

const work=path.dirname(fileURLToPath(import.meta.url));
const build=path.join(work,'.codex-build/visual-redesign');
const runtime='C:/Users/cinna/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const skill='C:/Users/cinna/.codex/plugins/cache/openai-primary-runtime/presentations/26.1020.11127/skills/presentations';
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const {importRuntimeModule}=await import(pathToFileURL(path.join(skill,'container_tools/runtime_helpers.mjs')).href);
const {Presentation,PresentationFile,FileBlob}=await importRuntimeModule('@oai/artifact-tool');
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const source=JSON.parse(await fs.readFile(path.join(work,'visual_source.json'),'utf8'));
if(source.slides.length!==source.source_slide_count || source.slides.some(p=>!p.title||!p.notes))throw new Error('Incomplete edited source');
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
const H={T,R,B,Cn,L,tag,dot,tiles,C,sub,foot};
const deck=Presentation.create({slideSize:{width:1672,height:941}});
let md='# EAGLE 圖解流程\n\n依刪頁後的簡報順序與內容重製。來源 SHA-256：`'+source.source_sha256+'`。\n';
for(const p of source.slides){
  const s=deck.slides.add();s.background.fill=C.bg;
  T(s,p.title,64,36,1544,82,{size:p.title.length>29?43:53,color:C.ink,bold:true});
  if(!renderPrimary(s,p,H)&&!renderSecondary(s,p,H))throw new Error('No visual layout for '+p.page);
  T(s,`${p.page} / ${source.slides.length}`,1450,906,155,28,{size:19,color:C.muted,align:'right'});
  const raw=p.texts.filter(v=>v!==String(p.page)).join('\n')+'\n'+p.tables.map(t=>t.map(r=>r.join(' / ')).join('\n')).join('\n');
  s.speakerNotes.textFrame.setText(p.notes+'\n\n保留的原稿文字：\n'+raw);
  md+='\n## '+p.page+'. '+p.title+'\n\n'+p.notes+'\n\n原稿補充：\n'+raw+'\n';
}
await fs.writeFile(path.join(work,'visual_workflow_explained.md'),md.trimEnd()+'\n');
const candidatePath=path.join(build,'candidate.pptx');
await(await PresentationFile.exportPptx(deck)).save(candidatePath);
const finalPath=path.join(work,'deliverables/EAGLE_20261021_visual_workflow.pptx');
const receiptPath=path.join(build,'visual-workflow.validation.json');
const result=await finalizePresentation({workspaceDir:work,candidatePath,finalPath,pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15925800,8963025','--validate-heading-fit'],explicitTotalSlideCount:source.slides.length,requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],fontPolicy:{basis:'reference',families:[F],referencePath:editedPath,referenceSha256:source.source_sha256},verifyArtifactToolImport:true,receiptPath});
const final=await PresentationFile.importPptx(await FileBlob.load(result.finalPath));
await fs.mkdir(path.join(build,'render'),{recursive:true});
for(let i=0;i<final.slides.items.length;i++){
  const png=await final.slides.items[i].export({format:'png',scale:1});
  await fs.writeFile(path.join(build,'render',`slide-${i+1}.png`),new Uint8Array(await png.arrayBuffer()));
  console.log('render',i+1,'/',source.slides.length);
}
console.log(JSON.stringify({finalPath,receiptPath,slides:source.slides.length,sourceSha256:source.source_sha256}));
