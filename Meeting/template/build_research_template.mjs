import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {pathToFileURL,fileURLToPath} from 'node:url';

const root=path.dirname(fileURLToPath(import.meta.url));
const build=path.join(root,'.codex-build/infographic-template');
const skill='C:/Users/cinna/.codex/plugins/cache/openai-primary-runtime/presentations/26.1020.11127/skills/presentations';
const runtime='C:/Users/cinna/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const source=path.resolve(root,'../20261021_current_workflow/deliverables/EAGLE_20261021_opponent_pool_template_restored.pptx');
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const {importRuntimeModule}=await import(pathToFileURL(path.join(skill,'container_tools/runtime_helpers.mjs')).href);
const {Presentation,PresentationFile,FileBlob}=await importRuntimeModule('@oai/artifact-tool');
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const proto=(await PresentationFile.importPptx(await FileBlob.load(source))).toProto();
// Use the approved editable compositions rather than rebuilding generic text pages.
const examples=[2,5,22,18,40,42,44,36];
proto.slides=examples.map(n=>proto.slides[n-1]);
const chartIds=new Set(proto.slides.flatMap(s=>s.elements.flatMap(e=>e.chartReference?[e.chartReference.id]:[])));
proto.charts=proto.charts.filter(c=>chartIds.has(c.id));
for(const s of proto.slides){
  const title=s.elements.find(e=>e.bbox?.xEmu===64*9525&&e.bbox?.yEmu===36*9525);
  if(!title?.paragraphs?.length)throw new Error('Example title is missing');
  title.placeholderType='title';title.placeholderIndex=0;
  const subtitle=s.elements.find(e=>e.bbox?.yEmu===122*9525);
  if(subtitle){subtitle.placeholderType='subTitle';subtitle.placeholderIndex=1;}
  s.elements=s.elements.filter(e=>e.placeholderType!=='sldNum');
}
const sourceMaster=proto.layouts.find(l=>l.type==='master');
for(const level of sourceMaster.bodyLevelStyles)level.paragraphStyle.bulletCharacter='';
const masterNumber=sourceMaster.elements.find(e=>e.placeholderType==='sldNum');
delete masterNumber.placeholderType;delete masterNumber.placeholderIndex;
masterNumber.paragraphs[0].runs=[{...masterNumber.paragraphs[0].runs[0],id:'{'+randomUUID().toUpperCase()+'}',text:'1',fieldType:'slidenum'}];
let deck=Presentation.load(proto);
const currentLayouts=deck.layouts.items.slice(13);
if(currentLayouts.length!==6 || chartIds.size!==3)throw new Error('Unexpected template or source example structure');
const layoutNames=['圖解流程','選項與對應','矩陣與規則','結果圖表','比較與表格','時間與證據'];
const normalized=deck.toProto();
for(const [i,layout] of currentLayouts.entries()){
  const saved=normalized.layouts.find(l=>l.id===layout.id);
  saved.name=layoutNames[i];saved.elements=[];
}
deck=Presentation.load(normalized);
for(const layout of deck.layouts.items.slice(13)){
  for(const [type,index,text,x,y,w,h,size,color,bold] of [
    ['title',0,'[研究主題]',64,36,1544,82,53,'#47171C',true],
    ['subtitle',1,'[必要的實驗口徑或圖例]',66,122,1518,50,27,'#887575',false]
  ]){
    const p=layout.placeholders.add({type,index,text,geometry:'textbox',position:{left:x,top:y,width:w,height:h}});
    p.text.insets=0;p.text.style={typeface:'Source Han Serif TW',fontSize:size,color,bold,verticalAlignment:'middle',autoFit:'none'};
  }
}
const layoutMapping=[0,1,0,2,3,4,3,5];
for(const [i,s] of deck.slides.items.entries()){
  s.setLayout(deck.layouts.items[13+layoutMapping[i]]);
  const prior=s.speakerNotes.text;
  s.speakerNotes.textFrame.setText('頁型示例，取自 2026-10-21 Opponent Pool 簡報第 '+examples[i]+' 頁。此頁保留該來源的內容與數值，僅供版面與可編輯物件參考；建立新簡報時須依新來源替換。\n\n'+prior);
}
await fs.mkdir(build,{recursive:true});
const candidatePath=path.join(build,'candidate.pptx');
await(await PresentationFile.exportPptx(deck)).save(candidatePath);
execFileSync(path.join(runtime,'python/python.exe'),[path.join(root,'prepare_template.py'),'restore-workbooks',source,candidatePath,examples.join(',')],{stdio:'inherit'});
const output=path.join(build,'checked/reference.pptx');
await fs.mkdir(path.dirname(output),{recursive:true});
await finalizePresentation({workspaceDir:root,candidatePath,finalPath:output,pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15925800,8963025','--validate-heading-fit','--require-native-table-slide','6'],explicitTotalSlideCount:8,requiredNativeTableOwnerSlides:[6],requiredNativeChartOwnerSlides:[5,6,7],nativeChartTargetApplication:'portable',materializeLiteralChartWorkbooks:true,fontPolicy:{basis:'reference',families:['Source Han Serif TW'],referencePath:source,referenceSha256:createHash('sha256').update(await fs.readFile(source)).digest('hex')},verifyArtifactToolImport:true,receiptPath:path.join(build,'template.validation.json')});
const final=await PresentationFile.importPptx(await FileBlob.load(output));
await fs.mkdir(path.join(build,'render'),{recursive:true});
for(let i=0;i<final.slides.items.length;i++){
  const png=await final.slides.items[i].export({format:'png',scale:1});
  await fs.writeFile(path.join(build,'render','slide-'+(i+1)+'.png'),new Uint8Array(await png.arrayBuffer()));
}
await fs.copyFile(path.join(build,'render/slide-1.png'),path.join(root,'preview.png'));
await fs.copyFile(output,path.join(root,'reference.pptx'));
execFileSync(path.join(runtime,'python/python.exe'),[path.join(root,'prepare_template.py'),'potx',output,path.join(build,'EAGLE.potx')],{stdio:'inherit'});
console.log(JSON.stringify({output,examples,slides:8,charts:chartIds.size,layouts:deck.layouts.items.length-deck.masters.items.length}));
