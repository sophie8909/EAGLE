const C={bg:'#FCF8F5',ink:'#47171C',text:'#423C3B',rose:'#CF8792',blush:'#DEB4BA',gold:'#FAEDC6',pale:'#F4E7E7',muted:'#887575',light:'#EEE9E4'};

function text(s,H,value,x,y,w,h,size=28,color=C.text,bold=false,align='left'){
  return H.T(s,value,x,y,w,h,{size,color,bold,align});
}
function box(s,H,value,x,y,w,h,{fill=C.pale,size=27,color=C.text,bold=false,align='center',line='none'}={}){
  return H.B(s,value,x,y,w,h,{fill,line,size,color,bold,align});
}
function arrow(s,H,a,b,from='right',to='left',color=C.rose){H.Cn(s,a,b,from,to,{color,width:2});}
function panel(s,H,x,y,w,h,fill=C.bg){return H.R(s,x,y,w,h,{fill,line:'none',radius:true});}
function chip(s,H,label,x,y,w,fill=C.blush,size=24){return H.tag(s,label,x,y,w,{fill,size});}
function numbered(s,H,n,label,x,y,fill=C.rose){H.dot(s,String(n),x,y,{fill,size:24,r:25});text(s,H,label,x+64,y-2,345,52,27,C.ink,true);}

export function renderSecondary(s,p,H){
  const n=Number(p.page);
  if(n<21||n>38)return false;
  switch(n){
    case 21:{
      H.R(s,110,215,1452,570,{fill:C.bg,line:C.blush,width:2,radius:true});
      text(s,H,'50',170,275,240,160,112,C.ink,true,'center');
      text(s,H,'總容量上限',170,427,240,48,29,C.text,true,'center');
      chip(s,H,'預設 50',210,506,160,C.gold,25);
      chip(s,H,'最低 10',210,563,160,C.light,25);
      text(s,H,'4 個固定保護：永久保留，不淘汰',510,238,880,54,30,C.ink,true,'center');
      const guards=['AllInBot','Mayari','COAC','TMA'];
      const safe=guards.map((v,i)=>box(s,H,v,510+i*218,315,190,82,{fill:C.gold,size:25,bold:true}));
      text(s,H,'起始另有 6 個可替換基準',510,422,870,40,25,C.muted,true);
      ['PassiveAI','RandomAI','RandomBiasedAI','LightRush','HeavyRush','WorkerRush'].forEach((v,i)=>box(s,H,v,510+(i%3)*290,477+Math.floor(i/3)*82,267,66,{fill:C.pale,size:v==='RandomBiasedAI'?23:25}));
      text(s,H,'歷代策略累積',510,672,250,44,25,C.ink,true);
      for(let i=0;i<6;i++)H.dot(s,'',790+i*95,676,{fill:i<4?C.rose:C.blush,size:18,r:17});
      text(s,H,'評估名單 = 4 個保護對手 ＋ 從池中抽取 6 名動態對手',260,805,1180,40,25,C.ink,true,'center');
      return true;
    }
    case 22:{
      const a=box(s,H,'來源\nG0 初始族群\n每代已評估子代',90,270,300,176,{fill:C.gold,size:27,bold:true});
      const b=box(s,H,'入池資格\n可執行、完整評估\nID／來源／表型去重',495,270,350,176,{fill:C.pale,size:25});
      const c=box(s,H,'未滿容量\n直接加入',1080,260,300,120,{fill:C.gold,size:29,bold:true});
      const d=box(s,H,'已滿容量\nseeded 抽 1 位非保護守擂者',970,520,390,120,{fill:C.pale,size:26});
      const e=box(s,H,'18 場挑戰\n3 地圖 × 3 回合 × 2 邊',475,520,365,120,{fill:C.blush,size:27,bold:true});
      const f=box(s,H,'完整且無錯誤\n勝場 > 敗場才替換',90,520,300,120,{fill:C.gold,size:25,bold:true});
      arrow(s,H,a,b);arrow(s,H,b,c);arrow(s,H,b,d,'bottom','top');arrow(s,H,d,e,'left','right');arrow(s,H,e,f,'left','right');
      text(s,H,'平手、失敗或未完成：保留原守擂者',535,682,760,42,25,C.ink,true,'center');
      text(s,H,'候選入池不要求先成為下一代倖存者',400,745,870,35,23,C.muted,false,'center');
      return true;
    }
    case 23:{
      text(s,H,'固定 4 個保護欄位',160,232,440,48,29,C.ink,true);
      const guard=box(s,H,'4 個內建保護對手\n跨快照維持相同 case ID',160,298,415,124,{fill:C.gold,size:27,bold:true});
      text(s,H,'每個快照再抽 6 名',1070,232,440,48,29,C.ink,true,'right');
      for(let i=0;i<6;i++)box(s,H,'',940+i*94,328,68,68,{fill:i%2?C.blush:C.pale});
      text(s,H,'從歷代累積的可替換成員抽樣',940,420,570,40,24,C.muted,false,'center');
      const t0=box(s,H,'G0',180,520,160,88,{fill:C.blush,size:30,bold:true});
      const t1=box(s,H,'G1–5',535,520,220,88,{fill:C.pale,size:29,bold:true});
      const t2=box(s,H,'G6–10',925,520,220,88,{fill:C.blush,size:29,bold:true});
      const t3=box(s,H,'G11–15',1310,520,220,88,{fill:C.pale,size:28,bold:true});
      arrow(s,H,t0,t1);arrow(s,H,t1,t2);arrow(s,H,t2,t3);
      text(s,H,'全部 10 個內建對手',160,630,300,44,25,C.text,true);
      text(s,H,'首個抽樣快照',535,630,240,44,25,C.text,true,'center');
      text(s,H,'刷新預設每 5 代',925,630,240,44,25,C.text,true,'center');
      text(s,H,'G16… 持續刷新',1310,630,220,44,25,C.text,true,'center');
      box(s,H,'每個快照固定評估 10 個欄位：4 個保護成員 ＋ 6 個動態成員',300,728,1080,58,{fill:C.gold,size:27,bold:true});
      return true;
    }
    case 24:{
      numbered(s,H,1,'凍結對手名單',105,260);numbered(s,H,2,'建立父代複本',590,260);numbered(s,H,3,'新情境重評',1080,260);
      const a=box(s,H,'4＋6 對手\n保存 context hash',105,340,300,144,{fill:C.gold,size:27,bold:true});
      const b=box(s,H,'每位父代保留 phenotype\n配置新 candidate ID',590,340,340,144,{fill:C.pale,size:25});
      const c=box(s,H,'新情境重新評估\n不覆寫舊分數',1080,340,360,144,{fill:C.blush,size:27,bold:true});
      arrow(s,H,a,b);arrow(s,H,b,c);
      const d=box(s,H,'新 context 完成評分',920,610,350,90,{fill:C.gold,size:27,bold:true});
      const e=box(s,H,'再進入同一情境的繁殖選擇',390,610,390,90,{fill:C.pale,size:26});
      arrow(s,H,c,d,'bottom','top');arrow(s,H,d,e,'left','right');
      text(s,H,'不同對手情境的分數不混在同一選擇池',370,740,950,40,25,C.ink,true,'center');
      return true;
    }
    case 25:{
      const same=box(s,H,'對手快照未改變',100,245,640,92,{fill:C.ink,size:34,color:'#FFFFFF',bold:true});
      const changed=box(s,H,'對手快照到期刷新',930,245,640,92,{fill:C.rose,size:34,bold:true});
      const reuse=box(s,H,'沿用父代 Java\n沿用同情境的已完成分數',100,435,640,135,{fill:C.pale,size:31,bold:true});
      const refresh=box(s,H,'沿用父代 Java\n新 ID 複本，對新名單跑 180 場',930,435,640,135,{fill:C.gold,size:30,bold:true});
      arrow(s,H,same,reuse,'bottom','top');arrow(s,H,changed,refresh,'bottom','top');
      const joint=box(s,H,'先完成父代情境校準，再繁殖；子代也用同一快照評估',270,730,1130,80,{fill:C.blush,size:29,bold:true});
      arrow(s,H,reuse,joint,'bottom','top');arrow(s,H,refresh,joint,'bottom','top');
      text(s,H,'本流程要求 parent_evaluation_mode = reuse_cached；快照刷新自動執行表型不變的父代重評',180,840,1310,40,22,C.ink,false,'center');
      return true;
    }
    case 26:{
      text(s,H,'固定狀態探針',125,240,410,46,30,C.ink,true);
      const maps=['小地圖','中地圖','大地圖'];
      for(let r=0;r<3;r++){
        text(s,H,maps[r],115,336+r*122,160,64,24,C.muted,true,'center');
        for(let c=0;c<3;c++)box(s,H,['早期','中期','後期'][c],300+c*118,326+r*122,105,76,{fill:(r+c)%2?C.pale:C.gold,size:23,bold:true});
      }
      text(s,H,'3 地圖 × 3 階段 = 9 個動作簽章',155,730,540,42,25,C.ink,true,'center');
      const tie=box(s,H,'同分層',820,320,250,92,{fill:C.blush,size:31,bold:true});
      const dist=box(s,H,'比較九個 probe 的動作差異\n距離 = 不同 probe 數 ÷ 9',1190,310,350,118,{fill:C.pale,size:26});
      arrow(s,H,tie,dist);
      const boundary=box(s,H,'父代：頂層挑行為較遠者\n倖存者：切分同層時採 max-min',895,560,500,120,{fill:C.gold,size:26,bold:true});
      arrow(s,H,dist,boundary,'bottom','top');
      text(s,H,'語意探針只解決同分，不另加搜尋目標',865,716,520,46,24,C.muted,true,'center');
      return true;
    }
    case 27:{
      const pool=box(s,H,'N 父代＋N 子代\n合併、依 ID 去重',80,260,400,125,{fill:C.gold,size:30,bold:true});
      const done=box(s,H,'只留下\n完整評估者',610,260,320,125,{fill:C.pale,size:30,bold:true});arrow(s,H,pool,done);
      const tiers=box(s,H,'依 fitness 由高至低\n以每層最高分 − 1.0 分層',1060,260,500,125,{fill:C.blush,size:29,bold:true});arrow(s,H,done,tiers);
      text(s,H,'整層放得下',90,520,480,48,31,C.ink,true,'center');
      box(s,H,'整層保留\n再處理下一個分數層',90,605,480,125,{fill:C.pale,size:31,bold:true});
      text(s,H,'剩餘名額切在同一層',760,520,780,48,31,C.ink,true,'center');
      box(s,H,'只在該層用 seeded max-min 選子集\n優先保留與已選者行為較遠的候選',760,605,780,125,{fill:C.gold,size:29,bold:true});
      H.L(s,1310,385,1310,450);H.L(s,330,450,1310,450);H.L(s,330,450,330,505,{arrow:true});H.L(s,1150,450,1150,505,{arrow:true});
      text(s,H,'選滿固定 N 位；低分層不能靠新穎性越級。完成者不足 N，run 明確失敗。',160,825,1370,44,25,C.ink,true,'center');
      return true;
    }
    case 28:{
      text(s,H,'self_play 要求 reflection_operator_mode = static',130,195,1390,60,34,C.ink,true,'center');
      const child=box(s,H,'交配後的子代',80,330,340,100,{fill:C.gold,size:32,bold:true});
      const gate=box(s,H,'固定 mutation_rate\n決定是否突變',560,330,420,100,{fill:C.pale,size:31,bold:true});arrow(s,H,child,gate);
      const mutate=box(s,H,'依已設定的靜態規則\n執行可用突變操作',1130,290,450,135,{fill:C.blush,size:30,bold:true});arrow(s,H,gate,mutate);
      const next=box(s,H,'進入 Java 與評估',1130,650,450,100,{fill:C.ink,size:32,color:'#FFFFFF',bold:true});arrow(s,H,mutate,next,'bottom','top');
      H.L(s,770,430,770,700);H.L(s,770,700,1130,700,{arrow:true});
      text(s,H,'否：保留交配後基因',800,555,300,50,25,C.muted,true,'center');
      text(s,H,'是',1020,300,80,45,26,C.ink,true,'center');
      text(s,H,'Framework local：至多改一槽\nFramework Coach：回傳完整 genome\nLLM／DSL：依可用操作與固定配比',80,525,630,150,28,C.text,false);
      text(s,H,'對戰結果提供 fitness 與反思證據；本流程不以 reward 動態更新操作機率',170,825,1330,44,25,C.ink,true,'center');
      return true;
    }
    case 29:{
      const gen=box(s,H,'LLM 產生',70,250,200,82,{fill:C.ink,size:26,color:'#FFFFFF',bold:true});
      const val=box(s,H,'Validation',315,250,200,82,{fill:C.gold,size:25,bold:true});
      const javac=box(s,H,'javac',560,250,200,82,{fill:C.pale,size:26,bold:true});
      const integ=box(s,H,'Integration',805,250,200,82,{fill:C.blush,size:25,bold:true});
      const match=box(s,H,'180 場評估',1050,250,200,82,{fill:C.pale,size:25,bold:true});
      const select=box(s,H,'候選篩選',1295,250,240,82,{fill:C.gold,size:26,bold:true});
      arrow(s,H,gen,val);arrow(s,H,val,javac);arrow(s,H,javac,integ);arrow(s,H,integ,match);arrow(s,H,match,select);
      const repair=box(s,H,'有界修復重試\nLLM 模式限 generation_max_attempts',290,430,475,104,{fill:C.blush,size:24,bold:true});
      arrow(s,H,val,repair,'bottom','top');arrow(s,H,javac,repair,'bottom','top');arrow(s,H,repair,gen,'top','bottom');
      const intFail=box(s,H,'Integration\n失敗，候選終止',785,430,215,96,{fill:C.blush,size:22,bold:true});
      const matFail=box(s,H,'矩陣未完成\n候選終止',1040,430,215,78,{fill:C.blush,size:23,bold:true});
      arrow(s,H,integ,intFail,'bottom','top');arrow(s,H,match,matFail,'bottom','top');
      text(s,H,'DSL／framework 編譯失敗亦直接終止候選',815,539,470,42,23,C.muted,true,'center');
      text(s,H,'失敗候選 sentinel',840,597,260,42,24,C.text,true,'center');
      text(s,H,'−1000',1090,575,245,82,58,C.ink,true,'center');
      const enough=box(s,H,'完成者 ≥ N\n父代足夠時仍可延續',225,690,510,92,{fill:C.gold,size:26,bold:true});
      const insufficient=box(s,H,'完成者 < N\nrun 明確失敗',925,690,510,92,{fill:C.blush,size:26,bold:true});
      text(s,H,'中斷：取消排隊工作、等待執行中工作，再從最後提交世代恢復',330,795,1010,36,22,C.muted,false,'center');
      return true;
    }
    case 30:{
      const root=box(s,H,'runs/<run_id>/',590,220,500,70,{fill:C.ink,size:30,color:'#FFFFFF',bold:true});
      const a=box(s,H,'config.yaml\nmanifest.json\nsummary.json',130,375,360,142,{fill:C.gold,size:25,bold:true});
      const b=box(s,H,'generations/\n候選快照與 latest_generation',520,375,360,142,{fill:C.blush,size:24,bold:true});
      const c=box(s,H,'candidates/\n基因、譜系、逐階段證據',910,375,360,142,{fill:C.pale,size:24,bold:true});
      const d=box(s,H,'archives/\n操作、錯誤與 opponent pool',1300,375,300,142,{fill:C.gold,size:24,bold:true});
      arrow(s,H,root,a,'bottom','top');arrow(s,H,root,b,'bottom','top');arrow(s,H,root,c,'bottom','top');arrow(s,H,root,d,'bottom','top');
      const framework=box(s,H,'framework/bundle.json\nFramework slots 凍結來源',225,600,500,92,{fill:C.blush,size:24,bold:true});
      box(s,H,'timing.jsonl：append-only 階段與 LLM request 時間線',790,600,420,92,{fill:C.pale,size:23});
      box(s,H,'final_test/\n獨立正式測試證據',1270,600,300,92,{fill:C.pale,size:23});
      arrow(s,H,root,framework,'bottom','top');
      text(s,H,'generation snapshot 原子寫入成功後，manifest 才前進',420,745,820,42,25,C.ink,true,'center');
      return true;
    }
    case 31:{
      const cp=box(s,H,'1  最後提交快照\nmanifest\nlatest_generation = Gk',80,270,340,122,{fill:C.ink,size:24,color:'#FFFFFF',bold:true});
      const check=box(s,H,'2  身分相容檢查\nprotocol · config · hash',470,270,340,122,{fill:C.gold,size:25,bold:true});
      const archive=box(s,H,'3  封存未提交工作\ninterrupted_work/',860,270,340,122,{fill:C.blush,size:25,bold:true});
      const restore=box(s,H,'4  還原 population\n操作器、pool 與 context',860,560,340,122,{fill:C.pale,size:25,bold:true});
      const replay=box(s,H,'5  重播並繼續\n從 Gk + 1 開始',360,560,340,122,{fill:C.gold,size:27,bold:true});
      arrow(s,H,cp,check);arrow(s,H,check,archive);arrow(s,H,archive,restore,'bottom','top');arrow(s,H,restore,replay,'left','right');
      text(s,H,'身分不符即拒絕；不沿用半成品，也不重新 bootstrap',280,740,1120,46,25,C.ink,true,'center');
      return true;
    }
    case 32:{
      text(s,H,'設定資料夾依 YAML 檔名順序逐組執行',150,228,710,48,28,C.ink,true);
      const groups=['設定 A','設定 B','設定 C'];
      groups.forEach((g,i)=>{
        const x=150+i*500;
        box(s,H,g,x,315,180,64,{fill:C.ink,size:25,color:'#FFFFFF',bold:true});
        box(s,H,'Run 1',x,410,170,62,{fill:C.pale,size:24,bold:true});
        box(s,H,'Run 2',x+205,410,170,62,{fill:C.gold,size:24,bold:true});
      });
      const seeds=['7','7','8','8','9','9'];
      text(s,H,'random_seeds × runs',155,564,300,44,26,C.muted,true);
      seeds.forEach((v,i)=>{
        const x=475+i*162;box(s,H,`seed ${v}`,x,555,140,66,{fill:i%2?C.blush:C.gold,size:25,bold:true});
        if(i<seeds.length-1)H.L(s,x+143,588,x+157,588,{color:C.rose,width:2,arrow:true});
      });
      text(s,H,'experiment.yaml 以有序 slot 記錄 run 路徑；未完成優先恢復，完整項目可跳過。',250,700,1160,52,25,C.ink,true,'center');
      text(s,H,'正式 run 需 Final Test 摘要才算 slot 完成；缺 G0 證據則建立替代 run。',250,765,1160,42,23,C.muted,false,'center');
      return true;
    }
    case 33:{
      const seed=box(s,H,'root seed\ntask identity + input index',610,220,440,92,{fill:C.ink,size:27,color:'#FFFFFF',bold:true});
      const streams=['初始化','選擇','操作','LLM request','MicroRTS match'];
      const dest=streams.map((v,i)=>box(s,H,v,100+i*305,430,240,88,{fill:i%2?C.pale:C.gold,size:24,bold:true}));
      H.L(s,830,312,830,365,{color:C.rose,width:2});
      H.L(s,220,365,1440,365,{color:C.rose,width:2});
      dest.forEach((d,i)=>H.L(s,220+i*305,365,220+i*305,423,{color:C.rose,width:2,arrow:true}));
      const gate=box(s,H,'保存與核對\nconfig · source · map · runtime · bundle hashes',300,555,560,120,{fill:C.pale,size:25,bold:true});
      const risk=box(s,H,'仍可能改變\n外部模型、GPU 執行、私有 RNG、時間上限',930,555,480,120,{fill:C.blush,size:24});
      text(s,H,'相同 seed 建立可控隨機流，不保證外部服務逐位元相同',330,736,1010,46,25,C.ink,true,'center');
      return true;
    }
    case 34:{
      const stop=box(s,H,'停止條件',95,280,260,86,{fill:C.ink,size:29,color:'#FFFFFF',bold:true});
      const limit=box(s,H,'世代上限\n或 stagnation',420,260,300,126,{fill:C.gold,size:27,bold:true});
      arrow(s,H,stop,limit);
      const rep=box(s,H,'選可執行代表\n通常取末代候選',790,250,300,112,{fill:C.pale,size:25,bold:true});
      const compile=box(s,H,'獨立 recompile\n＋七項 Integration',1190,250,360,112,{fill:C.blush,size:25,bold:true});
      arrow(s,H,limit,rep);arrow(s,H,rep,compile);
      const finalMatrix=box(s,H,'Final Test\n固定十個內建對手',1210,385,340,76,{fill:C.ink,size:24,color:'#FFFFFF',bold:true});
      arrow(s,H,compile,finalMatrix,'bottom','top');
      text(s,H,'三種對戰矩陣各有用途',180,455,800,50,30,C.ink,true);
      const items=[['180','搜尋評估','10 對手 × 3 地圖 × 3 回合 × 2 邊'],['18','Pool 挑戰','3 地圖 × 3 回合 × 2 邊'],['600','Final Test','10 對手 × 3 地圖 × 10 回合 × 2 邊']];
      const xs=[170,665,1160];
      items.forEach((v,i)=>{
        text(s,H,v[0],xs[i],565,280,105,76,i===2?C.ink:C.rose,true,'center');
        text(s,H,v[1],xs[i],665,280,42,27,C.ink,true,'center');
        text(s,H,v[2],xs[i]-40,720,360,56,22,C.muted,false,'center');
      });
      text(s,H,'mock 與 --skip-final-test 可略過',780,404,400,38,23,C.muted,false,'center');
      text(s,H,'搜尋名單會刷新；正式測試名單固定，兩者分開保存結果',180,813,1330,44,25,C.ink,true,'center');
      return true;
    }
    case 35:{
      text(s,H,'搜尋：對手快照隨世代改變',95,220,620,48,28,C.ink,true,'center');
      const snapshots=[['G0','4 保護\n＋6 內建'],['G6','4 保護\n＋6 抽樣'],['G11','4 保護\n＋6 抽樣']];
      snapshots.forEach((v,i)=>{
        const x=110+i*190;
        box(s,H,v[0],x,302,150,54,{fill:C.ink,size:24,color:'#FFFFFF',bold:true});
        box(s,H,v[1],x,369,150,94,{fill:i===0?C.gold:C.pale,size:22,bold:true});
      });
      H.L(s,205,495,585,495,{color:C.rose,width:2,arrow:true});
      text(s,H,'fitness 隨情境變動\n每個候選 180 場',135,540,470,86,25,C.text,true,'center');
      text(s,H,'公平比較：一份凍結 protocol',745,220,830,48,28,C.ink,true,'center');
      const reps=['G0','G5','G10','G15','G20'];
      const repShapes=reps.map((v,i)=>box(s,H,v,760,295+i*76,115,56,{fill:i%2?C.pale:C.gold,size:24,bold:true}));
      const protocol=box(s,H,'同一固定 protocol\n固定對手、地圖、規則',1010,382,310,122,{fill:C.blush,size:25,bold:true});
      repShapes.forEach(r=>arrow(s,H,r,protocol));
      const score=box(s,H,'每個代表 600 場\npaired seeds',1370,394,220,100,{fill:C.ink,size:25,color:'#FFFFFF',bold:true});
      arrow(s,H,protocol,score);
      text(s,H,'不同快照的搜尋分數，不能當成同條件能力比較。',375,720,960,48,26,C.ink,true,'center');
      return true;
    }
    case 36:{
      chip(s,H,'排程示意，非量測',120,220,285,C.gold,23);
      const g0=box(s,H,'G0 初始化\n獨立工作量',110,315,220,108,{fill:C.ink,size:25,color:'#FFFFFF',bold:true});
      text(s,H,'後續演化世代的重疊工作',405,235,1010,44,28,C.ink,true,'center');
      text(s,H,'準備子代',365,325,185,52,24,C.muted,true,'center');
      text(s,H,'十工人對戰矩陣',365,525,185,52,24,C.muted,true,'center');
      const prep1=box(s,H,'準備批次 A',570,315,260,86,{fill:C.pale,size:25,bold:true});
      const prep2=box(s,H,'準備批次 B',905,315,260,86,{fill:C.pale,size:25,bold:true});
      const prep3=box(s,H,'準備批次 C',1240,315,260,86,{fill:C.pale,size:25,bold:true});
      const match1=box(s,H,'對戰 A',710,515,310,86,{fill:C.blush,size:26,bold:true});
      const match2=box(s,H,'對戰 B',1045,515,310,86,{fill:C.blush,size:26,bold:true});
      text(s,H,'A 對戰期間，B 的準備已開始',715,425,360,42,23,C.text,true,'center');
      text(s,H,'B 對戰期間，C 的準備已開始',1050,625,390,42,23,C.text,true,'center');
      H.L(s,570,710,1500,710,{color:C.ink,width:3,arrow:true});
      text(s,H,'wall time',570,730,930,40,24,C.ink,true,'center');
      text(s,H,'G0 初始化另行記錄；世代／階段時間以實際 timing artifacts 為準。',365,771,1140,30,21,C.muted,false,'center');
      chip(s,H,'目前未有 live 多主機 speedup benchmark',480,818,720,C.blush,22);
      return true;
    }
    case 37:{
      const a=box(s,H,'GUI',150,300,340,115,{fill:C.ink,size:34,color:'#FFFFFF',bold:true});
      const b=box(s,H,'Monitor',665,300,340,115,{fill:C.rose,size:32,bold:true});
      const c=box(s,H,'Analyze',1180,300,340,115,{fill:C.gold,size:32,bold:true});
      arrow(s,H,a,b);arrow(s,H,b,c);
      box(s,H,'選設定、啟停／續跑\n瀏覽族群與視覺觀戰',115,485,410,128,{fill:C.pale,size:25});
      box(s,H,'讀 manifest 與已提交快照\n狀態監看唯讀',630,485,410,128,{fill:C.pale,size:25});
      box(s,H,'讀保存的快照與證據\n離線產生報表與圖',1145,485,410,128,{fill:C.pale,size:25});
      text(s,H,'使用工具檢視證據，不改寫演化 fitness',390,700,900,50,28,C.ink,true,'center');
      return true;
    }
    case 38:{
      box(s,H,'Framework slots',120,240,430,72,{fill:C.ink,size:30,color:'#FFFFFF',bold:true});
      text(s,H,'Coach 使用完整控制 genome',120,330,430,42,25,C.text,true,'center');
      box(s,H,'Mistral bootstrap',660,240,400,72,{fill:C.gold,size:29,bold:true});
      text(s,H,'mistral-small-latest',660,330,400,42,25,C.text,true,'center');
      box(s,H,'Qwen 3.5 9B',1170,240,390,72,{fill:C.rose,size:30,bold:true});
      text(s,H,'主模型＋外部 additional endpoint',1170,330,390,42,22,C.text,true,'center');
      const nums=[['20','演化世代'],['10','population'],['8','seed'],['50','pool capacity']];
      nums.forEach((v,i)=>{
        const x=130+i*380;
        text(s,H,v[0],x,465,300,96,66,i===3?C.ink:C.rose,true,'center');
        text(s,H,v[1],x,560,300,42,25,C.text,true,'center');
      });
      box(s,H,'每次評估：4 個保護對手 ＋ 6 個抽樣對手',290,650,1090,72,{fill:C.pale,size:28,bold:true});
      chip(s,H,'refresh 5',280,758,190,C.blush,23);
      chip(s,H,'crossover 0.75',550,758,240,C.gold,23);
      chip(s,H,'mutation 1.0',870,758,230,C.pale,23);
      chip(s,H,'tick caps 1500／3000／4000',1160,758,380,C.blush,22);
      text(s,H,'這是 checked-in 範例設定，不代表全域預設或已執行實驗。',470,817,760,34,22,C.muted,false,'center');
      return true;
    }
  }
  return false;
}
