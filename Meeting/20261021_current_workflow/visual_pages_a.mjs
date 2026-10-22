export function renderPrimary(s,p,H){
  const {T,R,B,Cn,L,tag,dot,tiles,C,sub,foot}=H;
  if(p.page>20)return false;
  const section=(v,x,y,w=400)=>T(s,v,x,y,w,50,{size:32,color:C.ink,bold:true});
  const small=(v,x,y,w,h=52)=>T(s,v,x,y,w,h,{size:25,color:C.muted});
  switch(p.page){
    case 1:{
      sub(s,'以歷代策略維護對手池，再用凍結的 4＋6 名單評估候選');
      T(s,'離線演化',72,225,520,110,{size:86,color:C.ink,bold:true});
      T(s,'MicroRTS Java agent',76,346,590,66,{size:42,color:C.text});
      const a=B(s,'策略／控制基因',805,232,330,104,{fill:C.gold,bold:true,size:34});
      const b=B(s,'完整 Java',1205,410,330,104,{fill:C.blush,bold:true,size:35});
      const c=B(s,'對戰證據',805,588,330,104,{fill:C.pale,bold:true,size:35});
      Cn(s,a,b);Cn(s,b,c,'bottom','right');Cn(s,c,a,'left','left');
      T(s,'生成',1205,268,330,56,{size:26,align:'center',color:C.muted});
      T(s,'評估',1235,574,300,54,{size:26,align:'center',color:C.muted});
      // Preserve the label position edited in PowerPoint.
      T(s,'反思與選擇',5869811/9525,422,270,56,{size:26,color:C.ink,bold:true});
      tag(s,'對戰時直接執行 Java',76,515,420,{fill:C.gold,size:28});
      small('演化與 LLM 工作在對戰之前完成',76,580,570);
      T(s,'2026-10-21',76,734,500,56,{size:30,color:C.muted});
      foot(s,'搜尋採 opponent pool；正式 Final Test 使用獨立的固定基準');
      return true;
    }
    case 2:{
      sub(s,'目前搜尋協定：self_play ＋ tournament-v1 opponent pool');
      R(s,65,205,1540,145,{fill:C.gold,radius:true});
      const a=B(s,'GPT 產生 Java framework',90,225,540,100,{fill:C.gold,size:35,bold:true});
      small('暫時人工由 ChatGPT\n生成固定 framework',680,236,780,78);
      const init=B(s,'初始化 G0\n十個內建對手',100,440,325,100,{fill:C.pale,size:29,bold:true});
      const e0=B(s,'候選初評\n策略開始累積入池',525,440,400,100,{fill:C.blush,size:29,bold:true});
      const cycle=B(s,'到期刷新 4＋6\n父代重評、選擇與變異',1050,420,420,140,{fill:C.rose,size:28,bold:true});
      const evals=B(s,'子代評估與倖存選擇\n更新 opponent pool',1040,680,440,125,{fill:C.blush,size:28,bold:true});
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
      sub(s,'slot 是固定 Java 裡的可替換位置；演化只改選值，Java 骨架保持固定');
      section('槽位的意義',75,195,330);section('bundle 定義的合法選項',435,195,650);section('候選保存的值',1120,195,470);
      T(s,'integer｜工人數',75,285,330,48,{size:29,color:C.ink,bold:true});small('worker_target',75,334,330,42);
      [2,3,4,5,6,7,8].forEach((v,i)=>B(s,String(v),435+i*83,290,68,66,{fill:v===6?C.rose:C.pale,size:31,bold:v===6}));
      small('min = 2，max = 8，step = 1',435,366,650,38);
      L(s,1045,333,1100,333,{arrow:true});B(s,'worker_target: 6',1120,290,470,86,{fill:C.gold,size:30,bold:true});
      T(s,'number｜數值權重',75,455,340,48,{size:28,color:C.ink,bold:true});small('attack_weight',75,504,330,42);
      ['0','0.25','0.5','0.75','1'].forEach((v,i)=>B(s,v,435+i*115,460,100,66,{fill:v==='0.75'?C.rose:C.pale,size:29,bold:v==='0.75'}));
      small('min = 0，max = 1，step = 0.25',435,536,670,38);
      L(s,1045,503,1100,503,{arrow:true});B(s,'attack_weight: 0.75',1120,460,470,86,{fill:C.gold,size:28,bold:true});
      T(s,'expression_choice',75,625,340,48,{size:27,color:C.ink,bold:true});small('攻擊目標 target_policy',75,674,350,42);
      ['最近敵人','最低血量','敵方基地'].forEach((v,i)=>B(s,v,435+i*195,630,180,70,{fill:i===1?C.rose:C.pale,size:28,bold:i===1}));
      small('每個 choice_id 已對應一段固定 Java 表達式',435,710,690,38);
      L(s,1045,673,1100,673,{arrow:true});B(s,'target_policy: "lowest_hp"',1120,630,470,86,{fill:C.gold,size:25,bold:true});
      const genome=B(s,'填滿全部 slot，組成完整 genome',75,779,600,62,{fill:C.blush,size:29,bold:true});
      const java=B(s,'驗證選值，再填入固定模板產生 Java',825,779,765,62,{fill:C.ink,color:'#FFFFFF',size:29,bold:true});Cn(s,genome,java);
      foot(s,'簡化示例，實際選單由 bundle 決定。number 也只能選離散格點，不能任意填小數');
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
      sub(s,'同一凍結快照內，10 位父代與 10 位子代選出 10 位下一代');
      T(s,'父代',76,230,260,60,{size:37,color:C.ink,bold:true});tiles(s,10,82,320,{cols:5,cell:56,gap:14,fill:C.gold});
      const select=B(s,'選父代',535,265,300,94,{fill:C.pale,size:34,bold:true});
      const vary=B(s,'交配與突變',1065,265,410,94,{fill:C.blush,size:34,bold:true});Cn(s,select,vary);
      const evals=B(s,'Java、驗證與子代評估',1065,485,410,110,{fill:C.pale,size:30,bold:true});Cn(s,vary,evals,'bottom','top');
      const surv=B(s,'父代＋子代\n選下一代',535,655,300,120,{fill:C.rose,size:31,bold:true});Cn(s,evals,surv,'bottom','right');
      const saved=B(s,'更新 pool\n保存 checkpoint',85,655,330,120,{fill:C.gold,size:31,bold:true});Cn(s,surv,saved,'left','right');Cn(s,saved,select,'top','left');
      tag(s,'對手快照到期刷新時，繁殖前先重評父代',535,423,940,{fill:C.gold,size:28});
      foot(s,'世代提交後才前進；新入池成員等下一次快照刷新才可能成為對手');
      return true;
    }
    case 8:{
      sub(s,'先用 Game Performance 決定頂層，再在這一層中選繁殖父代');
      const pop=B(s,'當代候選族群\n同一對手快照，已有 fitness',80,280,415,135,{fill:C.pale,size:29,bold:true});
      const tier=B(s,'只留分數頂層\nfitness ≥ 最高分 − 1.0',625,280,460,135,{fill:C.gold,size:31,bold:true});Cn(s,pop,tier);
      const pa=B(s,'父代 A\nseeded 抽樣',1230,250,345,110,{fill:C.blush,size:31,bold:true});Cn(s,tier,pa);
      const pb=B(s,'父代 B\n優先挑離 A 較遠者',1230,590,345,125,{fill:C.rose,size:29,bold:true});L(s,1085,390,1150,390);L(s,1150,390,1150,652);L(s,1150,652,1230,652,{arrow:true});
      T(s,'在同一頂層再選',1210,440,380,52,{size:28,color:C.ink,bold:true,align:'center'});
      tag(s,'語意距離來自固定狀態中的 Java 動作',80,580,950,{fill:C.pale,size:28});
      small('低分者不能只靠行為新穎跨越分數頂層',80,660,950);
      foot(s,'繁殖父代提供基因；opponent pool 提供評估對手。沒有相容簽章時採 seeded fallback');
      return true;
    }
    case 9:{
      sub(s,'教學示例：最高分 100，頂層門檻為 99.0；只在這層中比較行為');
      const rows=[['候選','fitness','距候選 B'],['A','100','8／9'],['B','99.4','0'],['C','99.0','2／9'],['D','98.8','不比較']];
      rows.forEach((row,r)=>row.forEach((v,c)=>B(s,v,80+c*195,245+r*104,183,86,{fill:r===0?C.blush:r===4?C.light:r===1?C.rose:r===2?C.gold:C.pale,size:r?31:27,bold:r<3})));
      const first=B(s,'第一父代：seeded 抽中候選 B',875,260,660,96,{fill:C.gold,size:31,bold:true});
      const distance=B(s,'在 A、B、C 中\n比較與 B 的語意距離',960,470,490,125,{fill:C.pale,size:31,bold:true});Cn(s,first,distance,'bottom','top');
      const second=B(s,'第二父代選候選 A\n8／9 是最大距離',960,700,490,110,{fill:C.rose,size:32,bold:true});Cn(s,distance,second,'bottom','top');
      small('D 低於 99.0，不能靠新穎性入選',80,776,750);
      foot(s,'本頁為示例，非實驗結果。分數差 1.0 包含邊界；距離來自相容的九個動作探針');
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
      foot(s,'Code gate 只診斷策略忠實度與程式正確性，不使用勝率作修正依據');
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
      foot(s,'Opponent pool 必須啟用語意 probe，用於行為去重與分數層內的選擇');
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
      foot(s,'對手快照固定為 4 個保護成員＋6 個抽樣成員；同一快照內的候選共用名單');
      return true;
    }
    case 19:{
      sub(s,'單場結果分數，加上最多 ±10 的物資、資源與存活 shaping');
      const vals=[['敗','−100',C.blush],['和','0',C.pale],['勝','＋100',C.gold]];
      vals.forEach((v,i)=>{const x=90+i*540;T(s,v[0],x,225,450,65,{size:40,bold:true,color:C.ink,align:'center'});T(s,v[1],x,310,450,130,{size:90,bold:true,color:C.ink,align:'center'});B(s,'−10 ≤ shaping ≤ ＋10',x,490,450,64,{fill:v[2],size:28,bold:true});});
      const per=B(s,'每個對手\n18 場分數取平均',90,655,550,130,{fill:C.pale,size:31,bold:true});
      const fit=B(s,'10 個對手等權平均\n＝候選的唯一 fitness',850,655,730,130,{fill:C.gold,size:33,bold:true});Cn(s,per,fit);
      foot(s,'完整 180 場才有有效 fitness；語意差異只在分數同層內輔助選擇，不另加分');
      return true;
    }
    case 20:{
      sub(s,'G0 使用全部十個內建對手；之後從持續累積的池中抽取 4＋6 名單');
      const rows=[['可替換｜基礎',['PassiveAI','RandomAI','RandomBiasedAI'],C.pale],['可替換｜Rush',['LightRush','HeavyRush','WorkerRush'],C.blush],['永久保護',['AllInBot','Mayari','COAC','TMA'],C.gold]];
      rows.forEach((r,i)=>{const y=245+i*180;T(s,r[0],80,y+5,350,60,{size:30,color:C.ink,bold:true});r[1].forEach((v,j)=>B(s,v,455+j*286,y,264,80,{fill:r[2],size:v==='RandomBiasedAI'?24:28,bold:true}));});
      B(s,'前 6 個可被歷代候選替換；後 4 個永久保留。評分時十欄等權',165,785,1340,62,{fill:C.pale,size:29,bold:true});
      return true;
    }
  }
  return false;
}
