export function renderPrimary(s,p,H){
  const {T,R,B,Cn,L,tag,dot,tiles,C,sub,foot}=H;
  if(p.page>20)return false;
  const section=(v,x,y,w=400)=>T(s,v,x,y,w,50,{size:32,color:C.ink,bold:true});
  const small=(v,x,y,w,h=52)=>T(s,v,x,y,w,h,{size:25,color:C.muted});
  switch(p.page){
    case 1:{
      sub(s,'策略、Java 與對戰證據的演化迴圈');
      T(s,'離線演化',72,225,520,110,{size:86,color:C.ink,bold:true});
      T(s,'MicroRTS Java agent',76,346,590,66,{size:42,color:C.text});
      const a=B(s,'策略／控制基因',805,232,330,104,{fill:C.gold,bold:true,size:34});
      const b=B(s,'完整 Java',1205,410,330,104,{fill:C.blush,bold:true,size:35});
      const c=B(s,'對戰證據',805,588,330,104,{fill:C.pale,bold:true,size:35});
      Cn(s,a,b);Cn(s,b,c,'bottom','right');Cn(s,c,a,'left','left');
      T(s,'生成',1205,268,330,56,{size:26,align:'center',color:C.muted});
      T(s,'評估',1235,574,300,54,{size:26,align:'center',color:C.muted});
      T(s,'反思與選擇',660,422,270,56,{size:26,color:C.ink,bold:true});
      tag(s,'對戰時直接執行 Java',76,515,420,{fill:C.gold,size:28});
      small('演化與 LLM 工作在對戰之前完成',76,580,570);
      T(s,'2026-10-21',76,734,500,56,{size:30,color:C.muted});
      foot(s,'以對戰證據反思策略，再由演化選擇保留候選');
      return true;
    }
    case 2:{
      sub(s,'先固定 framework，再進入第 0 代與演化迴圈');
      R(s,65,205,1540,145,{fill:C.gold,radius:true});
      const a=B(s,'GPT 產生 Java framework',90,225,540,100,{fill:C.gold,size:35,bold:true});
      small('暫時人工由 ChatGPT\n生成固定 framework',680,236,780,78);
      const init=B(s,'初始化 G0',100,440,325,100,{fill:C.pale,size:33,bold:true});
      const e0=B(s,'Java 與初始評估',525,440,400,100,{fill:C.blush,size:31,bold:true});
      const cycle=B(s,'刷新情境\n選父代與變異',1050,420,420,140,{fill:C.rose,size:32,bold:true});
      const evals=B(s,'子代評估\n父代＋子代選倖存者',1040,680,440,125,{fill:C.blush,size:30,bold:true});
      const stop=B(s,'停止條件？',525,690,360,105,{fill:C.gold,size:32,bold:true});
      const ft=B(s,'Final Test',100,690,325,105,{fill:C.ink,color:'#FFFFFF',size:34,bold:true});
      Cn(s,a,init,'bottom','top');Cn(s,init,e0);Cn(s,e0,cycle);Cn(s,cycle,evals,'bottom','top');Cn(s,evals,stop,'left','right');Cn(s,stop,ft,'left','right');
      L(s,705,690,705,600);L(s,705,600,1515,600);L(s,1515,600,1515,490);L(s,1515,490,1470,490,{arrow:true});
      tag(s,'否：下一代',730,565,240,{fill:C.bg,size:24});small('是',450,671,70);
      return true;
    }
    case 3:{
      sub(s,'一條規則決定：誰，在什麼條件下，嘗試什麼動作');
      const a=B(s,'actor\n執行對象',94,265,380,175,{fill:C.gold,size:42,bold:true});
      const w=B(s,'when\n可觀察條件',644,265,380,175,{fill:C.pale,size:42,bold:true});
      const ac=B(s,'action\n候選動作',1194,265,380,175,{fill:C.blush,size:42,bold:true});
      Cn(s,a,w);Cn(s,w,ac);
      const rules=B(s,'規則 1   →   規則 2   →   規則 3   →   …',94,550,1480,100,{fill:C.bg,line:C.blush,size:37});
      const valid=B(s,'可合法發出動作',950,706,360,85,{fill:C.gold,size:30,bold:true});
      const next=B(s,'無法發出：繼續下一條',285,706,470,85,{fill:C.pale,size:30,bold:true});
      L(s,520,650,520,706,{arrow:true});L(s,1130,650,1130,706,{arrow:true});
      foot(s,'DSL 離線轉為 Java；對戰不執行文字指令。空 rules 代表 idle');
      return true;
    }
    case 4:{
      sub(s,'架構建立一次；模板、槽位與表達式在搜尋期間保持固定');
      const made=B(s,'新建立 framework',84,250,430,90,{fill:C.blush,size:34,bold:true});
      const existing=B(s,'已有外部 bundle',84,520,430,90,{fill:C.gold,size:34,bold:true});
      small('design_brief\nGroq／Mistral／local bootstrap',95,359,450,100);
      small('人工準備或共用架構\n指定 bundle_path',95,630,450,100);
      const check=B(s,'Schema\n與 Java 契約驗證',645,405,390,160,{fill:C.pale,size:35,bold:true});
      Cn(s,made,check);Cn(s,existing,check);
      const frozen=B(s,'凍結 bundle',1170,390,410,190,{fill:C.gold,size:42,bold:true});Cn(s,check,frozen);
      tag(s,'exact bytes',1182,620,190,{fill:C.pale,size:25});tag(s,'SHA-256',1390,620,180,{fill:C.blush,size:25});
      foot(s,'之後只演化 control_genome；resume 讀凍結版本，不重新 bootstrap');
      return true;
    }
    case 5:{
      sub(s,'候選只選值；Java 結構與每個選項的意義由 bundle 決定');
      section('integer',85,240,300);small('離散整數格點',85,300,300);
      L(s,420,326,1530,326,{color:C.blush,width:4});
      ['min','min＋step','…','max'].forEach((v,i)=>{dot(s,'',420+i*350,306,{fill:i===1?C.rose:C.gold,r:20});T(s,v,370+i*350,350,180,48,{size:26,align:'center'});});
      section('number',85,450,300);small('宣告的有限數值格點',85,510,330);
      L(s,420,526,1530,526,{color:C.blush,width:4});for(let i=0;i<9;i++)dot(s,'',420+i*135,510,{fill:i===5?C.rose:C.pale,r:16});
      section('expression_choice',85,650,430);small('只保存 choice_id',85,711,350);
      ['選項 A','選項 B','選項 C','…'].forEach((v,i)=>B(s,v,570+i*245,665,220,86,{fill:i===1?C.blush:C.gold,size:30,bold:i===1}));
      foot(s,'完整 genome 必須包含每個 slot_id，拒絕缺項、未知 key 與越界值');
      return true;
    }
    case 6:{
      sub(s,'兩種演化政策，共用相同的凍結 framework 與下游評估');
      R(s,70,220,720,480,{fill:C.pale,radius:true});R(s,880,220,720,480,{fill:C.gold,radius:true});
      T(s,'local',100,243,640,80,{size:52,bold:true,color:C.ink,align:'center'});
      T(s,'llm_coach',915,243,640,80,{size:52,bold:true,color:C.ink,align:'center'});
      const l1=B(s,'初始：有限域採樣',120,365,620,84,{fill:C.bg,size:31});
      const l2=B(s,'逐槽交配，至多一槽突變',120,535,620,84,{fill:C.blush,size:31,bold:true});Cn(s,l1,l2,'bottom','top');
      const c1=B(s,'初始：LLM 選完整 genome',930,365,620,84,{fill:C.bg,size:30});
      const c2=B(s,'最差單場賽評＋Coach\n回傳完整 genome',930,520,620,112,{fill:C.blush,size:30,bold:true});Cn(s,c1,c2,'bottom','top');
      const out=B(s,'本地渲染 Java，再驗證與對戰',445,750,790,70,{fill:C.ink,color:'#FFFFFF',size:32,bold:true});Cn(s,l2,out,'bottom','top');Cn(s,c2,out,'bottom','top');
      foot(s,'Coach 回應不合法：保留突變前的完整 genome，標記失敗，不隨機補值');
      return true;
    }
    case 7:{
      sub(s,'例：10 位父代與 10 位子代，選出固定 10 位下一代');
      T(s,'父代',76,230,260,60,{size:37,color:C.ink,bold:true});tiles(s,10,82,320,{cols:5,cell:56,gap:14,fill:C.gold});
      const select=B(s,'選父代',535,265,300,94,{fill:C.pale,size:34,bold:true});
      const vary=B(s,'交配與突變',1065,265,410,94,{fill:C.blush,size:34,bold:true});Cn(s,select,vary);
      const evals=B(s,'Java、驗證與子代評估',1065,485,410,110,{fill:C.pale,size:30,bold:true});Cn(s,vary,evals,'bottom','top');
      const surv=B(s,'父代＋子代\n選下一代',535,655,300,120,{fill:C.rose,size:31,bold:true});Cn(s,evals,surv,'bottom','right');
      const saved=B(s,'更新 pool\n保存 checkpoint',85,655,330,120,{fill:C.gold,size:31,bold:true});Cn(s,surv,saved,'left','right');Cn(s,saved,select,'top','left');
      tag(s,'self-play 刷新時，繁殖前先重評父代',535,423,940,{fill:C.gold,size:29});
      foot(s,'世代提交後才前進；新入池成員等下一次快照刷新才可能成為對手');
      return true;
    }
    case 8:{
      sub(s,'繁殖父代提供基因；評估對手與倖存者選擇是另外兩個環節');
      section('Fixed roster',90,220,600);section('Self-play',920,220,600);
      tag(s,'十案例 lexicase',90,290,620,{fill:C.pale,size:31});tag(s,'Game Performance 頂層',920,290,620,{fill:C.gold,size:31});
      const f1=B(s,'打亂案例順序',130,405,540,86,{fill:C.blush,size:31});
      const f2=B(s,'依案例留下最高分者',130,585,540,86,{fill:C.pale,size:31,bold:true});Cn(s,f1,f2,'bottom','top');
      const g1=B(s,'距最高分 ≤ 1.0',960,405,540,86,{fill:C.blush,size:33,bold:true});
      const g2=B(s,'第二父代可優先選\n行為差異較遠者',960,575,540,112,{fill:C.gold,size:31});Cn(s,g1,g2,'bottom','top');
      L(s,830,235,830,765,{color:C.blush,width:1});
      small('兩次獨立抽樣，可選中同一父代',120,734,610);small('語意距離只在同分範圍內作用',960,734,610);
      return true;
    }
    case 9:{
      sub(s,'教學示例：改變案例檢查順序，專長不同的策略都有機會');
      const rows=[['候選','X','Y'],['A','90','20'],['B','90','70'],['C','80','95']];
      rows.forEach((row,r)=>row.forEach((v,c)=>B(s,v,85+c*160,260+r*115,150,95,{fill:r===0?C.blush:(r===2&&c===1)||(r===3&&c===2)?C.gold:C.pale,size:r?36:30,bold:!r||r===2})));
      section('順序 X、Y',730,250,800);
      const a=B(s,'A、B、C',730,340,240,82,{fill:C.pale,size:31});const ab=B(s,'A、B',1080,340,190,82,{fill:C.gold,size:32});const b=B(s,'B',1380,340,160,82,{fill:C.rose,size:40,bold:true});Cn(s,a,ab);Cn(s,ab,b);small('X 最高分',955,295,170);small('Y 最高分',1275,295,170);
      section('順序 Y、X',730,550,800);
      const all=B(s,'A、B、C',730,640,240,82,{fill:C.pale,size:31});const c=B(s,'C',1130,640,240,82,{fill:C.rose,size:40,bold:true});Cn(s,all,c);small('Y 已剩一位',970,596,210);
      foot(s,'正式流程使用十個對手案例；本頁數值只說明篩選機制');
      return true;
    }
    case 10:{
      sub(s,'直接父代與各成分的真正來源，分開保存');
      section('父代 A',84,225,300);section('父代 B',1180,225,300);
      const labs=['策略 DSL','generation prompt','inherited Java'];
      const aa=labs.map((v,i)=>B(s,v,84,320+i*135,400,86,{fill:C.gold,size:28,bold:true}));
      const bb=labs.map((v,i)=>B(s,v,1180,320+i*135,400,86,{fill:C.blush,size:28,bold:true}));
      const child=labs.map((v,i)=>B(s,v,638,320+i*135,390,86,{fill:i===1?C.blush:C.gold,size:28,bold:true}));
      [aa[0],bb[1],aa[2]].forEach((a,i)=>Cn(s,a,child[i],i===1?'left':'right',i===1?'right':'left'));
      tag(s,'子代：成分獨立選來源',606,225,450,{fill:C.pale,size:29});
      small('Java 這一列只在 inherited 模式啟用',515,732,710);
      foot(s,'DSL 模式複製完整 policy；framework 模式改為每個 slot 獨立交配並保存 donor');
      return true;
    }
    case 11:{
      sub(s,'僅 LLM 模式執行；每位實際來源先對照自己的策略與 Java');
      const source=B(s,'來源 policy\n＋原始 Java',80,345,330,140,{fill:C.pale,size:33,bold:true});
      const gate=B(s,'Code 診斷',570,345,360,140,{fill:C.ink,color:'#FFFFFF',size:40,bold:true});Cn(s,source,gate);
      const good=B(s,'健康',1110,220,180,70,{fill:C.gold,size:32,bold:true});const variation=B(s,'正常交配與突變',1110,310,445,86,{fill:C.pale,size:31});Cn(s,gate,good);Cn(s,good,variation,'bottom','top');
      const bad=B(s,'有缺陷',1110,470,180,70,{fill:C.blush,size:32,bold:true});const correction=B(s,'單一父代修正 Java\n保留原 prompt 基因',1110,560,445,110,{fill:C.pale,size:29});Cn(s,gate,bad);Cn(s,bad,correction,'bottom','top');
      const fail=B(s,'診斷失敗：保留證據，標記失敗子代',400,741,800,64,{fill:C.light,size:28});Cn(s,gate,fail,'bottom','top');
      foot(s,'只修策略忠實度與程式正確性；Code gate 不靠勝率評分，也不計 AOS credit');
      return true;
    }
    case 12:{
      sub(s,'Coach 同時看全局摘要，但詳細賽評只取策略來源父代的一場最差對戰');
      section('父代已完成對戰',75,215,480);tiles(s,18,85,300,{cols:6,cell:51,gap:11,fill:C.pale});
      B(s,'差',85+2*62,300+62,51,51,{fill:C.rose,size:21,bold:true});
      const worst=B(s,'1 場詳細 trace',90,575,350,82,{fill:C.blush,size:30,bold:true});
      const comment=B(s,'Match Commentator\n診斷轉折與失誤',580,570,410,110,{fill:C.pale,size:28,bold:true});Cn(s,worst,comment);
      const summary=B(s,'全場 global summary',580,287,410,96,{fill:C.gold,size:29,bold:true});
      const coach=B(s,'Coach',1140,423,405,120,{fill:C.ink,color:'#FFFFFF',size:49,bold:true});Cn(s,comment,coach);Cn(s,summary,coach);
      const out=B(s,'新 DSL 或完整 genome',1115,704,455,86,{fill:C.blush,size:31,bold:true});Cn(s,coach,out,'bottom','top');
      small('圖中場次方塊為示意',83,490,420);
      foot(s,'找不到該場 trace 或賽評失敗，不另挑替代賽事；原基因與證據保留');
      return true;
    }
    case 13:{
      sub(s,'先選對證據，再驗證 Coach 提出的完整規則');
      section('最差已完成場次',82,230,650);section('JSONL 逐行規則',915,230,650);
      const m1=B(s,'performance 為有限值\n選最低值',90,330,610,100,{fill:C.gold,size:30,bold:true});
      const m2=B(s,'缺值時：敗 −100、和 0、勝 100',90,495,610,90,{fill:C.pale,size:29});Cn(s,m1,m2,'bottom','top');
      small('同分按 match_id；失敗比賽排除',100,644,630);
      ['合法規則 1　保留','非法整行規則　捨棄','合法規則 3　保留'].forEach((v,i)=>B(s,v,925,330+i*140,620,100,{fill:i===1?C.light:C.blush,size:31,bold:i!==1}));
      L(s,830,250,830,760,{color:C.blush,width:1});
      foot(s,'合法規則保留原順序；至少一條才成功。Framework 回應仍要求完整 genome');
      return true;
    }
    case 14:{
      sub(s,'改進「如何把策略翻成 Java」的可重用規則');
      const inputs=B(s,'Policy\n可編輯 Java 區域\n相符的 validation／compiler 診斷',80,275,460,210,{fill:C.pale,size:28});
      const reviewer=B(s,'Reviewer',665,330,340,100,{fill:C.gold,size:39,bold:true});Cn(s,inputs,reviewer);
      const rewriter=B(s,'Rewriter',1165,330,390,100,{fill:C.blush,size:39,bold:true});Cn(s,reviewer,rewriter);
      const delta=B(s,'Reusable-rule delta',1095,590,460,90,{fill:C.pale,size:29,bold:true});Cn(s,rewriter,delta,'bottom','top');
      const gp=B(s,'generation_prompt',550,590,430,90,{fill:C.rose,size:34,bold:true});Cn(s,delta,gp,'left','right');
      const generator=B(s,'Java Generator',80,590,350,90,{fill:C.gold,size:32,bold:true});Cn(s,gp,generator,'left','right');
      tag(s,'策略基因保留',550,746,430,{fill:C.gold,size:27});
      foot(s,'Reviewer 不接收勝敗、fitness、對手分數或比賽 trace');
      return true;
    }
    case 15:{
      sub(s,'不同基因表示，匯入同一條 Java 驗證與對戰路徑');
      const modes=[['LLM','策略＋generation prompt\n選配 inherited Java','有界生成／編譯修復',C.blush],['Deterministic DSL','Canonical policy\n本地 typed IR 編譯','失敗不呼叫 LLM 修復',C.pale],['Framework slots','凍結 template\n＋完整 control_genome','失敗不呼叫 LLM 修復',C.gold]];
      const outs=[];
      modes.forEach((m,i)=>{const x=72+i*523;T(s,m[0],x,225,482,65,{size:35,color:C.ink,bold:true,align:'center'});const inp=B(s,m[1],x,340,482,135,{fill:m[3],size:30});outs.push(B(s,'完整 Java',x+58,550,365,85,{fill:m[3],size:34,bold:true}));Cn(s,inp,outs[i],'bottom','top');small(m[2],x,672,482);});
      const v=B(s,'Validation → javac → Integration → MicroRTS',370,765,955,64,{fill:C.ink,color:'#FFFFFF',size:31,bold:true});outs.forEach(o=>Cn(s,o,v,'bottom','top'));
      foot(s,'語意 probe 為選配診斷，self-play 必須啟用');
      return true;
    }
    case 16:{
      sub(s,'第一份驗證與編譯成功的 source／classes，成為唯一 canonical 表型');
      const inputs=B(s,'權威基因\n＋固定 scaffold',80,285,345,135,{fill:C.gold,size:34,bold:true});
      const gen=B(s,'完整 Java 回應',610,285,410,135,{fill:C.blush,size:35,bold:true});Cn(s,inputs,gen);
      const check=B(s,'外框／normalize\nValidation＋javac',1175,285,420,135,{fill:C.pale,size:31,bold:true});Cn(s,gen,check);
      const good=B(s,'成功 → 提升表型',1190,620,395,105,{fill:C.gold,size:32,bold:true});Cn(s,check,good,'bottom','top');
      const repair=B(s,'前次完整 source\n＋當次結構化診斷',610,620,410,105,{fill:C.pale,size:29});
      L(s,1175,386,1100,386);L(s,1100,386,1100,675);L(s,1100,675,1020,675,{arrow:true});Cn(s,repair,gen,'top','bottom');
      tag(s,'失敗，尚有 attempt',700,505,330,{fill:C.bg,size:25});
      const failed=B(s,'耗盡上限\n保留失敗證據',80,620,345,105,{fill:C.light,size:30});Cn(s,repair,failed,'left','right');
      foot(s,'Integration／runtime 失敗不回到 decoder；確定性兩種模式沒有此修復迴圈');
      return true;
    }
    case 17:{
      sub(s,'先檢查 source，再編譯；可載入不代表能合法執行對戰');
      const src=B(s,'Validation',80,245,450,84,{fill:C.gold,size:37,bold:true});
      small('package／class／固定 scaffold\n單一策略 marker／合法 API',90,365,430,100);
      const comp=B(s,'javac',640,245,390,84,{fill:C.blush,size:42,bold:true});Cn(s,src,comp);
      small('每個 attempt 最多一次\n提升成功 class tree，不重編',650,365,410,100);
      const integ=B(s,'Integration',1140,245,450,84,{fill:C.pale,size:38,bold:true});Cn(s,comp,integ);
      const checks=['載入','AI 繼承','建構子','reset','clone','getAction','PlayerAction'];
      checks.forEach((v,i)=>{const x=88+i*218;dot(s,String(i+1),x,595,{fill:i<5?C.pale:C.gold,r:28,size:25});T(s,v,x-38,676,156,60,{size:24,align:'center',bold:true,color:C.ink});if(i<6)L(s,x+65,623,x+195,623,{arrow:true});});
      foot(s,'真實 8×8 地圖、雙方位置與獨立狀態檢查動作和一個 cycle；前置失敗阻擋後續');
      return true;
    }
    case 18:{
      sub(s,'同一份 Java 與 classes，覆蓋所有對手、地圖、回合與位置');
      const terms=[['10','對手欄位'],['3','地圖'],['3','回合'],['2','雙方位置']];
      terms.forEach((v,i)=>{const x=80+i*405;T(s,v[0],x,230,310,150,{size:120,color:i===0?C.ink:C.rose,bold:true,align:'center'});tag(s,v[1],x,430,310,{fill:i%2?C.pale:C.gold,size:30});if(i<3)T(s,'×',x+330,270,70,80,{size:53,color:C.muted});});
      const total=B(s,'180 場／候選',450,590,780,140,{fill:C.ink,color:'#FFFFFF',size:68,bold:true});
      tag(s,'每個對手 18 場',85,630,305,{fill:C.pale,size:28});B(s,'每張地圖可設\ntick_limit',1280,614,305,86,{fill:C.gold,size:25,bold:true});
      foot(s,'固定十對手或凍結的 self-play 4＋6 名單，都維持相同矩陣規模');
      return true;
    }
    case 19:{
      sub(s,'單場結果分數，加上最多 ±10 的物資、資源與存活 shaping');
      const vals=[['敗','−100',C.blush],['和','0',C.pale],['勝','＋100',C.gold]];
      vals.forEach((v,i)=>{const x=90+i*540;T(s,v[0],x,225,450,65,{size:40,bold:true,color:C.ink,align:'center'});T(s,v[1],x,310,450,130,{size:90,bold:true,color:C.ink,align:'center'});B(s,'−10 ≤ shaping ≤ ＋10',x,490,450,64,{fill:v[2],size:28,bold:true});});
      const f=B(s,'Fixed roster\n十個對手分數各自成一個案例',90,655,710,130,{fill:C.pale,size:30,bold:true});
      const sp=B(s,'Self-play\n十欄等權平均＝唯一 fitness',890,655,690,130,{fill:C.gold,size:30,bold:true});
      foot(s,'固定名單的 0.5／1／2 加權均分只用於報表與代表選擇');
      return true;
    }
    case 20:{
      sub(s,'每個對手 18 場；演化選擇保留十個獨立案例');
      const rows=[['基礎基準','0.5',['PassiveAI','RandomAI','RandomBiasedAI'],C.pale],['Rush 基準','1',['LightRush','HeavyRush','WorkerRush'],C.blush],['進階基準','2',['AllInBot','Mayari','COAC','TMA'],C.gold]];
      rows.forEach((r,i)=>{const y=245+i*180;T(s,r[0],80,y+5,250,60,{size:33,color:C.ink,bold:true});dot(s,r[1],326,y,{fill:r[3],r:39,size:29});r[2].forEach((v,j)=>B(s,v,455+j*286,y,264,80,{fill:r[3],size:v==='RandomBiasedAI'?24:28,bold:true}));});
      tag(s,'報表權重總和 12.5',80,795,440,{fill:C.pale,size:27});
      T(s,'Lexicase 使用案例，不以加權總分過濾',620,788,935,55,{size:29,color:C.ink,bold:true});
      return true;
    }
  }
  return false;
}
