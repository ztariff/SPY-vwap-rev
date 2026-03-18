#!/usr/bin/env python3
"""
Build dashboard_v2.html with ALL trades + gap analysis embedded.
Single self-contained HTML file.
"""
import json, os, math

BASE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(BASE, "all_promoted_trades.json")) as f:
    trades = json.load(f)

with open(os.path.join(BASE, "gap_analysis_results.json")) as f:
    gap = json.load(f)

with open(os.path.join(BASE, "commission_final_report.json")) as f:
    commission_report = json.load(f)

# Clean NaN values for JSON safety
def clean(obj):
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean(v) for v in obj]
    elif isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj

trades = clean(trades)
gap = clean(gap)
commission_report = clean(commission_report)

trades_json = json.dumps(trades)
gap_json = json.dumps(gap)
commission_json = json.dumps(commission_report)

print(f"Embedding {len(trades)} trades ({len(trades_json)} bytes)")
print(f"Embedding gap analysis ({len(gap_json)} bytes)")
print(f"Embedding commission report ({len(commission_json)} bytes)")

html = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>VWAP Deviation Strategy — Enhanced Calendar Dashboard</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0f1117;color:#DDD;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;overflow-x:hidden}}
.pos{{color:#26a69a}}.neg{{color:#ef5350}}.muted{{color:#666}}

/* Header */
#hdr{{display:flex;align-items:center;justify-content:space-between;padding:10px 20px;background:#181b28;border-bottom:1px solid #2a2e3d;flex-wrap:wrap;gap:8px}}
#hdr h1{{font-size:15px;font-weight:600;color:#e0e0e0;white-space:nowrap}}
#hdr .stats{{display:flex;gap:16px;font-size:12px;flex-wrap:wrap}}
#hdr .sl{{color:#666;margin-right:4px}}
#hdr .sv{{font-weight:700}}
#comm-toggle{{background:#2a2e3d;color:#aaa;border:1px solid #3a3f52;border-radius:4px;padding:5px 12px;font-size:11px;cursor:pointer;font-weight:600}}
#comm-toggle:hover{{background:#363c52;color:#fff}}
#comm-toggle.on{{background:#2962ff;color:#fff;border-color:#2962ff}}

/* Controls */
.controls{{display:flex;align-items:center;gap:12px;padding:12px 20px;flex-wrap:wrap}}
.controls button{{background:#2a2e3d;color:#aaa;border:1px solid #3a3f52;border-radius:4px;padding:5px 12px;font-size:13px;cursor:pointer}}
.controls button:hover{{background:#363c52;color:#fff}}
.month-title{{font-size:15px;font-weight:600;min-width:160px;text-align:center}}
.filter-group{{display:flex;gap:4px;margin-left:auto}}
.fbtn{{background:#2a2e3d;color:#777;border:1px solid #3a3f52;border-radius:4px;padding:4px 10px;font-size:11px;cursor:pointer;font-weight:600}}
.fbtn:hover{{color:#ddd}}.fbtn.on{{background:#2962ff;color:#fff;border-color:#2962ff}}

/* Equity curve */
#eq-wrap{{padding:4px 20px 8px;position:relative}}
#eq-container{{width:100%;height:100px;border-radius:6px;border:1px solid #2a2e3d;background:#0f1117}}
#eq-label{{position:absolute;top:10px;left:30px;font-size:11px;color:#555;pointer-events:none}}

/* Calendar */
#cal-wrap{{padding:4px 20px 12px}}
.cal-grid{{display:grid;grid-template-columns:repeat(7,1fr);gap:2px}}
.cal-hdr{{text-align:center;font-size:10px;color:#555;padding:6px 0;text-transform:uppercase;letter-spacing:1px;font-weight:700}}
.cal-cell{{min-height:88px;background:#161925;border:1px solid #22263a;border-radius:4px;padding:6px 8px;position:relative;cursor:default;transition:all .12s}}
.cal-cell.om{{opacity:.25}}
.cal-cell.has{{cursor:pointer}}
.cal-cell.has:hover{{border-color:#2962ff;background:#1a2040}}
.cal-cell.sel{{border-color:#2962ff;background:#1a2040;box-shadow:0 0 0 1px #2962ff}}
.cal-cell .dn{{font-size:11px;color:#555;margin-bottom:4px;font-weight:500}}
.cal-cell.today .dn{{color:#2962ff;font-weight:700}}
.pill{{font-size:9px;padding:2px 5px;border-radius:3px;margin-bottom:2px;display:flex;justify-content:space-between;align-items:center;gap:3px;line-height:1.3}}
.pill.w{{background:rgba(38,166,154,.12);color:#26a69a;border:1px solid rgba(38,166,154,.25)}}
.pill.l{{background:rgba(239,83,80,.12);color:#ef5350;border:1px solid rgba(239,83,80,.25)}}
.pill .plbl{{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:70px}}
.pill .ppnl{{font-weight:700;white-space:nowrap}}
.pill .comm-dot{{font-size:8px;font-weight:700;line-height:1}}
.day-total{{position:absolute;bottom:4px;right:6px;font-size:10px;font-weight:700}}

/* Trade detail */
#detail{{padding:0 20px 40px}}
.detail-date{{font-size:15px;font-weight:600;color:#e0e0e0;margin:16px 0 12px;padding-top:16px;border-top:1px solid #2a2e3d}}
.tblock{{margin-bottom:20px;border:1px solid #2a2e3d;border-radius:8px;background:#13162a;overflow:hidden}}
.tblock-hdr{{display:flex;align-items:center;gap:12px;padding:10px 14px;background:#181c30;border-bottom:1px solid #2a2e3d;flex-wrap:wrap}}
.tbadge{{padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700;text-transform:uppercase}}
.tbadge.bull{{background:rgba(38,166,154,.18);color:#26a69a}}
.tbadge.bear{{background:rgba(239,83,80,.18);color:#ef5350}}
.tleg{{color:#999;font-size:12px}}
.tatr{{color:#666;font-size:11px}}
.tpnl{{font-size:16px;font-weight:700;margin-left:auto}}
.tmeta{{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:6px;padding:10px 14px}}
.mc{{background:#181c30;border:1px solid #22263a;border-radius:5px;padding:6px 10px}}
.mc .ml{{font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.5px;font-weight:600}}
.mc .mv{{font-size:13px;font-weight:600;margin-top:2px}}
.tcharts{{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:10px 14px}}
.tcbox{{background:#0f1117;border:1px solid #22263a;border-radius:6px;padding:10px;position:relative}}
.tcbox .tclbl{{font-size:11px;color:#666;margin-bottom:6px;font-weight:600}}
.tcbox .tccont{{width:100%;height:280px}}
.tt-ov{{position:absolute;top:32px;left:16px;background:rgba(15,17,23,.9);border:1px solid #2a2e3d;border-radius:5px;padding:5px 8px;font-size:10px;line-height:1.5;pointer-events:none;z-index:100;display:none;min-width:120px}}

/* Gap analysis panel */
#gap-panel{{padding:0 20px 40px}}
.gap-toggle{{background:#2a2e3d;color:#aaa;border:1px solid #3a3f52;border-radius:4px;padding:8px 16px;font-size:13px;cursor:pointer;width:100%;text-align:left;font-weight:600;margin-bottom:8px}}
.gap-toggle:hover{{background:#363c52;color:#fff}}
.gap-content{{display:none;border:1px solid #2a2e3d;border-radius:8px;background:#13162a;padding:16px;margin-bottom:20px}}
.gap-content.show{{display:block}}
.gap-section{{margin-bottom:16px}}
.gap-section h3{{font-size:13px;font-weight:700;color:#e0e0e0;margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid #22263a}}
.gap-tbl{{width:100%;border-collapse:collapse;font-size:11px}}
.gap-tbl th{{text-align:left;padding:5px 8px;color:#666;font-size:10px;text-transform:uppercase;border-bottom:1px solid #22263a;font-weight:600}}
.gap-tbl td{{padding:5px 8px;border-bottom:1px solid rgba(34,38,58,.5)}}
.gap-tbl td.num{{text-align:right;font-family:monospace;font-weight:600}}
.gap-stat{{display:inline-block;background:#181c30;border:1px solid #22263a;border-radius:6px;padding:8px 14px;margin:3px;text-align:center}}
.gap-stat .gs-val{{font-size:16px;font-weight:700}}
.gap-stat .gs-lbl{{font-size:9px;color:#555;text-transform:uppercase;margin-top:2px}}
</style>
</head>
<body>

<div id="hdr">
  <h1>VWAP Deviation — Credit Spreads Calendar</h1>
  <div class="stats">
    <span><span class="sl">Trades</span><span class="sv" id="s-n">-</span></span>
    <span><span class="sl">Win Rate</span><span class="sv" id="s-wr">-</span></span>
    <span><span class="sl">Avg P&L</span><span class="sv" id="s-avg">-</span></span>
    <span><span class="sl">Total $P&L</span><span class="sv" id="s-tot">-</span></span>
    <span><span class="sl">PF</span><span class="sv" id="s-pf">-</span></span>
    <span><span class="sl">MaxDD</span><span class="sv" id="s-dd">-</span></span>
    <span><span class="sl">Commission</span><span class="sv" id="s-comm">-</span></span>
  </div>
  <button id="comm-toggle">Show Commission-Adjusted</button>
</div>

<div class="controls">
  <button id="prev-m">&laquo;</button>
  <div class="month-title" id="m-title">-</div>
  <button id="next-m">&raquo;</button>
  <div class="filter-group">
    <button class="fbtn on" data-f="all">All</button>
    <button class="fbtn" data-f="bull_put">Bull Puts</button>
    <button class="fbtn" data-f="bear_call">Bear Calls</button>
    <button class="fbtn" data-f="0.5x">0.5x ATR</button>
    <button class="fbtn" data-f="0.6x">0.6x ATR</button>
    <button class="fbtn" data-f="0.7x">0.7x ATR</button>
    <button class="fbtn" data-f="win">Winners</button>
    <button class="fbtn" data-f="loss">Losers</button>
    <button class="fbtn" data-f="survives">Commission Survivors</button>
    <button class="fbtn" data-f="dead">Commission Dead</button>
  </div>
</div>

<div id="eq-wrap">
  <div id="eq-container"></div>
  <div id="eq-label">Monthly Cumulative P&L</div>
</div>

<div id="cal-wrap"><div class="cal-grid" id="cal-grid"></div></div>
<div id="detail"></div>
<div id="gap-panel"></div>

<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
<script>
// ═══════════════════════════════════════════════════════════════════
//  DATA (all {len(trades)} trades from real Polygon market prices)
// ═══════════════════════════════════════════════════════════════════
const TRADES={trades_json};
const GAP={gap_json};
const COMMISSION_REPORT={commission_json};
const PK='cBE5Kbq9yllt0Yj29mDQjBcIKfAYQlHF';
const RPT=100000;
const COMM_PER_LEG=0.73; // IBKR tiered total per contract per leg

// ═══════════════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════════════
let curMonth=new Date();
let filter='all';
let selDate=null;
let commAdj=false;
let eqChart=null,eqSeries=null;
let detailCharts=[];
const fcache={{}};

// ═══════════════════════════════════════════════════════════════════
//  SIZING & P&L
// ═══════════════════════════════════════════════════════════════════
function sizeTrade(t){{
  const cr=t.credit_received||0, sw=t.spread_width||1;
  const mrp=(sw-cr)*100;
  if(mrp<=0)return Object.assign(t,{{_c:0,_dp:0,_comm:0,_adp:0,_mr:0}});
  const c=Math.floor(RPT/mrp);
  const dp=t.pnl_dollar*100*c;
  const cm=COMM_PER_LEG*4*c;
  return Object.assign(t,{{_c:c,_dp:dp,_comm:cm,_adp:dp-cm,_mr:mrp*c,_tc:cr*100*c}});
}}
TRADES.forEach(sizeTrade);

function pnl(t){{return commAdj?t._adp:t._dp}}
function fmtD(v){{const a=Math.abs(v);const s=a>=1000?(a/1000).toFixed(1)+'k':a.toFixed(0);return(v>=0?'+$':'-$')+s}}
function fmtP(v){{return(v>=0?'+':'')+v.toFixed(1)+'%'}}
function fmtT12(t){{if(!t)return'-';const p=t.split(':');let h=+p[0],m=p[1];const ap=h>=12?'PM':'AM';if(h>12)h-=12;if(h===0)h=12;return h+':'+m+' '+ap}}

// ═══════════════════════════════════════════════════════════════════
//  FILTERING
// ═══════════════════════════════════════════════════════════════════
function getFiltered(){{
  return TRADES.filter(t=>{{
    if(filter==='win')return pnl(t)>0;
    if(filter==='loss')return pnl(t)<=0;
    if(filter==='bull_put')return t.product&&t.product.includes('bull_put');
    if(filter==='bear_call')return t.product&&t.product.includes('bear_call');
    if(filter==='0.5x')return t.atr_mult===0.5;
    if(filter==='0.6x')return t.atr_mult===0.6;
    if(filter==='0.7x')return t.atr_mult===0.7;
    if(filter==='survives')return t.commission_status==='SURVIVES';
    if(filter==='dead')return t.commission_status==='DEAD';
    return true;
  }});
}}

// ═══════════════════════════════════════════════════════════════════
//  HEADER STATS
// ═══════════════════════════════════════════════════════════════════
function updateStats(){{
  const ft=getFiltered();
  const n=ft.length;
  if(!n){{['s-n','s-wr','s-avg','s-tot','s-pf','s-dd','s-comm'].forEach(id=>document.getElementById(id).textContent='-');return}}
  const pnls=ft.map(t=>pnl(t));
  const wins=commAdj?ft.filter(t=>t.pnl_adj_pct>0):pnls.filter(p=>p>0);
  const losses=commAdj?ft.filter(t=>t.pnl_adj_pct<=0):pnls.filter(p=>p<0);
  const tot=pnls.reduce((a,b)=>a+b,0);
  const adjTot=ft.reduce((s,t)=>s+(t.pnl_adj_dollar||0),0);
  const displayTot=commAdj?adjTot:tot;
  const avgP=displayTot/n;
  const gw=wins.reduce((s,t)=>s+pnl(t),0);
  const gl=Math.abs(losses.reduce((s,t)=>s+pnl(t),0));
  const pf=gl>0?gw/gl:wins.length>0?99:0;
  // Max drawdown
  let cum=0,peak=0,maxdd=0;
  pnls.forEach(p=>{{cum+=p;if(cum>peak)peak=cum;const dd=peak-cum;if(dd>maxdd)maxdd=dd}});
  const tComm=ft.reduce((s,t)=>s+(t.commission_dollar||0),0);

  document.getElementById('s-n').textContent=n;
  const wrEl=document.getElementById('s-wr');wrEl.textContent=(wins.length/n*100).toFixed(1)+'%';wrEl.className='sv '+(wins.length/n>0.6?'pos':'neg');
  const avgEl=document.getElementById('s-avg');avgEl.textContent=fmtD(avgP);avgEl.className='sv '+(avgP>=0?'pos':'neg');
  const totEl=document.getElementById('s-tot');totEl.textContent=fmtD(displayTot);totEl.className='sv '+(displayTot>=0?'pos':'neg');
  document.getElementById('s-pf').textContent=pf>20?'20+':pf.toFixed(2);
  const ddEl=document.getElementById('s-dd');ddEl.textContent='-'+fmtD(maxdd).replace('+$','$');ddEl.className='sv neg';
  const commEl=document.getElementById('s-comm');commEl.textContent='-$'+(tComm>=1000?(tComm/1000).toFixed(1)+'k':tComm.toFixed(0));commEl.className='sv neg';
}}

// ═══════════════════════════════════════════════════════════════════
//  EQUITY CURVE
// ═══════════════════════════════════════════════════════════════════
function renderEquity(){{
  const c=document.getElementById('eq-container');
  if(eqChart){{eqChart.remove();eqChart=null;eqSeries=null}}
  const yr=curMonth.getFullYear(),mo=curMonth.getMonth();
  const ft=getFiltered().filter(t=>{{const d=new Date(t.date+'T12:00:00');return d.getFullYear()===yr&&d.getMonth()===mo}});
  if(!ft.length){{c.innerHTML='<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#444;font-size:12px">No trades this month</div>';return}}
  c.innerHTML='';
  eqChart=LightweightCharts.createChart(c,{{
    width:c.clientWidth,height:100,
    layout:{{background:{{color:'#0f1117'}},textColor:'#777',fontSize:10}},
    grid:{{vertLines:{{visible:false}},horzLines:{{color:'rgba(255,255,255,0.03)'}}}},
    rightPriceScale:{{borderVisible:false,drawTicks:false}},
    timeScale:{{borderVisible:false,timeVisible:false,fixLeftEdge:true,fixRightEdge:true}},
    crosshair:{{mode:LightweightCharts.CrosshairMode.Normal}},
    handleScroll:false,handleScale:false
  }});
  // Aggregate by date
  const byD={{}};
  ft.forEach(t=>{{if(!byD[t.date])byD[t.date]=0;byD[t.date]+=pnl(t)}});
  let cum=0;
  const data=Object.keys(byD).sort().map(d=>{{cum+=byD[d];return{{time:d,value:Math.round(cum)}}}});
  eqSeries=eqChart.addAreaSeries({{
    topColor:cum>=0?'rgba(38,166,154,0.35)':'rgba(239,83,80,0.35)',
    bottomColor:cum>=0?'rgba(38,166,154,0.02)':'rgba(239,83,80,0.02)',
    lineColor:cum>=0?'#26a69a':'#ef5350',lineWidth:2,
    lastValueVisible:true,priceLineVisible:false
  }});
  eqSeries.setData(data);
  eqChart.timeScale().fitContent();
  new ResizeObserver(()=>{{if(eqChart)eqChart.applyOptions({{width:c.clientWidth}})}}).observe(c);
}}

// ═══════════════════════════════════════════════════════════════════
//  CALENDAR
// ═══════════════════════════════════════════════════════════════════
function renderCal(){{
  const g=document.getElementById('cal-grid');
  const yr=curMonth.getFullYear(),mo=curMonth.getMonth();
  document.getElementById('m-title').textContent=new Date(yr,mo).toLocaleString('en-US',{{month:'long',year:'numeric'}});
  const first=new Date(yr,mo,1),last=new Date(yr,mo+1,0);
  const pad=first.getDay(),dim=last.getDate();
  const ft=getFiltered();
  const byD={{}};ft.forEach(t=>{{if(!byD[t.date])byD[t.date]=[];byD[t.date].push(t)}});
  const today=new Date().toISOString().slice(0,10);

  let html=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(d=>`<div class="cal-hdr">${{d}}</div>`).join('');
  const prev=new Date(yr,mo,0);
  for(let i=pad-1;i>=0;i--)html+=`<div class="cal-cell om"><div class="dn">${{prev.getDate()-i}}</div></div>`;

  for(let d=1;d<=dim;d++){{
    const ds=`${{yr}}-${{String(mo+1).padStart(2,'0')}}-${{String(d).padStart(2,'0')}}`;
    const dt=byD[ds]||[];
    const has=dt.length>0;
    const dayP=dt.reduce((s,t)=>s+pnl(t),0);
    let cls='cal-cell';
    if(ds===today)cls+=' today';
    if(has)cls+=' has';
    if(ds===selDate)cls+=' sel';
    let inner=`<div class="dn">${{d}}</div>`;
    dt.forEach(t=>{{
      const w=pnl(t)>0;
      const isBull=t.product&&t.product.includes('bull_put');
      const lbl=`${{isBull?'BP':'BC'}} ${{t.short_delta}}/${{t.long_delta}} ${{t.atr_mult}}x`;
      const commDot=t.commission_status==='SURVIVES'?'<span class="comm-dot" style="color:#26a69a">●</span>':'<span class="comm-dot" style="color:#ef5350">●</span>';
      inner+=`<div class="pill ${{w?'w':'l'}}"><span class="plbl">${{lbl}}</span><span class="ppnl">${{fmtD(pnl(t))}}</span>${{commDot}}</div>`;
    }});
    if(has){{
      inner+=`<div class="day-total ${{dayP>=0?'pos':'neg'}}">${{fmtD(dayP)}}</div>`;
    }}
    const oc=has?`onclick="selectDay('${{ds}}')"`:''
    html+=`<div class="${{cls}}" ${{oc}}>${{inner}}</div>`;
  }}
  const rem=(7-((pad+dim)%7))%7;
  for(let i=1;i<=rem;i++)html+=`<div class="cal-cell om"><div class="dn">${{i}}</div></div>`;
  g.innerHTML=html;
}}

// ═══════════════════════════════════════════════════════════════════
//  SELECT DAY -> TRADE DETAIL
// ═══════════════════════════════════════════════════════════════════
function selectDay(ds){{
  detailCharts.forEach(c=>c.remove());detailCharts=[];
  selDate=ds;
  renderCal();
  const sec=document.getElementById('detail');
  const dt=getFiltered().filter(t=>t.date===ds);
  if(!dt.length){{sec.innerHTML='';return}}
  const dl=new Date(ds+'T12:00:00').toLocaleDateString('en-US',{{weekday:'long',year:'numeric',month:'long',day:'numeric'}});
  const dayP=dt.reduce((s,t)=>s+pnl(t),0);
  let html=`<div class="detail-date">${{dl}} — ${{dt.length}} Trade${{dt.length>1?'s':''}} — <span class="${{dayP>=0?'pos':'neg'}}">${{fmtD(dayP)}}</span></div>`;

  dt.forEach((t,idx)=>{{
    const w=pnl(t)>0;
    const pc=w?'#26a69a':'#ef5350';
    const dirLbl=t.direction==='below'?'BULL PUT SPREAD':'BEAR CALL SPREAD';
    const dirCls=t.direction==='below'?'bull':'bear';
    const legLbl=`Short ${{t.short_delta}}d / Long ${{t.long_delta}}d ${{t.direction==='below'?'Put':'Call'}} @ $${{t.short_strike?.toFixed(0)||'-'}}/$${{t.long_strike?.toFixed(0)||'-'}}`;
    const exitR=(t.exit_reason||'-').replace(/_/g,' ').toUpperCase();
    const exitC=t.exit_reason==='target'?'pos':t.exit_reason==='stop_loss'?'neg':'muted';
    const comm=t._comm||0;
    const adjP=t._adp||0;

    html+=`<div class="tblock">
    <div class="tblock-hdr">
      <span class="tbadge ${{dirCls}}">${{dirLbl}}</span>
      <span class="tleg">${{legLbl}}</span>
      <span class="tatr">ATR ${{t.atr_mult}}x</span>
      <span class="tpnl" style="color:${{pc}}">${{fmtP(t.pnl_pct)}} ${{fmtD(pnl(t))}}</span>
    </div>
    <div class="tmeta">
      <div class="mc"><div class="ml">Contracts</div><div class="mv">${{t._c}}</div></div>
      <div class="mc"><div class="ml">SPY at Entry</div><div class="mv">$${{t.spy_entry_price?.toFixed(2)||'-'}}</div></div>
      <div class="mc"><div class="ml">Credit / Contract</div><div class="mv pos">$${{t.credit_received?.toFixed(2)||'-'}}</div></div>
      <div class="mc"><div class="ml">Total Credit</div><div class="mv pos">${{fmtD(t._tc||0)}}</div></div>
      <div class="mc"><div class="ml">Spread Width</div><div class="mv">$${{t.spread_width?.toFixed(0)||'-'}}</div></div>
      <div class="mc"><div class="ml">Total Risk</div><div class="mv neg">${{fmtD(t._mr||0)}}</div></div>
      <div class="mc"><div class="ml">Short Entry</div><div class="mv">$${{t.short_entry_price?.toFixed(2)||'-'}}</div></div>
      <div class="mc"><div class="ml">Long Entry</div><div class="mv">$${{t.long_entry_price?.toFixed(2)||'-'}}</div></div>
      <div class="mc"><div class="ml">Exit Spread</div><div class="mv">$${{t.exit_spread_value?.toFixed(2)||'-'}}</div></div>
      <div class="mc"><div class="ml">Entry</div><div class="mv">${{fmtT12(t.entry_time)}}</div></div>
      <div class="mc"><div class="ml">Exit</div><div class="mv">${{fmtT12(t.exit_time)}}</div></div>
      <div class="mc"><div class="ml">Exit Reason</div><div class="mv ${{exitC}}">${{exitR}}</div></div>
      <div class="mc"><div class="ml">Held</div><div class="mv">${{t.minutes_held!=null?Math.round(t.minutes_held)+'m':'-'}}</div></div>
      <div class="mc"><div class="ml">Target / Stop</div><div class="mv">${{t.target_pct!=null?(t.target_pct*100).toFixed(0):'?'}}% / ${{t.stop_pct!=null?t.stop_pct.toFixed(1):'?'}}x</div></div>
      <div class="mc"><div class="ml">Commission</div><div class="mv neg">-$${{comm.toFixed(0)}}</div></div>
      <div class="mc"><div class="ml">Adj P&L</div><div class="mv ${{adjP>=0?'pos':'neg'}}">${{fmtD(adjP)}}</div></div>
    </div>
    <div class="tcharts">
      <div class="tcbox">
        <div class="tclbl">SPY 1-Min with VWAP</div>
        <div class="tccont" id="spy-${{idx}}"></div>
        <div class="tt-ov" id="spy-tt-${{idx}}"></div>
      </div>
      <div class="tcbox">
        <div class="tclbl">Spread Value & Exit Levels</div>
        <div class="tccont" id="opt-${{idx}}"></div>
        <div class="tt-ov" id="opt-tt-${{idx}}"></div>
      </div>
    </div>
    </div>`;
  }});

  sec.innerHTML=html;
  sec.scrollIntoView({{behavior:'smooth',block:'start'}});
  dt.forEach((t,idx)=>loadCharts(t,idx));
}}

// ═══════════════════════════════════════════════════════════════════
//  POLYGON DATA FETCHING
// ═══════════════════════════════════════════════════════════════════
async function fetchBars(ticker,dateStr){{
  const ck=`${{ticker}}_${{dateStr}}`;
  if(fcache[ck])return fcache[ck];
  try{{
    const url=`https://api.polygon.io/v2/aggs/ticker/${{ticker}}/range/1/minute/${{dateStr}}/${{dateStr}}?adjusted=true&sort=asc&limit=10000&apiKey=${{PK}}`;
    const r=await fetch(url);const j=await r.json();
    if(!j.results){{fcache[ck]=[];return[]}}
    const bars=j.results.map(r=>({{t:r.t,o:r.o,h:r.h,l:r.l,c:r.c,v:r.v||0}}));
    fcache[ck]=bars;return bars;
  }}catch(e){{console.error('Fetch error:',ticker,e);fcache[ck]=[];return[]}}
}}

function tsToSec(ms){{return Math.floor(ms/1000)}}
function isoToSec(iso){{if(!iso)return null;return Math.floor(new Date(iso).getTime()/1000)}}
function tsNY(sec){{return new Date(sec*1000).toLocaleString('en-US',{{timeZone:'America/New_York',hour:'numeric',minute:'2-digit',hour12:true}})}}
function findNearest(data,ts){{if(!data.length)return null;let b=data[0].time,bd=Math.abs(b-ts);for(const d of data){{const diff=Math.abs(d.time-ts);if(diff<bd){{bd=diff;b=d.time}}}}return b}}

// ═══════════════════════════════════════════════════════════════════
//  CHART FACTORY
// ═══════════════════════════════════════════════════════════════════
function makeChart(container,h){{
  return LightweightCharts.createChart(container,{{
    width:container.clientWidth,height:h||280,
    layout:{{background:{{color:'#0f1117'}},textColor:'#999',fontSize:10}},
    grid:{{vertLines:{{color:'rgba(255,255,255,0.03)'}},horzLines:{{color:'rgba(255,255,255,0.03)'}}}},
    timeScale:{{borderColor:'#2a2e3d',timeVisible:true,secondsVisible:false,tickMarkFormatter:tsNY}},
    rightPriceScale:{{borderColor:'#2a2e3d'}},
    crosshair:{{mode:LightweightCharts.CrosshairMode.Normal}},
    localization:{{timeFormatter:tsNY}}
  }});
}}

function setupTT(chart,series,ttId){{
  const tt=document.getElementById(ttId);
  if(!tt)return;
  chart.subscribeCrosshairMove(p=>{{
    if(!p.time||!p.seriesData||!p.seriesData.get(series)){{tt.style.display='none';return}}
    const d=p.seriesData.get(series);
    tt.style.display='block';
    const time=tsNY(p.time);
    if(d.open!==undefined){{
      tt.innerHTML=`<div style="color:#666;font-size:9px">${{time}}</div><div>O <span class="${{d.close>=d.open?'pos':'neg'}}">${{d.open.toFixed(2)}}</span></div><div>H <span class="pos">${{d.high.toFixed(2)}}</span></div><div>L <span class="neg">${{d.low.toFixed(2)}}</span></div><div>C <span class="${{d.close>=d.open?'pos':'neg'}}">${{d.close.toFixed(2)}}</span></div>`;
    }}else if(d.value!==undefined){{
      tt.innerHTML=`<div style="color:#666;font-size:9px">${{time}}</div><div>${{d.value.toFixed(2)}}</div>`;
    }}
  }});
}}

// ═══════════════════════════════════════════════════════════════════
//  LOAD TRADE CHARTS
// ═══════════════════════════════════════════════════════════════════
async function loadCharts(trade,idx){{
  // ─── SPY Chart ───
  const spyC=document.getElementById(`spy-${{idx}}`);
  if(spyC){{
    const bars=await fetchBars('SPY',trade.date);
    if(bars.length){{
      const chart=makeChart(spyC);
      detailCharts.push(chart);
      const candles=chart.addCandlestickSeries({{upColor:'#26a69a',downColor:'#ef5350',borderUpColor:'#26a69a',borderDownColor:'#ef5350',wickUpColor:'#26a69a',wickDownColor:'#ef5350'}});
      const cdata=bars.map(b=>({{time:tsToSec(b.t),open:b.o,high:b.h,low:b.l,close:b.c}}));
      candles.setData(cdata);

      // Volume
      const vol=chart.addHistogramSeries({{priceFormat:{{type:'volume'}},priceScaleId:'vol'}});
      chart.priceScale('vol').applyOptions({{scaleMargins:{{top:0.85,bottom:0}}}});
      vol.setData(bars.map(b=>({{time:tsToSec(b.t),value:b.v,color:b.c>=b.o?'rgba(38,166,154,0.25)':'rgba(239,83,80,0.25)'}})));

      // VWAP
      let cumTPV=0,cumV=0;
      const vwap=bars.map(b=>{{const tp=(b.h+b.l+b.c)/3;cumTPV+=tp*b.v;cumV+=b.v;return{{time:tsToSec(b.t),value:cumV>0?cumTPV/cumV:b.c}}}});
      const vwapS=chart.addLineSeries({{color:'#ff9800',lineWidth:2,lastValueVisible:false,priceLineVisible:false}});
      vwapS.setData(vwap);

      // Entry/exit markers
      const markers=[];
      const ets=isoToSec(trade.entry_time_iso);
      const xts=isoToSec(trade.exit_time_iso);
      if(ets){{const ct=findNearest(cdata,ets);if(ct)markers.push({{time:ct,position:'aboveBar',color:'#2962ff',shape:'circle',text:`SIGNAL $${{trade.spy_entry_price.toFixed(2)}}`}})}}
      if(xts){{const ct=findNearest(cdata,xts);if(ct)markers.push({{time:ct,position:'belowBar',color:pnl(trade)>=0?'#26a69a':'#ef5350',shape:'circle',text:`EXIT (${{(trade.exit_reason||'').replace(/_/g,' ')}})`}})}}
      if(markers.length){{markers.sort((a,b)=>a.time-b.time);candles.setMarkers(markers)}}

      setupTT(chart,candles,`spy-tt-${{idx}}`);
      chart.timeScale().fitContent();
      new ResizeObserver(()=>chart.applyOptions({{width:spyC.clientWidth}})).observe(spyC);
    }}else{{spyC.innerHTML='<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#444;font-size:12px">No SPY data</div>'}}
  }}

  // ─── Spread Value Chart ───
  const optC=document.getElementById(`opt-${{idx}}`);
  if(optC&&trade.short_ticker&&trade.long_ticker){{
    const [sb,lb]=await Promise.all([fetchBars(trade.short_ticker,trade.date),fetchBars(trade.long_ticker,trade.date)]);
    if(sb.length&&lb.length){{
      const chart=makeChart(optC);
      detailCharts.push(chart);

      // Build spread value line
      const lmap=new Map();lb.forEach(b=>lmap.set(tsToSec(b.t),b));
      const spLine=[];
      sb.forEach(b=>{{const ts=tsToSec(b.t);const lv=lmap.get(ts);if(lv)spLine.push({{time:ts,value:Math.max(b.c-lv.c,0)}})}});

      if(spLine.length){{
        const cr=trade.credit_received||0;
        // Spread area
        const spS=chart.addAreaSeries({{topColor:'rgba(239,83,80,0.25)',bottomColor:'rgba(38,166,154,0.12)',lineColor:'#b0bec5',lineWidth:2,crosshairMarkerVisible:true,priceFormat:{{type:'price',precision:2,minMove:0.01}}}});
        spS.setData(spLine);

        // Credit received line (blue dashed)
        if(cr>0){{const crS=chart.addLineSeries({{color:'#2962ff',lineWidth:1.5,lineStyle:2,lastValueVisible:false,priceLineVisible:false}});crS.setData(spLine.map(b=>({{time:b.time,value:cr}})))}}

        // Target line (green dotted)
        if(trade.target_pct&&cr>0){{const tv=cr*(1-trade.target_pct);const tS=chart.addLineSeries({{color:'rgba(38,166,154,0.6)',lineWidth:1,lineStyle:3,lastValueVisible:false,priceLineVisible:false}});tS.setData(spLine.map(b=>({{time:b.time,value:Math.max(tv,0)}})))}}

        // Stop line (red dotted)
        if(trade.stop_pct&&cr>0){{const sv=cr*(1+trade.stop_pct);const sS=chart.addLineSeries({{color:'rgba(239,83,80,0.6)',lineWidth:1,lineStyle:3,lastValueVisible:false,priceLineVisible:false}});sS.setData(spLine.map(b=>({{time:b.time,value:sv}})))}}

        // Entry/exit markers
        const markers=[];
        const ets=isoToSec(trade.entry_time_iso);
        const xts=isoToSec(trade.exit_time_iso);
        if(ets){{const ct=findNearest(spLine,ets);if(ct)markers.push({{time:ct,position:'aboveBar',color:'#2962ff',shape:'circle',text:`OPEN $${{cr.toFixed(2)}} credit`}})}}
        if(xts){{const ct=findNearest(spLine,xts);const ev=trade.exit_spread_value!=null?`$${{trade.exit_spread_value.toFixed(2)}}`:'';if(ct)markers.push({{time:ct,position:'belowBar',color:pnl(trade)>=0?'#26a69a':'#ef5350',shape:'circle',text:`CLOSE ${{ev}} (${{(trade.exit_reason||'').replace(/_/g,' ')}})`}})}}
        if(markers.length){{markers.sort((a,b)=>a.time-b.time);spS.setMarkers(markers)}}

        setupTT(chart,spS,`opt-tt-${{idx}}`);
        chart.timeScale().fitContent();
        new ResizeObserver(()=>chart.applyOptions({{width:optC.clientWidth}})).observe(optC);
      }}else{{optC.innerHTML='<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#444;font-size:12px">No aligned spread data</div>'}}
    }}else{{optC.innerHTML='<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#444;font-size:12px">No option leg data</div>'}}
  }}else if(optC){{optC.innerHTML='<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#444;font-size:12px">No option tickers</div>'}}
}}

// ═══════════════════════════════════════════════════════════════════
//  GAP ANALYSIS PANEL
// ═══════════════════════════════════════════════════════════════════
function renderGapPanel(){{
  const sec=document.getElementById('gap-panel');
  const ca=GAP.commission_analysis||{{}};
  const ov=GAP.overlap_analysis||{{}};
  const dd=GAP.drawdown_analysis?.overall||{{}};
  const yr=GAP.yearly_analysis||{{}};
  const cr=COMMISSION_REPORT||{{}};

  // Commission table
  let commRows='';
  for(const [k,v] of Object.entries(ca)){{
    commRows+=`<tr>
      <td>${{v.label}}</td>
      <td class="num">$${{(v.total_raw_pnl||0).toLocaleString()}}</td>
      <td class="num neg">-$${{(v.total_commission||0).toLocaleString()}}</td>
      <td class="num ${{(v.total_adj_pnl||0)>=0?'pos':'neg'}}">$${{(v.total_adj_pnl||0).toLocaleString()}}</td>
      <td class="num">${{v.comm_pct_of_raw_pnl||0}}%</td>
      <td class="num">${{v.raw_sharpe||0}}</td>
      <td class="num">${{v.adj_sharpe||0}}</td>
    </tr>`;
  }}

  // Direction analysis from commission report
  let dirRows='';
  if(cr.direction_analysis){{
    for(const [dir,d] of Object.entries(cr.direction_analysis)){{
      dirRows+=`<tr>
        <td>${{dir}}</td>
        <td class="num">${{d.n_trades||0}}</td>
        <td class="num">${{(d.adj_win_rate||0).toFixed(1)}}%</td>
        <td class="num ${{(d.adj_total_dollar||0)>=0?'pos':'neg'}}">$${{(d.adj_total_dollar||0).toLocaleString()}}</td>
        <td class="num ${{(d.adj_sharpe||0)>=0?'pos':'neg'}}">${{(d.adj_sharpe||0).toFixed(3)}}</td>
        <td><span style="padding:2px 8px;border-radius:3px;font-size:10px;font-weight:600;${{d.status==='SURVIVES'?'background:rgba(38,166,154,.2);color:#26a69a':'background:rgba(239,83,80,.2);color:#ef5350'}}">${{d.status}}</span></td>
      </tr>`;
    }}
  }}

  // Yearly table
  let yrRows='';
  for(const [year,strats] of Object.entries(yr).sort()){{
    for(const [sk,d] of Object.entries(strats).sort()){{
      const sLbl=sk.replace('put_credit_','PC ').replace(/_/g,' ');
      yrRows+=`<tr>
        <td>${{year}}</td>
        <td>${{sLbl}}</td>
        <td class="num">${{d.n}}</td>
        <td class="num ${{d.sharpe>=0?'pos':'neg'}}">${{d.sharpe.toFixed(3)}}</td>
        <td class="num">${{d.win_rate}}%</td>
        <td class="num ${{d.avg_pnl>=0?'pos':'neg'}}">${{d.avg_pnl>=0?'+':''}}${{d.avg_pnl.toFixed(3)}}%</td>
      </tr>`;
    }}
  }}

  sec.innerHTML=`
  <button class="gap-toggle" onclick="this.nextElementSibling.classList.toggle('show')">▾ Commission & Gap Analysis</button>
  <div class="gap-content">
    <div class="gap-section">
      <h3>Commission Analysis — Real Impact</h3>
      <table class="gap-tbl">
        <tr><th>Direction</th><th>Trades</th><th>Adj Win %</th><th>Adj Total $</th><th>Adj Sharpe</th><th>Status</th></tr>
        ${{dirRows}}
      </table>
      <p style="font-size:11px;color:#666;margin-top:8px;line-height:1.5">
        <strong>Methodology:</strong> IBKR tiered model ($0.73/leg = $2.92 RT per contract). $100k risk budget.
        <br><strong>Verdict:</strong> ${{cr.final_verdict?.honest_assessment||'Analysis pending...'}}
      </p>
    </div>
    <div class="gap-section">
      <h3>Commission Impact ($100k Risk Budget)</h3>
      <table class="gap-tbl">
        <tr><th>Broker Model</th><th>Raw P&L</th><th>Commission</th><th>Adj P&L</th><th>Comm %</th><th>Raw Sharpe</th><th>Adj Sharpe</th></tr>
        ${{commRows}}
      </table>
    </div>
    <div class="gap-section">
      <h3>Signal Overlap</h3>
      <div>
        <div class="gap-stat"><div class="gs-val">${{ov.total_trade_days||0}}</div><div class="gs-lbl">Trade Days</div></div>
        <div class="gap-stat"><div class="gs-val neg">${{ov.multi_fire_days||0}}</div><div class="gs-lbl">Multi-Signal Days</div></div>
        <div class="gap-stat"><div class="gs-val neg">${{ov.multi_fire_pct||0}}%</div><div class="gs-lbl">Overlap Rate</div></div>
        <div class="gap-stat"><div class="gs-val">${{ov.max_same_day_trades||0}}</div><div class="gs-lbl">Max Same-Day</div></div>
      </div>
      <p style="font-size:11px;color:#666;margin-top:8px">⚠ 55% of trade days fire multiple strategies on the same SPY dip — portfolio drawdowns are correlated.</p>
    </div>
    <div class="gap-section">
      <h3>Drawdown & Streaks</h3>
      <div>
        <div class="gap-stat"><div class="gs-val neg">-$${{(dd.max_drawdown||0).toLocaleString()}}</div><div class="gs-lbl">Max Drawdown</div></div>
        <div class="gap-stat"><div class="gs-val neg">${{dd.max_dd_pct_of_risk||0}}%</div><div class="gs-lbl">DD % of Risk</div></div>
        <div class="gap-stat"><div class="gs-val neg">${{dd.max_consecutive_losses||0}}</div><div class="gs-lbl">Max Consec Losses</div></div>
        <div class="gap-stat"><div class="gs-val pos">${{dd.max_consecutive_wins||0}}</div><div class="gs-lbl">Max Consec Wins</div></div>
      </div>
      <p style="font-size:11px;color:#666;margin-top:8px">Worst drawdown period: ${{dd.worst_dd_period||'N/A'}}</p>
    </div>
    <div class="gap-section">
      <h3>Year-by-Year Sharpe</h3>
      <table class="gap-tbl">
        <tr><th>Year</th><th>Strategy</th><th>N</th><th>Sharpe</th><th>Win Rate</th><th>Avg P&L</th></tr>
        ${{yrRows}}
      </table>
    </div>
  </div>`;
}}

// ═══════════════════════════════════════════════════════════════════
//  NAV & FILTERS
// ═══════════════════════════════════════════════════════════════════
document.getElementById('prev-m').onclick=()=>{{curMonth=new Date(curMonth.getFullYear(),curMonth.getMonth()-1,1);selDate=null;document.getElementById('detail').innerHTML='';detailCharts.forEach(c=>c.remove());detailCharts=[];refresh()}};
document.getElementById('next-m').onclick=()=>{{curMonth=new Date(curMonth.getFullYear(),curMonth.getMonth()+1,1);selDate=null;document.getElementById('detail').innerHTML='';detailCharts.forEach(c=>c.remove());detailCharts=[];refresh()}};
document.querySelectorAll('.fbtn').forEach(b=>b.onclick=()=>{{
  document.querySelectorAll('.fbtn').forEach(x=>x.classList.remove('on'));
  b.classList.add('on');
  filter=b.dataset.f;
  selDate=null;document.getElementById('detail').innerHTML='';
  detailCharts.forEach(c=>c.remove());detailCharts=[];
  refresh();
}});
document.getElementById('comm-toggle').onclick=function(){{
  commAdj=!commAdj;
  this.textContent=commAdj?'Showing Commission-Adjusted':'Show Commission-Adjusted';
  this.classList.toggle('on',commAdj);
  refresh();
}};

function refresh(){{updateStats();renderEquity();renderCal()}}

// ═══════════════════════════════════════════════════════════════════
//  INIT — Navigate to first trade month
// ═══════════════════════════════════════════════════════════════════
(function init(){{
  // Start at the month with the most recent trades
  if(TRADES.length){{
    const lastDate=TRADES[TRADES.length-1].date;
    const d=new Date(lastDate+'T12:00:00');
    curMonth=new Date(d.getFullYear(),d.getMonth(),1);
  }}
  refresh();
  renderGapPanel();
}})();
</script>
</body>
</html>'''

out_path = os.path.join(BASE, "dashboard_v2.html")
with open(out_path, "w") as f:
    f.write(html)

print(f"Written {len(html)} bytes to {out_path}")
print(f"Embedded {len(trades)} trades")
