export const STABILITY_SLIDE_COUNT=7;
export const STABILITY_CHART_SLIDES=[40,41,42,44];
export const STABILITY_TABLE_SLIDES=[39,42,43,44,45];

export function stabilityPages(d){
  const source='來源：'+d.source.remote_refresh.artifact_root+'/runs/<run_id>；數據截點：'+d.source.data_snapshot_label+'。欄位來源：'+JSON.stringify(d.source.remote_refresh)+'。原報告 reports/1021_framework_stability_comparison.md；SHA-256 '+d.source.sha256+'。';
  const pages=[
    ['實驗批次與完成場數','模式：framework_slots / local；population 10；G1–20；self_play / tournament-v1；搜尋 180 場／candidate；Final Test 600 場／run。\n批次與 run：'+JSON.stringify(d.run_status)],
    ['G20 搜尋分數','指標：G20 population best、population mean、population sd、semantic unique。\n'+JSON.stringify(d.g20)],
    ['G0–G20 搜尋分數紀錄','各世代 population best；世代為 G0、G5、G10、G15、G20。\n'+JSON.stringify(d.trajectories)],
    ['正式測試：勝、和、負與錯誤','Final Test：10 opponents × 3 maps × 10 games/side = 600 matches/run。W=勝、D=和、L=負、E=錯誤；勝率=勝／總場數。\n'+JSON.stringify(d.final_test)],
    ['對手別正式測試場數','兩批各 seed 8–13；每個對手為 6 runs × 60 matches = 360 matches。\n'+JSON.stringify(d.opponents)],
    ['G20 行為簽章數','指標：G20 semantic unique；population 10；三張地圖 × 三個階段。\n'+JSON.stringify({previous:d.g20.previous.semantic_unique_counts,current:d.g20.current_completed.semantic_unique_counts})],
    ['各 seed 的耗時與勝負','時間：搜尋 wall time 為 G0 開始至 G20 完成；G0 為該代 duration；G1–20 為世代 duration 加總；Final Test 為 600 場對戰的時間跨度，排除 compilation 與 Integration。單位 seconds，表格四捨五入至整秒。\n'+JSON.stringify(d.timing_evidence)],
  ];
  return pages.map(([title,notes],i)=>({page:39+i,title,notes:source+'\n\n'+notes}));
}

export function renderStability(s,p,H,d){
  if(p.page<39||p.page>45)return false;
  const {T,B,L,Cn,C,sub,foot,F,applyChartFont}=H;
  const prev=d.g20.previous.rows,cur=d.g20.current_completed.rows;
  const seeds=[8,9,10,11,12,13],pairedPrev=seeds.map(seed=>prev.find(r=>r.seed===seed));
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
      sub(s,'Framework local＋Opponent Pool｜兩批各 6 個 seed，12 個 run 均完成 G20 與 Final Test');
      const a=B(s,'同一凍結 bundle\nb2daa0d4…0939b',80,235,430,110,{fill:C.gold,size:30,bold:true});
      const b=B(s,'local 有限槽位演化\n搜尋期間無 LLM 呼叫',630,235,430,110,{fill:C.pale,size:30,bold:true});Cn(s,a,b);
      const c=B(s,'人口 10 × 演化 20 代\n180 場搜尋／600 場測試',1180,235,410,110,{fill:C.blush,size:29,bold:true});Cn(s,b,c);
      [['12','已完成 run'],['1800／1800','每個 run 的 G20 對戰'],['0','Final Test 的 errors']].forEach((v,i)=>{
        const x=75+i*520;T(s,v[0],x,414,500,115,{size:i===1?65:86,color:C.ink,bold:true,align:'center'});T(s,v[1],x,530,500,46,{size:27,align:'center'});
      });
      table([['批次','seed 範圍','20 代完成','Final Test 完成'],['上次','8–13','6／6','6 × 600 場'],['本次','8–13','6／6','6 × 600 場']],80,638,1510,174,[380,460,300,370],26);
      foot(s,'數據截點：2026-10-22；兩批各 3600 場 Final Test，合計 7200 場');
      return true;
    }
    case 40:{
      sub(s,'G20 population best Game Performance；兩批均包含 seed 8–13');
      chart('bar',seeds.map(String),series('best'),{left:75,top:225,width:1130,height:525},{barOptions:{direction:'column',grouping:'clustered',gapWidth:30},yAxis:{min:-45,max:35,majorUnit:20,textStyle:{fontSize:21,typeface:F,fill:C.text},majorGridlines:{fill:C.blush,width:0.6}},dataLabels:{showValue:true,position:'outEnd',numberFormatCode:'0.000',textStyle:{fontSize:18,typeface:F,fill:C.ink}}});
      T(s,'跨 seed 的 best 平均',1250,245,340,58,{size:28,color:C.ink,bold:true});
      T(s,`上次 6 seed\n${fmt(d.g20.previous.mean_best)}\n\n本次 6 seed\n${fmt(d.g20.current_completed.mean_best)}`,1250,315,340,280,{size:31,color:C.text});
      const delta=cur.map(r=>{const v=r.best-prev.find(q=>q.seed===r.seed).best;return (v>=0?'+':'')+fmt(v);});
      T(s,'本次 − 上次（seed 8→13）：'+delta.join('、'),80,769,1510,50,{size:25,color:C.ink,bold:true});
      foot(s,'指標：G20 population best；跨 seed 平均的樣本數：每批 6 runs');
      return true;
    }
    case 41:{
      sub(s,'population best｜相同縱軸 −80～40；各點代表該代當下的對手快照');
      L(s,1120,192,1170,192,{color:C.rose,width:4});T(s,'上次',1185,172,120,40,{size:23});L(s,1330,192,1380,192,{color:C.ink,width:4});T(s,'本次',1395,172,150,40,{size:23});
      for(let i=0;i<6;i++){
        const seed=i+8,x=65+(i%3)*535,y=240+Math.floor(i/3)*290;
        T(s,`seed ${seed}`,x+20,y-24,480,42,{size:26,color:C.ink,bold:true});
        const rows=d.trajectories.rows.filter(r=>r.seed===seed);
        chart('line',['G0','G5','G10','G15','G20'],rows.map(r=>({name:r.cohort,values:['g0','g5','g10','g15','g20'].map(k=>r[k]),line:{fill:r.cohort==='上次'?C.rose:C.ink,width:3},marker:{symbol:r.cohort==='上次'?'circle':'diamond',size:5,fill:r.cohort==='上次'?C.rose:C.ink}})),{left:x,top:y+22,width:505,height:237},{hasLegend:false,lineOptions:{smooth:false},dataLabels:{showValue:false},xAxis:{textStyle:{fontSize:18,typeface:F,fill:C.text},tickLabelPosition:'low'},yAxis:{min:-80,max:40,majorUnit:40,textStyle:{fontSize:18,typeface:F,fill:C.text},majorGridlines:{fill:C.blush,width:0.5}}});
      }
      foot(s,'兩批各 6 個 seed；各圖為 G0、G5、G10、G15、G20 的 population best');
      return true;
    }
    case 42:{
      sub(s,'每 run 600 場；兩批各 6 runs。圖示 W／D／L 百分比，表列實際場數');
      const rows=d.final_test.cohorts;
      chart('bar',['上次｜6 runs，3600 場','本次｜6 runs，3600 場'],[
        {name:'勝 W',values:rows.map(r=>Number((100*r.wins/r.matches).toFixed(4))),fill:C.rose},
        {name:'和 D',values:rows.map(r=>Number((100*r.draws/r.matches).toFixed(4))),fill:C.gold,dataLabels:{showValue:false}},
        {name:'敗 L',values:rows.map(r=>Number((100*r.losses/r.matches).toFixed(4))),fill:C.ink},
      ],{left:80,top:225,width:1510,height:416},{barOptions:{direction:'column',grouping:'stacked',overlap:100,gapWidth:170},yAxis:{min:0,max:100,majorUnit:25,numberFormatCode:'0"%"',textStyle:{fontSize:22,typeface:F,fill:C.text},majorGridlines:{fill:C.blush,width:0.6}},dataLabels:{showValue:true,position:'center',numberFormatCode:'0.0"%"',textStyle:{fontSize:24,typeface:F,fill:C.bg}}});
      table([['批次','勝 W','和 D','敗 L','錯誤 E','勝率'],...rows.map((r,i)=>[i===0?'上次（6 runs）':'本次（6 runs）',r.wins,r.draws,r.losses,r.errors,r.aggregate_win_rate_percent.toFixed(2)+'%'])],80,675,1510,150,[410,200,200,200,200,300],26);
      foot(s,'Final Test：10 對手 × 3 地圖 × 每邊 10 場＝600 場／run；勝率＝勝 W／總場數');
      return true;
    }
    case 43:{
      sub(s,'兩批均為 seed 8–13；每個對手 6 runs × 60 場＝360 場');
      for(const [i,key] of ['previous','current'].entries()){
        const x=i===0?80:850;
        T(s,i===0?'上次｜6 runs':'本次｜6 runs',x,197,740,45,{size:30,color:C.ink,bold:true});
        table([['對手','勝 W','和 D','敗 L','錯誤 E'],...d.opponents[key].map(r=>[r.opponent,r.wins,r.draws,r.losses,r.errors])],x,260,740,550,[300,110,110,110,110],24);
      }
      foot(s,'每批：10 個對手 × 360 場＝3600 場；W＝勝、D＝和、L＝負、E＝錯誤');
      return true;
    }
    case 44:{
      sub(s,'G20 semantic unique／人口 10；三張地圖 × 三個階段的動作簽章');
      chart('bar',seeds.map(String),series('semantic_unique'),{left:75,top:240,width:1130,height:540},{barOptions:{direction:'column',grouping:'clustered',gapWidth:110},yAxis:{min:0,max:10,majorUnit:2,textStyle:{fontSize:22,typeface:F,fill:C.text},majorGridlines:{fill:C.blush,width:0.6}},dataLabels:{showValue:true,position:'outEnd',numberFormatCode:'0',textStyle:{fontSize:29,typeface:F,fill:C.ink}}});
      table([['seed','上次','本次'],...seeds.map(seed=>[seed,prev.find(r=>r.seed===seed).semantic_unique,cur.find(r=>r.seed===seed).semantic_unique])],1240,280,350,420,[100,125,125],25);
      foot(s,'指標：G20 semantic unique；兩批各 seed 8–13；每個 run 的 population＝10');
      return true;
    }
    case 45:{
      sub(s,'兩批各 seed 8–13｜時間單位 hh:mm:ss；勝／和／負為各 run 的 600 場 Final Test');
      const time=seconds=>{
        if(seconds===null)return '未取得';
        const n=Math.round(seconds);
        return [Math.floor(n/3600),Math.floor(n/60)%60,n%60].map(v=>String(v).padStart(2,'0')).join(':');
      };
      const rows=d.timing_evidence.rows;
      table([['批次','seed','搜尋 wall','G0','G1–20 合計','測試對戰','勝 W','和 D','敗 L','錯誤 E'],...rows.map(r=>[r.cohort,r.seed,time(r.search_wall_seconds),time(r.initialization_seconds),time(r.evolution_seconds),time(r.final_test_seconds),r.wins,r.draws,r.losses,r.errors])],80,235,1510,572,[120,80,230,180,230,220,120,100,120,110],23);
      foot(s,'搜尋 wall：G0→G20；G1–20：世代耗時加總；測試對戰：600 場時間跨度，排除編譯與 Integration');
      return true;
    }
  }
}
