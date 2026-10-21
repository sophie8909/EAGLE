import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {pathToFileURL,fileURLToPath} from 'node:url';
const workspaceDir=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(workspaceDir,'../..');
const build=path.join(workspaceDir,'.codex-build');
const skill=process.env.EAGLE_PRESENTATIONS_SKILL ?? 'C:/Users/cinna/.codex/plugins/cache/openai-primary-runtime/presentations/26.1020.11127/skills/presentations';
const runtime=process.env.EAGLE_ARTIFACT_RUNTIME ?? 'C:/Users/cinna/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const reference=process.env.EAGLE_TEMPLATE ?? 'C:/Users/cinna/.codex/skills/artifact-template-eagle-0917/assets/EAGLE.potx';
const finalPath=path.join(workspaceDir,'deliverables',process.env.EAGLE_DECK_NAME ?? 'EAGLE_20261021_complete_workflow.pptx');
const fontReference=process.env.EAGLE_FONT_REFERENCE ?? path.join(path.dirname(reference),'reference.pptx');
const {default:data}=await import('./content.mjs');
if(data.slides.length<35 || data.slides.some(s=>!s.notes || !s.sources?.length)) throw new Error('Incomplete workflow content');
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const {importRuntimeModule}=await import(pathToFileURL(path.join(skill,'container_tools/runtime_helpers.mjs')).href);
const {Presentation,PresentationFile,FileBlob}=await importRuntimeModule('@oai/artifact-tool');
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
await fs.mkdir(build,{recursive:true});await fs.mkdir(path.dirname(finalPath),{recursive:true});
const original=await PresentationFile.importPptx(await FileBlob.load(reference));
const proto=original.toProto();proto.slides=[];proto.charts=[];const deck=Presentation.load(proto);
const C={ink:'#47171C',body:'#423C3B',paper:'#FCF8F5',header:'#DEB4BA',rose:'#CF8792'};const F='Source Han Serif TW';
const tableOwners=[];
function text(s,value,x,y,w,h,size=30,color=C.body,bold=false,alignment='left'){
 const o=s.shapes.add({name:'text-'+s.shapes.items.length,geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 o.text=value;o.text.insets=0;o.text.style={typeface:F,fontSize:size,color,bold,alignment,autoFit:'none'};return o;
}
function table(s,values,widths,size=29){
 const rows=values.length,h=Math.min(570,rows*106),top=226;
 const t=s.tables.add({rows,columns:values[0].length,left:165,top,width:1342,height:h,columnWidths:widths,values});
 t.borders.assign({fill:C.body,width:0.65});t.cells.block({row:0,column:0,rowCount:rows,columnCount:values[0].length}).assign({margins:{left:14,right:14,top:12,bottom:10}});
 for(let r=0;r<rows;r++){t.rows[r].height=h/rows;for(let c=0;c<values[0].length;c++){const cell=t.getCell(r,c);cell.fill=r===0?C.header:C.paper;cell.text.style={typeface:F,fontSize:size,color:C.body,bold:r===0,autoFit:'none'};}}
 tableOwners.push(deck.slides.items.length);return t;
}
function node(s,n){const o=s.shapes.add({name:n.id,geometry:n.decision?'diamond':'rect',position:{left:n.x,top:n.y,width:n.w??360,height:n.h??100},fill:C.paper,line:{fill:C.ink,width:1.5}});o.text=n.text;o.text.style={typeface:F,fontSize:n.size??29,color:C.body,alignment:'center',verticalAlignment:'middle',autoFit:'none'};o.text.insets=8;return o;}
function diagram(s,spec){const nodes=new Map(spec.nodes.map(n=>[n.id,node(s,n)]));for(const e of spec.edges){s.shapes.connect(nodes.get(e[0]),nodes.get(e[1]),{kind:'elbow',fromSide:e[2]??'right',toSide:e[3]??'left',line:{fill:C.rose,width:2},tail:{type:'arrow',width:'med',length:'med'}});}for(const a of spec.labels??[])text(s,a.text,a.x,a.y,a.w??200,a.h??44,25,C.ink);}
let md=`# EAGLE 當前版本完整流程\n\n來源版本：${data.revision}。截點：${data.date}（Asia/Taipei）。\n\n本文件逐頁保留簡報內容、詳細解說與來源。教學示例不代表實驗量測。本次未執行新實驗，亦不以歷史分數代表現行策略效果。\n`;
for(let i=0;i<data.slides.length;i++){
 const d=data.slides[i];const s=deck.slides.add({layoutId:'/ppt/slideLayouts/slideLayout12.xml',width:1672,height:941});
 text(s,d.title,235,44,1202,104,d.title.length>25?43:48,C.ink,true,'center');
 if(d.subtitle)text(s,d.subtitle,180,162,1312,62,27,C.body,false,'center');
 if(d.type==='cover'){text(s,d.hero,215,326,1242,130,60,C.ink,true,'center');text(s,d.body.join('\n'),260,523,1152,176,33,C.body,false,'center');}
 else if(d.table)table(s,d.table,d.widths??(d.table[0].length===2?[340,1002]:[290,526,526]),d.size??29);
 else if(d.diagram)diagram(s,{...d.diagram,labels:d.diagramLabels??[]});
 else {const count=d.body.length;const step=count===3?167:132;d.body.forEach((v,j)=>text(s,v,185,242+j*step,1302,count===3?136:108,d.size??32));}
 if(d.foot)text(s,d.foot,185,786,1302,60,27,C.ink,true);
 // Keep the template's automatic slide number field; update its cached value after export.
 s.speakerNotes.textFrame.setText(`版本截點：${data.date}。程式版本：${data.revision}。\n${d.notes}\n\n程式來源（此版本的一基行號）：\n${d.sources.join('\n')}\n${d.example?'本頁數值／個體為說明演算法的教學示例，非實驗量測。':''}`);
 md+=`\n## ${i+1}. ${d.title}\n\n${d.subtitle??''}\n\n`;
 if(d.body)md+=d.body.map(x=>'- '+x).join('\n')+'\n';
 if(d.table)md+='\n'+d.table.map((row,j)=>'| '+row.map(cell=>cell.replaceAll('\n','<br>')).join(' | ')+' |'+(j===0?'\n| '+row.map(()=>'---').join(' | ')+' |':'')).join('\n')+'\n';
 if(d.diagram)md+='\n流程節點：'+d.diagram.nodes.map(n=>n.id+'='+n.text.replace(/\n/g,' / ')).join('；')+'\n連線：'+d.diagram.edges.map(e=>e[0]+' → '+e[1]).join('；')+'\n';
 md+=`\n${d.foot??''}\n\n詳細解說：${d.notes}\n\n來源：${d.sources.join('；')}\n`;
 if(d.example)md+='\n本頁為教學示例，非實驗量測。\n';
 for(const source of d.sources){const file=source.split(':')[0];await fs.access(path.join(root,file));}
}
await fs.writeFile(path.join(workspaceDir,'workflow_explained.md'),md);
const candidatePath=path.join(build,'candidate-ready.pptx');await(await PresentationFile.exportPptx(deck)).save(candidatePath);
execFileSync(path.join(runtime,'python/python.exe'),[path.join(root,'Meeting/20261013_current_workflow/native_numbers.py'),candidatePath],{stdio:'inherit'});
const result=await finalizePresentation({workspaceDir,candidatePath,finalPath,pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15925800,8963025','--validate-heading-fit',...tableOwners.flatMap(n=>['--require-native-table-slide',String(n)])],explicitTotalSlideCount:data.slides.length,requiredNativeTableOwnerSlides:tableOwners,requiredNativeChartOwnerSlides:[],fontPolicy:{basis:'reference',families:[F],referencePath:fontReference,referenceSha256:createHash('sha256').update(await fs.readFile(fontReference)).digest('hex')},verifyArtifactToolImport:true,receiptPath:path.join(build,path.basename(finalPath)+'.validation.json')});
const finalDeck=await PresentationFile.importPptx(await FileBlob.load(result.finalPath));await fs.mkdir(path.join(build,'render'),{recursive:true});
for(let i=0;i<finalDeck.slides.items.length;i++){const png=await finalDeck.slides.items[i].export({format:'png',scale:1});await fs.writeFile(path.join(build,'render',`slide-${i+1}.png`),new Uint8Array(await png.arrayBuffer()));console.log(`render ${i+1}/${finalDeck.slides.items.length}`);}
console.log(JSON.stringify({output:result.finalPath,slides:data.slides.length,tableOwners,receipt:result.receiptPath}));
