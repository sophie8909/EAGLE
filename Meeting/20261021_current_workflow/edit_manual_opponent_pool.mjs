import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createHash,randomUUID} from 'node:crypto';

const work=path.dirname(fileURLToPath(import.meta.url));
const build=path.join(work,'.codex-build/manual-opponent-pool');
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
function arrow(x,y,w){s.shapes.add({geometry:'connector',kind:'straight',position:{left:x,top:y,width:w,height:0},line:{fill:C.rose,width:3},tail:{type:'triangle',width:'med',length:'med'}});}
text('對手池（Opponent Pool）',64,36,1544,82,53,true,C.ink);
text('保存可供對戰的內建與歷代策略，再從池中挑出本次評估的 10 名對手',66,122,1518,50,27,false,C.muted);
text('策略來源',75,225,350,58,35,true,C.ink,'center');
box('起始：10 個內建對手',65,310,370,80,C.pale,29);
box('G0 已評估的初代候選\n之後各代已評估的子代',65,440,370,130,C.gold,28);
arrow(450,430,70);
text('對手池',555,225,470,58,40,true,C.ink,'center');
box('累積通過入池的歷代策略\n也保留池內的內建對手\n\n本次容量 50 名\n包含 4 個固定保護對手',550,305,480,285,C.blush,30);
arrow(1045,430,70);
text('本次對戰名單：10 名',1145,225,465,58,35,true,C.ink,'center');
box('4 個固定保護對手\nAllInBot、Mayari、COAC、TMA',1140,305,470,110,C.pale,26);
text('＋',1300,422,150,50,39,true,C.ink,'center');
box('6 名從池內非保護成員抽選\n可能是內建或歷代策略',1140,480,470,110,C.gold,27);
text('G0 使用全部 10 個內建對手。後續在 G1、G6、G11…刷新並凍結名單',65,625,1540,48,28,false,C.ink);
text('入池與替換',65,700,300,50,32,true,C.ink);
box('完成評估並去重\n池未滿時加入',390,695,470,105,C.pale,28);
box('池已滿：挑戰一名非保護對手，共 18 場\n勝場多於敗場才替換，平手保留原成員',900,695,710,105,C.gold,26);
text('10 是當次名單大小。繁殖父代另從當代族群選出；新入池策略需等下次刷新才可能成為對手',66,848,1465,46,23,false,C.ink);
text('6 / 44',1450,906,155,28,19,false,C.muted,'right');
s.speakerNotes.textFrame.setText('Opponent Pool 譯為對手池，保存可供評估候選的對手，不是繁殖族群或繁殖父代集合。初始池包含全部十個內建對手；AllInBot、Mayari、COAC、TMA 為固定保護成員，不能被入池賽替換。G0 評估完的初代及之後各代評估完的子代，經 candidate ID、source 與語意 phenotype 去重後才有資格入池；因此策略來源跨越歷代，並非只保留當代十位。池未滿時加入；本次容量 50 含四個保護成員。滿池時，新策略挑戰一個依種子選出的非保護成員，三地圖、三回合、雙邊共十八場；新策略勝場嚴格多於敗場才替換，平手留原成員。G0 對全部十個內建對手；後續 G1、G6、G11…保留四個固定保護成員，再從池內非保護成員抽六名並凍結成十人對戰名單，每名候選進行 180 場評估。名單在刷新前固定；池更新不會立即改變已凍結名單。對手名單刷新後，繁殖前先重評父代。來源：docs/eagle_architecture_spec.md:460-496；eagle/opponent_pool.py:23-211；eagle/evolution/search.py:158-189；configs/experiments/1021_rich_framework_stability_20x10_seed8_13_1run/qwen3_5_9b_rich_framework_stability_20x10_seed8_13_1run.yaml。');
const proto=deck.toProto(),footer=proto.slides[0].elements.at(-1),run=footer.paragraphs[0].runs[0];
footer.name='Slide Number';footer.placeholderType='sldNum';footer.placeholderIndex=90;
footer.paragraphs[0].runs=[{...run,id:`{${randomUUID().toUpperCase()}}`,text:'6',fieldType:'slidenum'},{...run,text:' / 44'}];
deck=Presentation.load(proto);
const candidate=path.join(build,'candidate.pptx');
await(await PresentationFile.exportPptx(deck)).save(candidate);
await finalizePresentation({workspaceDir:work,candidatePath:candidate,finalPath:path.join(build,'output/page.pptx'),pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15925800,8963025','--validate-heading-fit'],explicitTotalSlideCount:1,fontPolicy:{basis:'reference',families:[F],referencePath:source,referenceSha256:sourceHash},verifyArtifactToolImport:true,receiptPath:path.join(build,'validation.json')});
await fs.writeFile(path.join(build,'source.sha256'),sourceHash+'\n');
console.log(JSON.stringify({page:path.join(build,'output/page.pptx'),sourceHash}));
