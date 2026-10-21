export const STABILITY_SLIDE_COUNT=7;
export const STABILITY_CHART_SLIDES=[40,41,42,43,44];
export const STABILITY_TABLE_SLIDES=[39,42,43];

export function stabilityPages(d){
  const source=`來源：reports/1021_framework_stability_comparison.md；SHA-256 ${d.source.sha256}。報告快照：${d.source.report_snapshot_label}。未刷新即時批次狀態。`;
  const pages=[
    ['穩定性比較：相同 framework，兩批重跑',`兩批均為 framework_slots、framework.evolution_mode=local、population_size=10、演化 G1–20、self_play 與 tournament-v1。相同 bundle SHA-256：b2daa0d4baac80e446d46e5d32f6fd94a4300bec51f23b4816723c6d8f90939b。靜態操作，搜尋期間不呼叫 candidate-time LLM。報告指出 resolved config 的實質差異僅 experiment name、seed 清單與 run-owned bundle 路徑，bundle bytes 相同。上次六 run 為 10/19–10/20，本次批次為 10/21。11 個完成 run 的 G20 均 1800/1800、failure_count=0；每個 Final Test 均 600 場、Integration success、0 errors。這支持已測配置與矩陣的執行可靠性，不代表所有情境無錯誤。\n完整 run 索引：${JSON.stringify(d.run_status)}\n未完成項：${JSON.stringify(d.pending_seed13)}`],
    ['G20 搜尋分數：重跑差異因 seed 而異',`縱軸為各 run G20 population best Game Performance，非 population mean。主圖只並列 seed 8–12；上次 seed13 另列，避免將本次未完成 seed13 填成零。各 run 的 opponent-pool 快照可能不同，這些值只描述各自搜尋情境，不是固定難度的能力比較。上次六 seed best 平均 5.884，本次五 seed 1.861；樣本不齊，不能以 -4.023 推論架構退化。seed10 的兩個 G20 best 差 0.004 是觀察，不足以歸因其他 run 差異的原因。\nG20 全部 best、population mean、population sd、semantic unique：${JSON.stringify(d.g20)}`],
    ['搜尋軌跡：同 seed 的形狀多次接近',`六個圖共用相同縱軸 -80 到 40，橫軸 G0、G5、G10、G15、G20，數值為該世代 population best。上次用玫瑰色，本次用酒紅色。seed13 只有上次完整軌跡，本次 G4 不放入 G20 曲線。對手快照會刷新，曲線僅描述 run 內的搜尋情境，不能視為固定對手難度下的能力成長。seed10 兩次軌跡接近且 G20 回落至約 -32；這是可觀察的搜尋路徑，不能單憑曲線判定因果。\n完整軌跡：${JSON.stringify(d.trajectories)}`],
    ['正式測試：零執行錯誤，勝率約三成',`相同正式測試協定，每 run 為十對手、三地圖、每邊十場，共六百場。圖中各組百分比由 W、D、L 除以該組 matches 計算；W/D/L/E 欄位順序固定。兩批分母為 3600 與 3000，本次排除 seed13。報告勝率 32.33% 與 30.17% 是各批聚合，不是相同 seed 配對效果，不能據此判定架構退化。所有 11 個完成 Final Test Integration success、0 errors。\n完整正式測試資料：${JSON.stringify(d.final_test)}`],
    ['Hard opponents 仍是共同弱點',`本次已完成 seed8–12，每個對手五 run × 六十場=三百場。AllInBot、Mayari、COAC、TMA 合計 1200 場、11 勝、14 和、1175 敗、0 errors；勝率 0.92% 為計算值。COAC 的十勝集中於 seed11。其餘能力剖面依報告：PassiveAI／RandomAI 穩定取勝或打平；RandomBiasedAI 有較多勝場但 seed 間差異明顯；三種 Rush 尚無一致 counter。報告未提供這六個對手的逐項勝和敗數，不另造數值。\n四個 hard opponents 原始資料：${JSON.stringify(d.hard_opponents_current)}`],
    ['九狀態探針：末代行為多樣性偏低',`圖中為 G20 semantic unique／population10，並列 seed8–12；上次 seed13=4 另列，本次 seed13未納入。上次六 run 為 [1,2,2,1,1,4]，本次五 run 為 [3,1,2,1,1]。多數 run 在九個固定探針中只剩一到兩種行為簽章，不等於在所有遊戲狀態中只有一到兩種行為。Framework 不使用 Strategy DSL niche；known_signature_count=0 不能拿來判定 framework 行為沒有多樣性。population mean 和 population sd 請見完整 G20 資料。\n完整 G20 資料：${JSON.stringify(d.g20)}`],
    ['結論：執行可靠，探索與能力仍待改善',`報告結論分開理解：11 個已完成 run 支持此配置與已測矩陣的執行可靠性；跨 seed 結果與 hard-opponent 能力仍不一致；末代九狀態簽章多為一到兩類。現有搜尋分數受快照情境影響，不足以作架構退化或一般化能力改善的因果判定。建議先等報告中的 seed13完成，再補齊同六 seed 的正式測試比較；若目標是策略品質，控制條件測試語意探索與 hard-opponent coverage，而非先改 materialization。建議尚未執行，沒有啟動新實驗。\n耗時證據缺口：${JSON.stringify(d.timing_evidence)}。報告沒有 run wall time、G0 與 G1–20 完成世代耗時；不能由分數表推導時間，也不報加速比。`],
  ];
  return pages.map(([title,notes],i)=>({page:39+i,title,notes:`${source}\n\n${notes}`}));
}

export function renderStability(s,p,H,d){
  if(p.page<39||p.page>45)return false;
  const {T,B,L,Cn,C,sub,foot,F,applyChartFont}=H;
  const prev=d.g20.previous.rows,cur=d.g20.current_completed.rows;
  const seeds=[8,9,10,11,12],pairedPrev=seeds.map(seed=>prev.find(r=>r.seed===seed));
  const fmt=v=>Number(v).toFixed(3);
  function chart(type,categories,series,pos,opts={}){
    const ch=s.charts.add(type,{
      position:pos,categories,series,hasLegend:series.length>1,
      legend:{position:'bottom',textStyle:{fontSize:22,typeface:F,fill:C.text}},
      chartFill:C.bg,plotAreaFill:C.bg,
      xAxis:{textStyle:{fontSize:23,typeface:F,fill:C.text},tickLabelPosition:'low'},
      yAxis:{textStyle:{fontSize:21,typeface:F,fill:C.text},majorGridlines:{fill:C.blush,width:0.6}},
      dataLabels:{showValue:true,position:'outEnd',numberFormatCode:'0.000',textStyle:{fontSize:23,typeface:F,fill:C.ink}},
      ...opts,
    });
    applyChartFont(ch,{fontFamily:F});return ch;
  }
  function table(values,x,y,w,h,widths,size=25){
    const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,columnWidths:widths,values});
    t.borders.assign({fill:C.blush,width:0.6});
    t.cells.block({row:0,column:0,rowCount:values.length,columnCount:values[0].length}).assign({margins:{top:3,bottom:3,left:10,right:10}});
    values.forEach((row,r)=>{t.rows[r].height=h/values.length;row.forEach((v,c)=>{const cell=t.getCell(r,c);cell.fill=r===0?C.blush:C.bg;cell.text.style={typeface:F,fontSize:size,color:C.text,bold:r===0,alignment:c===0?'left':'center',autoFit:'none'};});});
    return t;
  }
  function series(field){return [{name:'上次',values:pairedPrev.map(r=>r[field]),fill:C.rose},{name:'本次已完成',values:cur.map(r=>r[field]),fill:C.ink}];}
  switch(p.page){
    case 39:{
      sub(s,'Framework local＋Opponent Pool｜上次 6 個 seed；本次完成 5 個，seed 13 尚未完成');
      const a=B(s,'同一凍結 bundle\nb2daa0d4…0939b',80,235,430,110,{fill:C.gold,size:30,bold:true});
      const b=B(s,'local 有限槽位演化\n搜尋期間無 LLM 呼叫',630,235,430,110,{fill:C.pale,size:30,bold:true});Cn(s,a,b);
      const c=B(s,'人口 10 × 演化 20 代\n180 場搜尋／600 場測試',1180,235,410,110,{fill:C.blush,size:29,bold:true});Cn(s,b,c);
      [['11','已完成 run'],['1800／1800','完成 run 的 G20 對戰'],['0','完成 Final Test 的 errors']].forEach((v,i)=>{
        const x=75+i*520;T(s,v[0],x,414,500,115,{size:i===1?65:86,color:C.ink,bold:true,align:'center'});T(s,v[1],x,530,500,46,{size:27,align:'center'});
      });
      table([['批次','seed 範圍','20 代完成','Final Test 完成'],['上次（10/19–20）','8–13','6／6','6 × 600 場'],['本次（10/21）','8–12 完成；13 待完','5／6','5 × 600 場']],80,638,1510,174,[380,460,300,370],26);
      foot(s,'依 10/21 報告快照：seed 13 在 G4／20，Final Test 尚未開始；未納入完成批次統計');
      return true;
    }
    case 40:{
      sub(s,'G20 population best Game Performance；主圖只並列已完成的 seed 8–12');
      chart('bar',seeds.map(String),series('best'),{left:75,top:225,width:1130,height:525},{barOptions:{direction:'column',grouping:'clustered',gapWidth:30},yAxis:{min:-45,max:35,majorUnit:20,textStyle:{fontSize:21,typeface:F,fill:C.text},majorGridlines:{fill:C.blush,width:0.6}},dataLabels:{showValue:true,position:'outEnd',numberFormatCode:'0.000',textStyle:{fontSize:20,typeface:F,fill:C.ink}}});
      T(s,'跨 seed 的 best 平均',1250,245,340,58,{size:28,color:C.ink,bold:true});
      T(s,'上次 6 seed\n5.884\n\n本次 5 seed\n1.861',1250,315,340,280,{size:31,color:C.text});
      T(s,'上次 seed 13：18.267\n本次尚未完成',1250,645,340,90,{size:24,color:C.muted});
      const delta=cur.map(r=>{const v=r.best-prev.find(q=>q.seed===r.seed).best;return (v>=0?'+':'')+fmt(v);});
      T(s,'本次 − 上次（seed 8→12）：'+delta.join('、'),80,769,1510,50,{size:26,color:C.ink,bold:true});
      foot(s,'各 run 對手快照可能不同，且平均樣本數不齊；不能用這些搜尋分數判定一般化能力或架構退化');
      return true;
    }
    case 41:{
      sub(s,'population best｜相同縱軸 −80～40；各點代表該代當下的對手快照');
      L(s,1120,192,1170,192,{color:C.rose,width:4});T(s,'上次',1185,172,120,40,{size:23});L(s,1330,192,1380,192,{color:C.ink,width:4});T(s,'本次',1395,172,150,40,{size:23});
      for(let i=0;i<6;i++){
        const seed=i+8,x=65+(i%3)*535,y=240+Math.floor(i/3)*290;
        T(s,seed===13?'seed 13｜僅上次完整結果':`seed ${seed}`,x+20,y-24,480,42,{size:26,color:C.ink,bold:true});
        const rows=d.trajectories.rows.filter(r=>r.seed===seed);
        chart('line',['G0','G5','G10','G15','G20'],rows.map(r=>({name:r.cohort,values:['g0','g5','g10','g15','g20'].map(k=>r[k]),line:{fill:r.cohort==='上次'?C.rose:C.ink,width:3},marker:{symbol:r.cohort==='上次'?'circle':'diamond',size:5,fill:r.cohort==='上次'?C.rose:C.ink}})),{left:x,top:y+22,width:505,height:237},{hasLegend:false,lineOptions:{smooth:false},dataLabels:{showValue:false},xAxis:{textStyle:{fontSize:18,typeface:F,fill:C.text},tickLabelPosition:'low'},yAxis:{min:-80,max:40,majorUnit:40,textStyle:{fontSize:18,typeface:F,fill:C.text},majorGridlines:{fill:C.blush,width:0.5}}});
      }
      foot(s,'seed 10 的重跑路徑接近；快照會刷新，曲線不能視為固定難度下的能力成長');
      return true;
    }
    case 42:{
      sub(s,'相同 600 場協定；本次排除 seed 13。圖示各批 W／D／L 百分比，表列實際場數');
      const rows=d.final_test.cohorts;
      chart('bar',['上次｜6 runs，3600 場','本次｜5 runs，3000 場'],[
        {name:'勝 W',values:rows.map(r=>Number((100*r.wins/r.matches).toFixed(4))),fill:C.rose},
        {name:'和 D',values:rows.map(r=>Number((100*r.draws/r.matches).toFixed(4))),fill:C.gold,dataLabels:{showValue:false}},
        {name:'敗 L',values:rows.map(r=>Number((100*r.losses/r.matches).toFixed(4))),fill:C.ink},
      ],{left:80,top:225,width:1510,height:416},{barOptions:{direction:'column',grouping:'stacked',overlap:100,gapWidth:170},yAxis:{min:0,max:100,majorUnit:25,numberFormatCode:'0"%"',textStyle:{fontSize:22,typeface:F,fill:C.text},majorGridlines:{fill:C.blush,width:0.6}},dataLabels:{showValue:true,position:'center',numberFormatCode:'0.0"%"',textStyle:{fontSize:24,typeface:F,fill:C.bg}}});
      table([['批次','勝 W','和 D','敗 L','錯誤 E','勝率'],...rows.map((r,i)=>[i===0?'上次（6 runs）':'本次（5 runs）',r.wins,r.draws,r.losses,r.errors,r.aggregate_win_rate_percent.toFixed(2)+'%'])],80,675,1510,150,[410,200,200,200,200,300],26);
      foot(s,'這是 6 run 與 5 run 的批次總勝率，非同 seed 配對效果；不足以判定架構退化');
      return true;
    }
    case 43:{
      sub(s,'本次已完成 seed 8–12；每個對手 5 runs × 60 場＝300 場');
      const rows=d.hard_opponents_current.rows;
      chart('bar',rows.map(r=>r.opponent),[{name:'勝 W',values:rows.map(r=>r.wins),fill:C.rose},{name:'和 D',values:rows.map(r=>r.draws),fill:C.gold},{name:'敗 L',values:rows.map(r=>r.losses),fill:C.ink}],{left:80,top:225,width:1110,height:398},{barOptions:{direction:'column',grouping:'stacked',overlap:100,gapWidth:100},yAxis:{min:0,max:300,majorUnit:100,textStyle:{fontSize:21,typeface:F,fill:C.text},majorGridlines:{fill:C.blush,width:0.6}},dataLabels:{showValue:false}});
      T(s,'11／1200',1250,255,340,100,{size:60,color:C.ink,bold:true,align:'center'});T(s,'四個強敵的合計勝場\n0 errors',1230,365,370,100,{size:27,align:'center'});
      T(s,'COAC 的 10 勝\n集中於 seed 11\nRush 對策也未一致',1250,505,340,115,{size:25,color:C.muted});
      table([['對手','勝 W','和 D','敗 L'],...rows.map(r=>[r.opponent,r.wins,r.draws,r.losses])],80,649,1510,190,[610,300,300,300],24);
      foot(s,'完成整個矩陣表示執行鏈可用；對 hard opponents 的策略能力仍不足');
      return true;
    }
    case 44:{
      sub(s,'G20 semantic unique／人口 10；三張地圖 × 三個階段的動作簽章');
      chart('bar',seeds.map(String),series('semantic_unique'),{left:75,top:240,width:1130,height:540},{barOptions:{direction:'column',grouping:'clustered',gapWidth:110},yAxis:{min:0,max:10,majorUnit:2,textStyle:{fontSize:22,typeface:F,fill:C.text},majorGridlines:{fill:C.blush,width:0.6}},dataLabels:{showValue:true,position:'outEnd',numberFormatCode:'0',textStyle:{fontSize:29,typeface:F,fill:C.ink}}});
      T(s,'末代多為\n1–2 類／10 人',1240,280,350,180,{size:45,color:C.ink,bold:true});
      T(s,'上次 seed 13：4 類\n本次 seed 13 未納入',1240,540,350,100,{size:26,color:C.muted});
      foot(s,'九狀態簽章不代表所有遊戲狀態；framework 沒有 DSL niche，不能以該 niche 的 count＝0 判斷行為多樣性');
      return true;
    }
    case 45:{
      sub(s,'觀察到執行可靠性；策略品質與一般化能力仍須分開驗證');
      const rows=[['執行可靠性','11 個完成 run\nFinal Test：0 errors','支持已測配置與矩陣可穩定執行'],['跨 seed 結果','seed 10 的 G20 差 0.004\n其他 seed 有重跑差異','搜尋分數受快照影響，另用共同測試比較'],['探索與能力','末代多為 1–2 類\n強敵合計 11／1200 勝','優先檢驗探索寬度與強敵涵蓋']];
      rows.forEach((r,i)=>{const y=240+i*150;T(s,r[0],80,y,300,60,{size:33,color:C.ink,bold:true});B(s,r[1],405,y-8,520,113,{fill:i===2?C.gold:C.pale,size:28,bold:true});T(s,r[2],1035,y,555,100,{size:27,color:C.text});L(s,925,y+48,1005,y+48,{arrow:true});});
      T(s,'建議下一步（尚未執行）',80,705,650,45,{size:29,color:C.ink,bold:true});
      const a=B(s,'補齊 seed 13',80,765,350,62,{fill:C.blush,size:28,bold:true});const b=B(s,'比較同六 seed 的正式測試',560,765,540,62,{fill:C.gold,size:27,bold:true});const c=B(s,'控制條件測試探索改動',1230,765,360,62,{fill:C.pale,size:25,bold:true});Cn(s,a,b);Cn(s,b,c);
      foot(s,'耗時比較缺測：run wall time、G0 與 G1–20 世代耗時未提供，無法判斷速度差異');
      return true;
    }
  }
}
