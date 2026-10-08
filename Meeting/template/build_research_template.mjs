import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
const root='D:/Project/EAGLE/Meeting/template';
const build=path.join(root,'.codex-build');
const skill='C:/Users/cinna/.codex/plugins/cache/openai-primary-runtime/presentations/26.1007.11041/skills/presentations';
const runtime='C:/Users/cinna/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const source='C:/Users/cinna/.codex/skills/artifact-template-eagle-0917/assets/EAGLE-0917.potx';
const fontReference='C:/Users/cinna/.codex/skills/artifact-template-eagle-0917/assets/reference-0917.pptx';
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const {importRuntimeModule}=await import(pathToFileURL(path.join(skill,'container_tools/runtime_helpers.mjs')).href);
const {Presentation,PresentationFile,FileBlob}=await importRuntimeModule('@oai/artifact-tool');
const {finalizePresentation,applyPresentationChartFont}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
await fs.mkdir(build,{recursive:true});
await fs.mkdir(path.join(build,'checked'),{recursive:true});
const imported=await PresentationFile.importPptx(await FileBlob.load(source));
const proto=imported.toProto();proto.slides=[];proto.charts=[];
const deck=Presentation.load(proto);
const palette=JSON.parse(await fs.readFile(path.join(root,'EAGLE.palette.json'),'utf8'));
const F=palette.font,C={ink:palette.heading,body:palette.body,bg:palette.background,rose:palette.rose,header:palette.table.headerFill,border:palette.border};
function text(s,value,x,y,w,h,size=28,color=C.body,bold=false,align='left'){
 const o=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 o.text=value;o.text.style={typeface:F,fontSize:size,color,bold,alignment:align,autoFit:'none'};return o;
}
const layoutNames=['完整演算法流程','迭代細節與失敗分支','實驗結果圖表','耗時與成本','比較分析','區間與逐次變更'];
const layouts=layoutNames.map((name,i)=>{
 const layout=deck.layouts.add(name);layout.setParentLayoutId(deck.masters.items[0].id);
 const title=layout.placeholders.add({type:'title',index:0,geometry:'textbox',position:{left:230,top:46,width:1212,height:108},text:'[研究主題]'});
 title.text.style={typeface:F,fontSize:48,color:C.ink,bold:true,alignment:'center'};
 const subtitle=layout.placeholders.add({type:'subtitle',index:1,geometry:'textbox',position:{left:190,top:166,width:1292,height:72},text:'[必要的實驗口徑或圖例]'});
 subtitle.text.style={typeface:F,fontSize:25,color:C.body,alignment:'center'};
 if(i<2){
  const body=layout.placeholders.add({type:'body',index:2,geometry:'textbox',position:{left:180,top:266,width:1312,height:460},text:'[以可編輯節點、連線與分支放入完整流程]'});
  body.text.style={typeface:F,fontSize:27,color:C.body};
 }else if(i===2||i===3){
  layout.placeholders.add({type:'chart',index:2,geometry:'rect',position:{left:175,top:266,width:795,height:420},text:'[量測資料圖表]'});
  const evidence=layout.placeholders.add({type:'table',index:3,geometry:'rect',position:{left:1020,top:280,width:475,height:370},text:'[數值、單位、樣本與來源]'});
  evidence.text.style={typeface:F,fontSize:27,color:C.body};
 }else{
  layout.placeholders.add({type:'table',index:2,geometry:'rect',position:{left:150,top:270,width:1372,height:330},text:i===5?'[日期／版本、before、after／目的、run、觀察影響]':'[基準、方法、結果差、耗時差與控制條件]'});
  const analysis=layout.placeholders.add({type:'body',index:3,geometry:'textbox',position:{left:190,top:650,width:1292,height:150},text:i===5?'[區間外基準的日期、版本、run ID 與選用原因]':'[一個有證據的解讀與必要限制]'});
  analysis.text.style={typeface:F,fontSize:28,color:C.body};
 }
 return layout;
});
function slide(layout,title,sub){
 const s=deck.slides.add({layoutId:layout.id,width:1672,height:941});
 s.placeholders.getItem('title').text=title;s.placeholders.getItem('subtitle').text=sub;
 s.speakerNotes.textFrame.setText('可重用研究簡報頁型。內容為可替換的結構占位，沒有聲稱任何實驗結果。用當次版本的演算法與量測資料替換全部占位內容。');
 return s;
}
function node(s,label,x,y,w=350,h=86,decision=false){
 const o=s.shapes.add({geometry:decision?'diamond':'rect',position:{left:x,top:y,width:w,height:h},fill:C.bg,line:{fill:C.ink,width:1.5}});
 o.text=label;o.text.style={typeface:F,fontSize:28,color:C.body,alignment:'center',verticalAlignment:'middle',autoFit:'none'};return o;
}
function connect(s,a,b,from='right',to='left'){return s.shapes.connect(a,b,{kind:'elbow',fromSide:from,toSide:to,line:{fill:C.rose,width:2},tail:{type:'arrow',width:'med',length:'med'}});}
function table(s,values,widths,x=1020,y=280,w=475,h=330,size=24){
 const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,columnWidths:widths,values});
 t.borders.assign({fill:C.border,width:0.7});
 t.cells.block({row:0,column:0,rowCount:values.length,columnCount:values[0].length}).assign({margins:{top:7,bottom:7,left:9,right:9}});
 for(let r=0;r<values.length;r++){t.rows[r].height=h/values.length;for(let c=0;c<values[0].length;c++){const cell=t.getCell(r,c);cell.fill=r===0?C.header:C.bg;cell.text.style={typeface:F,fontSize:size,color:C.body,bold:r===0,autoFit:'none'};}}
 return t;
}
function chart(s,title,values,yTitle){
 const ch=s.charts.add('bar',{position:{left:175,top:275,width:795,height:390},title,titleTextStyle:{typeface:F,fontSize:25,color:C.ink},categories:['區間外基準','區間內方法'],series:[{name:'占位數據',values,fill:C.rose}],barOptions:{direction:'column',grouping:'clustered',gapWidth:180},hasLegend:false,chartFill:C.bg,plotAreaFill:C.bg,xAxis:{textStyle:{typeface:F,fontSize:22,color:C.body}},yAxis:{min:0,title:yTitle,textStyle:{typeface:F,fontSize:22,color:C.body}},dataLabels:{showValue:true,position:'outEnd',textStyle:{typeface:F,fontSize:24,color:C.ink}}});
 applyPresentationChartFont(ch,{fontFamily:F});return ch;
}
let s=slide(layouts[5],'區間與逐次變更','[報告起訖日期]。每次變更獨立一列，基準可在區間外');
table(s,[['日期／版本','變更前','變更後／目的','影響實驗','量測影響'],['[日期／rev]','[前一版行為]','[新行為與原因]','[run IDs]','[結果／未驗證]'],['[日期／rev]','[前一版行為]','[新行為與原因]','[run IDs]','[結果／未驗證]']],[235,260,320,250,307],150,278,1372,340,25);
text(s,'區間外基準：[原始日期、版本、實驗 ID 與選用原因]',190,692,1292,105,30,C.ink,true);

s=slide(layouts[0],'完整演算法流程','結構示意。替換為來源中的所有階段、迴圈、分支與輸出');
const a=node(s,'[資料與設定]',180,270),b=node(s,'[初始化狀態]',660,270),c=node(s,'[初始評估]',1140,270);
const d=node(s,'[完整迭代計算]',1140,470),e=node(s,'[評估與狀態更新]',660,470),f=node(s,'停止？',225,451,260,125,true);
const g=node(s,'[最終獨立驗證]',180,680),h=node(s,'[輸出與持久化]',660,680);
connect(s,a,b);connect(s,b,c);connect(s,c,d,'bottom','top');connect(s,d,e,'left','right');connect(s,e,f,'left','right');connect(s,f,g,'bottom','top');connect(s,g,h);
connect(s,f,d,'top','top');text(s,'否：繼續迭代',730,412,400,40,23,C.ink);text(s,'是',305,611,60,40,23,C.ink);
text(s,'按實際方法替換節點，完整分支可延伸至下一張細節頁',1080,716,410,85,24);

s=slide(layouts[1],'迭代細節與失敗分支','結構示意。保留實際資料流、模型角色與有界重試');
const ia=node(s,'[前一輪狀態／證據]',170,285,355),ib=node(s,'[選擇／生成／更新]',655,285,355),ic=node(s,'[新狀態與評估]',1140,285,355);
const good=node(s,'有效？',1185,480,265,130,true),done=node(s,'[保留／提交狀態]',655,695,355),retry=node(s,'[修復／重試判定]',655,500,355),failed=node(s,'[失敗記錄與退出]',170,500,355);
connect(s,ia,ib);connect(s,ib,ic);connect(s,ic,good,'bottom','top');connect(s,good,done,'bottom','right');connect(s,good,retry,'left','right');connect(s,retry,ib,'top','bottom');connect(s,retry,failed,'left','right');
text(s,'否',1032,514,70,35,23,C.ink);text(s,'是',1185,648,70,35,23,C.ink);text(s,'可重試',700,431,180,35,23,C.ink);text(s,'超過上限',393,446,220,35,23,C.ink);
text(s,'[模型角色：輸入、上下文／篩選規則、輸出及用途]',170,732,430,92,25);

s=slide(layouts[2],'實驗結果圖表','示例數值僅展示版面，必須用實際量測資料替換');
chart(s,'結果比較（示例）',[30,50],'[指標與單位]');
table(s,[['證據項目','必填資料'],['日期 / run','[日期 / ID]'],['指標／值','[定義 / 單位]'],['Seeds / n','[seeds / n]'],['狀態／來源','[mode / 檔案]']],[190,285]);
text(s,'[依量測支持的發現。保留會改變結論的限制]',190,740,1292,70,29,C.ink,true);

s=slide(layouts[3],'耗時與成本','示例數值僅展示版面。區分 wall time、加總時間與 partial run');
chart(s,'Run 耗時（示例）',[20,35],'分鐘（示例）');
table(s,[['量測範圍','資料／單位'],['總 wall time','[t_total]'],['初始化','[t_init]'],['完成的世代','[t_gen / 序列]'],['階段／成本','[LLM / eval]']],[220,255]);
text(s,'[比較耗時與結果的取捨。來源：持久化 timing records]',190,740,1292,70,29,C.ink,true);

s=slide(layouts[4],'比較分析','固定比較口徑，分開呈現觀察、因果證據與限制');
table(s,[['比較項目','區間外基準','區間內方法','差異與比較條件'],['日期／版本','[日期／rev]','[日期／rev]','[歷史配置與變更對應]'],['主要結果','[m0 / n0]','[m1 / n1]','[絕對差 / 單位]'],['總耗時','[t0]','[t1]','[差異 / wall time]'],['控制條件','[版本／設定]','[版本／設定]','[共同條件／混雜因素]'],['解讀','[觀察]','[觀察]','[可支持／不能支持的結論]']],[305,325,325,417],150,278,1372,380,25);
text(s,'[一個主要發現，以及能區分可能原因的下一個實驗]',190,692,1292,105,30,C.ink,true);

const output=process.env.TEMPLATE_OUTPUT ?? path.join(build,'checked',"research-template-"+Date.now()+'.pptx');
const candidate=path.join(build,'research-template-candidate.pptx');
await (await PresentationFile.exportPptx(deck)).save(candidate);
execFileSync(path.join(runtime,'python/python.exe'),[path.join(root,'prepare_template.py'),'fix',candidate],{stdio:'inherit'});
await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:output,pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15925800,8963025','--validate-heading-fit',...[1,4,5,6].flatMap(n=>['--require-native-table-slide',String(n)])],explicitTotalSlideCount:6,requiredNativeTableOwnerSlides:[1,4,5,6],requiredNativeChartOwnerSlides:[4,5],materializeLiteralChartWorkbooks:true,fontPolicy:{basis:'reference',families:[F],referencePath:fontReference,referenceSha256:createHash('sha256').update(await fs.readFile(fontReference)).digest('hex')},verifyArtifactToolImport:true,receiptPath:path.join(build,path.basename(output)+'.validation.json')});
const final=await PresentationFile.importPptx(await FileBlob.load(output));
await fs.mkdir(path.join(build,'render'),{recursive:true});
for(let i=0;i<final.slides.items.length;i++){const img=await final.slides.items[i].export({format:'png',scale:1});await fs.writeFile(path.join(build,'render',`slide-${i+1}.png`),new Uint8Array(await img.arrayBuffer()));}
execFileSync(path.join(runtime,'python/python.exe'),[path.join(root,'prepare_template.py'),'potx',output,path.join(build,'EAGLE.potx')],{stdio:'inherit'});
console.log(JSON.stringify({output,slides:final.slides.items.length,layouts:final.layouts.items.length}));
