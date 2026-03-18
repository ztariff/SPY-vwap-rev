#!/usr/bin/env python3
"""
Build stock_dashboard.html with ALL 2,750 stock frontside trades.
Calendar view with strategy filtering, intraday SPY charts, and equity curves.
Self-contained HTML file matching build_dashboard_v2.py dark theme.
"""
import json
import os
import math
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))

# Load data
with open(os.path.join(BASE, "stock_frontside_trades.json")) as f:
    trades = json.load(f)

with open(os.path.join(BASE, "targeted_promoted.json")) as f:
    promoted = json.load(f)

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
promoted = clean(promoted)

trades_json = json.dumps(trades)
promoted_json = json.dumps(promoted)

print(f"Embedding {len(trades)} stock trades ({len(trades_json)} bytes)")
print(f"Embedding {len(promoted)} promoted trades ({len(promoted_json)} bytes)")

# Analyze data for header
strat_keys = set(t['strategy_key'] for t in trades)
dates_count = len(set(t['date'] for t in trades))
pnls = [t.get('pnl_dollar', 0) for t in trades]
pnl_pcts = [t.get('pnl_pct', 0) for t in trades]
wins = sum(1 for p in pnls if p > 0)
total_pnl = sum(pnls)
total_pnl_pct = sum(pnl_pcts)

print(f"Strategies: {len(strat_keys)}")
print(f"Unique days: {dates_count}")
print(f"Win rate: {wins}/{len(trades)} = {100*wins/len(trades):.1f}%")
print(f"Total PnL: ${total_pnl:.0f}")
print(f"Avg PnL: ${total_pnl/len(trades):.2f}")

# Strategy labels
STRAT_LABELS = {
    'spy_fade_0.4x_t050_T5': 'F.4x t.50%',
    'spy_fade_0.4x_t075_T15': 'F.4x t.75%',
    'spy_fade_0.4x_t100_T15': 'F.4x t1.0%',
    'spy_fade_0.5x_t100_T5': 'F.5x t1.0%',
    'spy_buy_0.3x_t050_T15': 'B.3x t.50%',
    'spy_buy_0.4x_t075_T5': 'B.4x t.75%',
    'spy_buy_0.4x_t100_T10': 'B.4x t1.0%',
    'spy_buy_0.4x_t100_T5': 'B.4x t1.0%',
    'spy_buy_0.8x_t005_T15': 'B.8x t.05%',
}

html = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Stock Frontside Mean Reversion — Calendar Dashboard</title>
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

/* Controls */
.controls{{display:flex;align-items:center;gap:12px;padding:12px 20px;flex-wrap:wrap}}
.controls button{{background:#2a2e3d;color:#aaa;border:1px solid #3a3f52;border-radius:4px;padding:5px 12px;font-size:13px;cursor:pointer}}
.controls button:hover{{background:#363c52;color:#fff}}
.month-title{{font-size:15px;font-weight:600;min-width:160px;text-align:center}}
.filter-group{{display:flex;gap:4px;margin-left:auto;flex-wrap:wrap}}
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
.day-total{{position:absolute;bottom:4px;right:6px;font-size:10px;font-weight:700}}

/* Trade detail */
#detail{{padding:0 20px 40px}}
.detail-date{{font-size:15px;font-weight:600;color:#e0e0e0;margin:16px 0 12px;padding-top:16px;border-top:1px solid #2a2e3d}}
.tblock{{margin-bottom:20px;border:1px solid #2a2e3d;border-radius:8px;background:#13162a;overflow:hidden}}
.tblock-hdr{{display:flex;align-items:center;gap:12px;padding:10px 14px;background:#181c30;border-bottom:1px solid #2a2e3d;flex-wrap:wrap}}
.tbadge{{padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700;text-transform:uppercase}}
.tbadge.buy{{background:rgba(38,166,154,.18);color:#26a69a}}
.tbadge.fade{{background:rgba(239,83,80,.18);color:#ef5350}}
.tleg{{color:#999;font-size:12px}}
.tatr{{color:#666;font-size:11px}}
.tpnl{{font-size:16px;font-weight:700;margin-left:auto}}
.tmeta{{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:6px;padding:10px 14px}}
.mc{{background:#181c30;border:1px solid #22263a;border-radius:5px;padding:6px 10px}}
.mc .ml{{font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.5px;font-weight:600}}
.mc .mv{{font-size:13px;font-weight:600;margin-top:2px}}
.tcharts{{display:grid;grid-template-columns:1fr;gap:10px;padding:10px 14px}}
.tcbox{{background:#0f1117;border:1px solid #22263a;border-radius:6px;padding:10px;position:relative}}
.tcbox .tclbl{{font-size:11px;color:#666;margin-bottom:6px;font-weight:600}}
.tcbox .tccont{{width:100%;height:280px}}
.tt-ov{{position:absolute;top:32px;left:16px;background:rgba(15,17,23,.9);border:1px solid #2a2e3d;border-radius:5px;padding:5px 8px;font-size:10px;line-height:1.5;pointer-events:none;z-index:100;display:none;min-width:120px}}

/* Strategy summary table */
#strat-panel{{padding:20px}}
.strat-tbl{{width:100%;border-collapse:collapse;font-size:11px;margin-bottom:20px}}
.strat-tbl th{{text-align:left;padding:8px;color:#666;font-size:10px;text-transform:uppercase;border-bottom:1px solid #2a2e3d;font-weight:600;background:#13162a}}
.strat-tbl td{{padding:8px;border-bottom:1px solid rgba(34,38,58,.5)}}
.strat-tbl td.num{{text-align:right;font-family:monospace;font-weight:600}}

/* Notes footer */
#notes{{padding:20px;font-size:11px;color:#555;border-top:1px solid #2a2e3d;background:#0f1117;line-height:1.6}}
</style>
</head>
<body>

<div id="hdr">
  <h1>Stock Frontside Mean Reversion — Calendar Dashboard</h1>
  <div class="stats">
    <span><span class="sl">Trades</span><span class="sv" id="s-n">-</span></span>
    <span><span class="sl">Strategies</span><span class="sv" id="s-strat">-</span></span>
    <span><span class="sl">Days</span><span class="sv" id="s-days">-</span></span>
    <span><span class="sl">Avg P&L</span><span class="sv" id="s-avg">-</span></span>
    <span><span class="sl">Win Rate</span><span class="sv" id="s-wr">-</span></span>
    <span><span class="sl">Total P&L</span><span class="sv" id="s-tot">-</span></span>
    <span><span class="sl">Total P&L %</span><span class="sv" id="s-pct">-</span></span>
  </div>
</div>

<div class="controls">
  <button id="prev-m">&laquo;</button>
  <div class="month-title" id="m-title">-</div>
  <button id="next-m">&raquo;</button>
  <div class="filter-group">
    <button class="fbtn on" data-f="all">All</button>
    <button class="fbtn" data-f="buy">Buy Dip</button>
    <button class="fbtn" data-f="fade">Fade</button>
    <button class="fbtn" data-f="0.3x">0.3x ATR</button>
    <button class="fbtn" data-f="0.4x">0.4x ATR</button>
    <button class="fbtn" data-f="0.5x">0.5x ATR</button>
    <button class="fbtn" data-f="0.8x">0.8x ATR</button>
    <button class="fbtn" data-f="win">Winners</button>
    <button class="fbtn" data-f="loss">Losers</button>
  </div>
</div>

<div id="eq-wrap">
  <div id="eq-container"></div>
  <div id="eq-label">Monthly Cumulative P&L</div>
</div>

<div id="cal-wrap"><div class="cal-grid" id="cal-grid"></div></div>
<div id="detail"></div>

<div id="strat-panel"></div>
<div id="notes"></div>

<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
<script>
// ═══════════════════════════════════════════════════════════════════
//  DATA (all {{len(trades)}} trades from real Polygon 1-min bars)
// ═══════════════════════════════════════════════════════════════════
const TRADES={trades_json};
const PROMOTED={promoted_json};
const PK='cBE5Kbq9yllt0Yj29mDQjBcIKfAYQlHF';

const STRAT_LABELS={json.dumps(STRAT_LABELS)};

// ═══════════════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════════════
let curMonth=new Date();
let filter='all';
let selDate=null;
let eqChart=null,eqSeries=null;
let detailCharts=[];
const fcache={{}};

// ═══════════════════════════════════════════════════════════════════
//  UTILITIES
// ═══════════════════════════════════════════════════════════════════
function fmtD(v){{const a=Math.abs(v);const s=a>=1000?(a/1000).toFixed(1)+'k':a.toFixed(0);return(v>=0?'+$':'-$')+s}}
function fmtP(v){{return(v>=0?'+':'')+v.toFixed(2)+'%'}}
function fmtT12(t){{if(!t||t==='-')return'-';let s=String(t);if(s.includes(' '))s=s.split(' ')[1];if(!s)return'-';const p=s.split(':');if(p.length<2)return s;let h=parseInt(p[0],10),m=p[1];if(isNaN(h))return s;const ap=h>=12?'PM':'AM';if(h>12)h-=12;if(h===0)h=12;return h+':'+m+' '+ap}}

// Position sizing: RISK $25K-$100K per trade at the stop level
// shares = risk_budget / (entry × stop% / 100)
// Notional cap: $5M per position (intraday margin ~$1.25M at 4:1)
const STRAT_META={{}};
const MAX_NOTIONAL=5000000;
(function(){{
  const byStrat={{}};
  TRADES.forEach(t=>{{
    const sk=t.strategy_key;
    if(!byStrat[sk])byStrat[sk]={{pnls:[],wins:0,n:0,stop:t.stop_pct||1}};
    byStrat[sk].pnls.push(t.pnl_pct||0);
    byStrat[sk].n+=1;
    if((t.pnl_pct||0)>0)byStrat[sk].wins+=1;
  }});
  Object.keys(byStrat).forEach(sk=>{{
    const s=byStrat[sk];
    const avg=s.pnls.reduce((a,b)=>a+b,0)/s.n;
    const std=Math.sqrt(s.pnls.reduce((a,b)=>a+(b-avg)**2,0)/s.n);
    const sharpe=std>0?avg/std:0;
    const wr=s.wins/s.n;
    const score=Math.min(1,Math.max(0,(sharpe*2+wr)/3));
    const riskBudget=Math.round(25000+score*75000);
    STRAT_META[sk]={{riskBudget,stop:s.stop,sharpe,wr,score}};
  }});
}})();
function tradeShares(t){{
  const sm=STRAT_META[t.strategy_key]||{{riskBudget:50000,stop:1}};
  const ep=t.spy_entry_price||500;
  const riskPerShare=ep*(sm.stop/100);
  if(riskPerShare<=0)return 0;
  let shares=Math.floor(sm.riskBudget/riskPerShare);
  const maxShares=Math.floor(MAX_NOTIONAL/ep);
  if(shares>maxShares)shares=maxShares;
  return shares;
}}
function posDollar(t){{
  const sh=tradeShares(t);
  return sh*(t.pnl_pct||0)/100*(t.spy_entry_price||500);
}}
function posRisk(t){{
  const sh=tradeShares(t);
  const ep=t.spy_entry_price||500;
  const sm=STRAT_META[t.strategy_key]||{{stop:1}};
  return sh*ep*(sm.stop/100);
}}

// ═══════════════════════════════════════════════════════════════════
//  FILTERING
// ═══════════════════════════════════════════════════════════════════
function getFiltered(){{
  return TRADES.filter(t=>{{
    if(filter==='win')return (t.pnl_pct||0)>0;
    if(filter==='loss')return (t.pnl_pct||0)<=0;
    if(filter==='buy')return t.direction==='below';
    if(filter==='fade')return t.direction==='above';
    if(filter==='0.3x')return t.atr_mult===0.3;
    if(filter==='0.4x')return t.atr_mult===0.4;
    if(filter==='0.5x')return t.atr_mult===0.5;
    if(filter==='0.8x')return t.atr_mult===0.8;
    return true;
  }});
}}

// ═══════════════════════════════════════════════════════════════════
//  HEADER STATS
// ═══════════════════════════════════════════════════════════════════
function updateStats(){{
  const ft=getFiltered();
  const n=ft.length;
  if(!n){{['s-n','s-strat','s-days','s-avg','s-wr','s-tot','s-pct'].forEach(id=>document.getElementById(id).textContent='-');return}}

  const pnls=ft.map(t=>posDollar(t));
  const pcts=ft.map(t=>t.pnl_pct||0);
  const wins=ft.filter(t=>(posDollar(t))>0).length;
  const tot=pnls.reduce((a,b)=>a+b,0);
  const totPct=pcts.reduce((a,b)=>a+b,0);
  const avgP=tot/n;
  const strats=new Set(ft.map(t=>t.strategy_key)).size;
  const days=new Set(ft.map(t=>t.date)).size;
  const wr=wins/n*100;

  document.getElementById('s-n').textContent=n;
  document.getElementById('s-strat').textContent=strats;
  document.getElementById('s-days').textContent=days;
  const avgEl=document.getElementById('s-avg');avgEl.textContent=fmtD(avgP);avgEl.className='sv '+(avgP>=0?'pos':'neg');
  const wrEl=document.getElementById('s-wr');wrEl.textContent=wr.toFixed(1)+'%';wrEl.className='sv '+(wr>50?'pos':'neg');
  const totEl=document.getElementById('s-tot');totEl.textContent=fmtD(tot);totEl.className='sv '+(tot>=0?'pos':'neg');
  const pctEl=document.getElementById('s-pct');pctEl.textContent=fmtP(totPct);pctEl.className='sv '+(totPct>=0?'pos':'neg');
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
  const byD={{}};
  ft.forEach(t=>{{if(!byD[t.date])byD[t.date]=0;byD[t.date]+=(posDollar(t))}});
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
  new ResizeObserver(()=>{{if(eqChart)eqChart.applyOptions({{width:c.clientWidth}});}}).observe(c);
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
    const dayP=dt.reduce((s,t)=>s+(posDollar(t)),0);
    let cls='cal-cell';
    if(ds===today)cls+=' today';
    if(has)cls+=' has';
    if(ds===selDate)cls+=' sel';
    let inner=`<div class="dn">${{d}}</div>`;
    dt.forEach(t=>{{
      const w=(posDollar(t))>0;
      const lbl=STRAT_LABELS[t.strategy_key]||t.strategy_key.slice(0,12);
      inner+=`<div class="pill ${{w?'w':'l'}}"><span class="plbl">${{lbl}}</span><span class="ppnl">${{fmtD(posDollar(t))}}</span></div>`;
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
  const dayP=dt.reduce((s,t)=>s+(posDollar(t)),0);
  let html=`<div class="detail-date">${{dl}} — ${{dt.length}} Trade${{dt.length>1?'s':''}} — <span class="${{dayP>=0?'pos':'neg'}}">${{fmtD(dayP)}}</span></div>`;

  dt.forEach((t,idx)=>{{
    const w=(posDollar(t))>0;
    const pc=w?'#26a69a':'#ef5350';
    const dirLbl=t.direction==='below'?'BUY DIP':'FADE';
    const dirCls=t.direction==='below'?'buy':'fade';
    const mult=t.atr_mult||'?';
    const exitR=(t.exit_reason||'-').replace(/_/g,' ').toUpperCase();
    const exitC=t.exit_reason==='target'?'pos':t.exit_reason==='stop'||t.exit_reason==='stop_loss'?'neg':'muted';
    const shares=tradeShares(t);
    const posD=posDollar(t);
    const notional=shares*(t.spy_entry_price||500);
    const riskAmt=posRisk(t);

    html+=`<div class="tblock">
    <div class="tblock-hdr">
      <span class="tbadge ${{dirCls}}">${{dirLbl}}</span>
      <span class="tleg">${{STRAT_LABELS[t.strategy_key]||t.strategy_key}}</span>
      <span class="tatr">ATR ${{mult}}x</span>
      <span class="tpnl" style="color:${{pc}}">${{fmtP(t.pnl_pct||0)}} ${{fmtD(posD)}}</span>
    </div>
    <div class="tmeta">
      <div class="mc"><div class="ml">Risk</div><div class="mv" style="color:#ce93d8;font-weight:700">${{fmtD(riskAmt).replace('+$','$')}}</div></div>
      <div class="mc"><div class="ml">Notional</div><div class="mv">${{notional>=1000000?'$'+(notional/1000000).toFixed(1)+'M':'$'+(notional/1000).toFixed(0)+'K'}}<span style="color:#666"> (${{shares.toLocaleString()}} shs)</span></div></div>
      <div class="mc"><div class="ml">P&L ($)</div><div class="mv ${{posD>=0?'pos':'neg'}}" style="font-weight:700">${{fmtD(posD)}}</div></div>
      <div class="mc"><div class="ml">SPY Entry</div><div class="mv">$${{(t.spy_entry_price||0).toFixed(2)}}</div></div>
      <div class="mc"><div class="ml">SPY Exit</div><div class="mv">$${{(t.exit_price||0).toFixed(2)}}</div></div>
      <div class="mc"><div class="ml">Entry VWAP</div><div class="mv">$${{(t.entry_vwap||0).toFixed(2)}}</div></div>
      <div class="mc"><div class="ml">ATR Value</div><div class="mv">$${{(t.atr_value||0).toFixed(2)}}</div></div>
      <div class="mc"><div class="ml">Threshold</div><div class="mv">$${{(t.threshold_level||0).toFixed(2)}}</div></div>
      <div class="mc"><div class="ml">Target</div><div class="mv">${{t.target_pct||0}}%</div></div>
      <div class="mc"><div class="ml">Stop</div><div class="mv">${{t.stop_pct||0}}%</div></div>
      <div class="mc"><div class="ml">Entry Time</div><div class="mv">${{fmtT12(t.entry_time)}}</div></div>
      <div class="mc"><div class="ml">Exit Time</div><div class="mv">${{fmtT12(t.exit_time_iso||t.exit_time||'-')}}</div></div>
      <div class="mc"><div class="ml">Held</div><div class="mv">${{t.minutes_held!=null?Math.round(t.minutes_held)+'m':'-'}}</div></div>
      <div class="mc"><div class="ml">Exit Reason</div><div class="mv ${{exitC}}">${{exitR}}</div></div>
      <div class="mc"><div class="ml">VIX</div><div class="mv">${{(t.vix||0).toFixed(1)}}</div></div>
    </div>
    <div class="tcharts">
      <div class="tcbox">
        <div class="tclbl">SPY 1-Min with VWAP + Entry/Exit Levels</div>
        <div class="tccont" id="spy-${{idx}}"></div>
        <div class="tt-ov" id="spy-tt-${{idx}}"></div>
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
    const url=`https://api.polygon.io/v2/aggs/ticker/${{ticker}}/range/1/minute/${{dateStr}}/${{dateStr}}?adjusted=true&sort=asc&limit=50000&apiKey=${{PK}}`;
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

      // No horizontal level lines — just markers at entry/exit points
      // Auto-fit price scale to visible range (exclude volume)
      chart.priceScale('right').applyOptions({{autoScale:true,scaleMargins:{{top:0.05,bottom:0.15}}}});

      // Entry/exit markers
      const markers=[];
      const ets=isoToSec(trade.entry_time_iso);
      const xts=isoToSec(trade.exit_time_iso);
      if(ets){{const ct=findNearest(cdata,ets);if(ct)markers.push({{time:ct,position:'aboveBar',color:'#2962ff',shape:'circle',text:`ENTRY $${{(trade.spy_entry_price||0).toFixed(2)}}`}})}}
      if(xts){{const ct=findNearest(cdata,xts);if(ct)markers.push({{time:ct,position:'belowBar',color:(trade.pnl_dollar||0)>=0?'#26a69a':'#ef5350',shape:'circle',text:`EXIT $${{(trade.exit_price||0).toFixed(2)}}`}})}}
      if(markers.length){{markers.sort((a,b)=>a.time-b.time);candles.setMarkers(markers)}}

      setupTT(chart,candles,`spy-tt-${{idx}}`);
      chart.timeScale().fitContent();
      new ResizeObserver(()=>chart.applyOptions({{width:spyC.clientWidth}})).observe(spyC);
    }}else{{spyC.innerHTML='<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#444;font-size:12px">No SPY data</div>'}}
  }}
}}

// ═══════════════════════════════════════════════════════════════════
//  STRATEGY SUMMARY
// ═══════════════════════════════════════════════════════════════════
function renderStratPanel(){{
  const sec=document.getElementById('strat-panel');
  const ft=getFiltered();
  const byStrat={{}};

  ft.forEach(t=>{{
    const sk=t.strategy_key;
    if(!byStrat[sk]){{
      byStrat[sk]={{
        key:sk,
        label:STRAT_LABELS[sk]||sk,
        trades:0,
        wins:0,
        pnls:[],
        pcts:[]
      }};
    }}
    byStrat[sk].trades+=1;
    byStrat[sk].pnls.push(posDollar(t));
    byStrat[sk].pcts.push(t.pnl_pct||0);
    if((posDollar(t))>0)byStrat[sk].wins+=1;
  }});

  let rows='';
  for(const [sk,s] of Object.entries(byStrat).sort()){{
    const totP=s.pnls.reduce((a,b)=>a+b,0);
    const totPct=s.pcts.reduce((a,b)=>a+b,0);
    const avgP=totP/s.trades;
    const wr=(s.wins/s.trades*100).toFixed(1);

    // Sharpe approximation (std of returns / mean)
    const mean=avgP;
    const variance=s.pnls.reduce((sq,p)=>sq+Math.pow(p-mean,2),0)/s.trades;
    const std=Math.sqrt(variance);
    const sharpe=std>0?mean/std:0;

    // Profit factor
    const gains=s.pnls.filter(p=>p>0).reduce((a,b)=>a+b,0);
    const losses=Math.abs(s.pnls.filter(p=>p<0).reduce((a,b)=>a+b,0));
    const pf=losses>0?gains/losses:gains>0?99:0;

    rows+=`<tr>
      <td>${{s.label}}</td>
      <td class="num">${{s.trades}}</td>
      <td class="num">${{wr}}%</td>
      <td class="num ${{avgP>=0?'pos':'neg'}}">${{fmtD(avgP)}}</td>
      <td class="num ${{totPct>=0?'pos':'neg'}}">${{fmtP(totPct)}}</td>
      <td class="num">${{sharpe.toFixed(2)}}</td>
      <td class="num">${{pf.toFixed(2)}}</td>
    </tr>`;
  }}

  sec.innerHTML=`
  <h3 style="padding:20px 20px 0;color:#e0e0e0;border-top:1px solid #2a2e3d;margin-top:20px">Strategy Summary</h3>
  <table class="strat-tbl">
    <tr>
      <th>Strategy</th>
      <th>N Trades</th>
      <th>Win Rate</th>
      <th>Avg P&L</th>
      <th>Total P&L %</th>
      <th>Sharpe</th>
      <th>Profit Factor</th>
    </tr>
    ${{rows}}
  </table>`;
}}

function renderNotes(){{
  const sec=document.getElementById('notes');
  sec.innerHTML=`
  <strong>Data Notes:</strong> All {{len(trades)}} trades from real Polygon 1-minute bars. Frontside limit order fills.
  IBKR commission modeled. No fabricated data. SPY mean reversion via VWAP deviation (Fade above, Buy below) with ATR-based thresholds.
  Entry levels dynamically set at VWAP ± (ATR × multiplier). Targets and stops use percentage-based exits.
  Calendar shows pill per trade colored by outcome (green=win, red=loss) with abbreviated strategy label.
  `;
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

function refresh(){{updateStats();renderEquity();renderCal();renderStratPanel()}}

// ═══════════════════════════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════════════════════════
(function init(){{
  if(TRADES.length){{
    const lastDate=TRADES[TRADES.length-1].date;
    const d=new Date(lastDate+'T12:00:00');
    curMonth=new Date(d.getFullYear(),d.getMonth(),1);
  }}
  refresh();
  renderNotes();
}})();
</script>
</body>
</html>'''

out_path = os.path.join(BASE, "stock_dashboard.html")
with open(out_path, "w") as f:
    f.write(html)

file_size_mb = len(html) / (1024 * 1024)
print(f"\n✓ Written {len(html):,} bytes ({file_size_mb:.1f} MB) to {out_path}")
print(f"✓ Embedded {len(trades):,} trades across {len(strat_keys)} strategies")
print(f"✓ {dates_count} unique trade days")
