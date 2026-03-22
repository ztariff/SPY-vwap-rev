#!/usr/bin/env python3
"""Build kite_dashboard.html — calendar dashboard with strategy dropdown for KITE backtests."""
import json, os, numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))

# Load all strategy trade files
strategies = {
    'V16': 'kite_v16_trades.json',
    'Champion': 'kite_champion_trades.json',
    'Grade10': 'kite_grade10_trades.json',
    'RangeOnly': 'kite_rangeonly_trades.json',
    'V9': 'kite_v9_trades.json',
    'V16b': 'kite_v16b_trades.json',
}

all_data = {}
strat_meta = {}

for name, fname in strategies.items():
    with open(os.path.join(BASE, fname)) as f:
        raw = json.load(f)
    trades = []
    for t in raw:
        pnl = float(t.get('mtm_pl', 0) or 0)
        ep = float(t['entry_price'])
        xp = float(t['exit_price'])
        shares = float(t['matched_shares'])
        fees = float(t.get('entry_fees', 0) or 0) + float(t.get('exit_fees', 0) or 0)
        entry_time = t['entry_time']
        exit_time = t['exit_time']
        date = entry_time[:10]
        side_val = float(t['entry_side'])
        pnl_pct = (xp - ep) / ep * 100 * (1 if side_val > 0 else -1)
        trades.append({
            'date': date,
            'entry_price': round(ep, 2),
            'exit_price': round(xp, 2),
            'shares': int(shares),
            'pnl': round(pnl, 0),
            'pnl_pct': round(pnl_pct, 3),
            'fees': round(fees, 0),
            'entry_time': entry_time[11:16],
            'exit_time': exit_time[11:16],
            'side': 'BUY' if side_val > 0 else 'SHORT',
        })
    trades.sort(key=lambda x: x['date'] + x['entry_time'])
    all_data[name] = trades

    # Compute strategy-level stats
    pnls = [t['pnl'] for t in trades]
    n = len(pnls)
    total = sum(pnls)
    avg = total / n if n else 0
    wins = sum(1 for p in pnls if p > 0)
    wr = wins / n * 100 if n else 0
    std = float(np.std(pnls, ddof=1)) if n > 1 else 1
    sharpe = avg / std * np.sqrt(n / 4.2) if std > 0 else 0
    gain_sum = sum(p for p in pnls if p > 0)
    loss_sum = abs(sum(p for p in pnls if p < 0))
    pf = gain_sum / loss_sum if loss_sum > 0 else 99
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    max_dd = float(np.max(peak - cum))
    strat_meta[name] = {
        'n': n, 'total': round(total, 0), 'avg': round(avg, 0), 'wr': round(wr, 1),
        'sharpe': round(float(sharpe), 3), 'pf': round(float(pf), 2), 'max_dd': round(max_dd, 0)
    }
    print(f"  {name}: {n} trades, Sharpe {sharpe:.3f}, Total ${total:,.0f}")

data_js = json.dumps(all_data)
meta_js = json.dumps(strat_meta)

# Build dropdown options
dropdown_opts = ""
for name in ['V16', 'Champion', 'Grade10', 'RangeOnly', 'V9', 'V16b']:
    m = strat_meta[name]
    dropdown_opts += f'    <option value="{name}">{name} (Sharpe {m["sharpe"]:.2f})</option>\n'

PK = 'cBE5Kbq9yllt0Yj29mDQjBcIKfAYQlHF'

html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>C-Shark KITE Backtest Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0f1117;color:#DDD;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;overflow-x:hidden}
.pos{color:#26a69a}.neg{color:#ef5350}.muted{color:#666}

#hdr{display:flex;align-items:center;justify-content:space-between;padding:10px 20px;background:#181b28;border-bottom:1px solid #2a2e3d;flex-wrap:wrap;gap:8px}
#hdr h1{font-size:15px;font-weight:600;color:#e0e0e0;white-space:nowrap}
#hdr .stats{display:flex;gap:16px;font-size:12px;flex-wrap:wrap}
#hdr .sl{color:#666;margin-right:4px}
#hdr .sv{font-weight:700}

.controls{display:flex;align-items:center;gap:12px;padding:12px 20px;flex-wrap:wrap}
.controls button{background:#2a2e3d;color:#aaa;border:1px solid #3a3f52;border-radius:4px;padding:5px 12px;font-size:13px;cursor:pointer}
.controls button:hover{background:#363c52;color:#fff}
.month-title{font-size:15px;font-weight:600;min-width:160px;text-align:center}

.strat-select{background:#2a2e3d;color:#e0e0e0;border:1px solid #3a3f52;border-radius:4px;padding:6px 14px;font-size:13px;cursor:pointer;font-weight:600;min-width:180px;appearance:auto}
.strat-select:hover{background:#363c52;border-color:#2962ff}
.strat-select:focus{outline:none;border-color:#2962ff;box-shadow:0 0 0 1px #2962ff}
.strat-select option{background:#1a1e2e;color:#e0e0e0;padding:4px}

.sharpe-badge{font-size:12px;font-weight:700;padding:4px 10px;border-radius:4px;margin-left:2px;letter-spacing:.3px}
.sharpe-badge.good{background:rgba(38,166,154,.18);color:#26a69a;border:1px solid rgba(38,166,154,.3)}
.sharpe-badge.ok{background:rgba(255,152,0,.18);color:#ff9800;border:1px solid rgba(255,152,0,.3)}
.sharpe-badge.bad{background:rgba(239,83,80,.18);color:#ef5350;border:1px solid rgba(239,83,80,.3)}

.filter-group{display:flex;gap:4px;margin-left:auto;flex-wrap:wrap}
.fbtn{background:#2a2e3d;color:#777;border:1px solid #3a3f52;border-radius:4px;padding:4px 10px;font-size:11px;cursor:pointer;font-weight:600}
.fbtn:hover{color:#ddd}.fbtn.on{background:#2962ff;color:#fff;border-color:#2962ff}

#eq-wrap{padding:4px 20px 8px;position:relative}
#eq-container{width:100%;height:130px;border-radius:6px;border:1px solid #2a2e3d;background:#0f1117}
#eq-label{position:absolute;top:10px;left:30px;font-size:11px;color:#555;pointer-events:none}

#cal-wrap{padding:4px 20px 12px}
.cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:2px}
.cal-hdr{text-align:center;font-size:10px;color:#555;padding:6px 0;text-transform:uppercase;letter-spacing:1px;font-weight:700}
.cal-cell{min-height:82px;background:#161925;border:1px solid #22263a;border-radius:4px;padding:6px 8px;position:relative;cursor:default;transition:all .12s}
.cal-cell.om{opacity:.25}
.cal-cell.has{cursor:pointer}
.cal-cell.has:hover{border-color:#2962ff;background:#1a2040}
.cal-cell.sel{border-color:#2962ff;background:#1a2040;box-shadow:0 0 0 1px #2962ff}
.cal-cell .dn{font-size:11px;color:#555;margin-bottom:4px;font-weight:500}
.cal-cell.today .dn{color:#2962ff;font-weight:700}
.pill{font-size:10px;padding:3px 6px;border-radius:3px;margin-bottom:2px;display:flex;justify-content:space-between;align-items:center;gap:3px;line-height:1.3}
.pill.w{background:rgba(38,166,154,.12);color:#26a69a;border:1px solid rgba(38,166,154,.25)}
.pill.l{background:rgba(239,83,80,.12);color:#ef5350;border:1px solid rgba(239,83,80,.25)}
.pill .plbl{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:50px}
.pill .ppnl{font-weight:700;white-space:nowrap}
.day-total{position:absolute;bottom:4px;right:6px;font-size:10px;font-weight:700}

#detail{padding:0 20px 20px}
.detail-date{font-size:15px;font-weight:600;color:#e0e0e0;margin:16px 0 12px;padding-top:16px;border-top:1px solid #2a2e3d}
.tblock{margin-bottom:16px;border:1px solid #2a2e3d;border-radius:8px;background:#13162a;overflow:hidden}
.tblock-hdr{display:flex;align-items:center;gap:12px;padding:10px 14px;background:#181c30;border-bottom:1px solid #2a2e3d;flex-wrap:wrap}
.tbadge{padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700;text-transform:uppercase}
.tbadge.buy{background:rgba(38,166,154,.18);color:#26a69a}
.tbadge.short{background:rgba(239,83,80,.18);color:#ef5350}
.tpnl{font-size:16px;font-weight:700;margin-left:auto}
.tmeta{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:6px;padding:10px 14px}
.mc{background:#181c30;border:1px solid #22263a;border-radius:5px;padding:6px 10px}
.mc .ml{font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.5px;font-weight:600}
.mc .mv{font-size:13px;font-weight:600;margin-top:2px}

.tcharts{display:grid;grid-template-columns:1fr;gap:10px;padding:10px 14px}
.tcbox{background:#0f1117;border:1px solid #22263a;border-radius:6px;padding:10px;position:relative}
.tcbox .tclbl{font-size:11px;color:#666;margin-bottom:6px;font-weight:600}
.tcbox .tccont{width:100%;height:500px}
.tt-ov{position:absolute;top:32px;left:16px;background:rgba(15,17,23,.9);border:1px solid #2a2e3d;border-radius:5px;padding:5px 8px;font-size:10px;line-height:1.5;pointer-events:none;z-index:100;display:none;min-width:120px}

#strat-panel{padding:0 20px 20px}
.strat-tbl{width:100%;border-collapse:collapse;font-size:12px;margin-top:12px}
.strat-tbl th{text-align:left;padding:10px 12px;color:#666;font-size:10px;text-transform:uppercase;border-bottom:1px solid #2a2e3d;font-weight:600;background:#13162a}
.strat-tbl th.num{text-align:right}
.strat-tbl td{padding:10px 12px;border-bottom:1px solid rgba(34,38,58,.5)}
.strat-tbl td.num{text-align:right;font-family:'SF Mono',Consolas,monospace;font-weight:600}
.strat-tbl tr.active{background:#1a2040}
.strat-tbl tr:hover{background:#161d35;cursor:pointer}
.rank-badge{display:inline-block;width:20px;height:20px;border-radius:50%;text-align:center;line-height:20px;font-size:10px;font-weight:700;margin-right:6px}
.rank-1{background:rgba(255,215,0,.2);color:#ffd700}
.rank-2{background:rgba(192,192,192,.2);color:#c0c0c0}
.rank-3{background:rgba(205,127,50,.2);color:#cd7f32}
</style>
</head>
<body>

<div id="hdr">
  <h1>C-Shark KITE Backtest Dashboard</h1>
  <div class="stats">
    <span><span class="sl">Trades</span><span class="sv" id="s-n">-</span></span>
    <span><span class="sl">Win Rate</span><span class="sv" id="s-wr">-</span></span>
    <span><span class="sl">Avg P&L</span><span class="sv" id="s-avg">-</span></span>
    <span><span class="sl">Total P&L</span><span class="sv" id="s-tot">-</span></span>
    <span><span class="sl">Sharpe</span><span class="sv" id="s-sh">-</span></span>
    <span><span class="sl">PF</span><span class="sv" id="s-pf">-</span></span>
    <span><span class="sl">Max DD</span><span class="sv" id="s-dd">-</span></span>
    <span><span class="sl">Month P&L</span><span class="sv" id="s-mo">-</span></span>
  </div>
</div>

<div class="controls">
  <button id="prev-m">&laquo;</button>
  <div class="month-title" id="m-title">-</div>
  <button id="next-m">&raquo;</button>
  <select class="strat-select" id="strat-sel">
""" + dropdown_opts + """  </select>
  <span class="sharpe-badge good" id="sharpe-badge">Sharpe 2.183</span>
  <div class="filter-group">
    <button class="fbtn on" data-f="all">All</button>
    <button class="fbtn" data-f="win">Winners</button>
    <button class="fbtn" data-f="loss">Losers</button>
  </div>
</div>

<div id="eq-wrap">
  <div id="eq-container"></div>
  <div id="eq-label">Cumulative P&L (all time)</div>
</div>

<div id="cal-wrap"><div class="cal-grid" id="cal-grid"></div></div>
<div id="detail"></div>
<div id="strat-panel"></div>

<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
<script>
const ALL_DATA = """ + data_js + """;
const STRAT_META = """ + meta_js + """;
const PK = '""" + PK + """';

let curStrat = 'V16';
let curMonth = new Date();
let filter = 'all';
let selDate = null;
let eqChart = null, eqSeries = null;
let detailCharts = [];
const fcache = {};

function trades() { return ALL_DATA[curStrat] || []; }

function fmtD(v) {
  const a = Math.abs(v);
  const s = a >= 1000000 ? (a/1000000).toFixed(1)+'M' : a >= 1000 ? (a/1000).toFixed(1)+'k' : a.toFixed(0);
  return (v >= 0 ? '+$' : '-$') + s;
}
function fmtP(v) { return (v >= 0 ? '+' : '') + v.toFixed(3) + '%'; }
function fmtT12(t) {
  if (!t || t === '-') return '-';
  const p = t.split(':');
  if (p.length < 2) return t;
  let h = parseInt(p[0], 10), m = p[1];
  if (isNaN(h)) return t;
  const ap = h >= 12 ? 'PM' : 'AM';
  if (h > 12) h -= 12;
  if (h === 0) h = 12;
  return h + ':' + m + ' ' + ap;
}

function getFiltered() {
  return trades().filter(t => {
    if (filter === 'win') return t.pnl > 0;
    if (filter === 'loss') return t.pnl <= 0;
    return true;
  });
}

function updateStats() {
  const ft = getFiltered();
  const n = ft.length;
  if (!n) {
    ['s-n','s-wr','s-avg','s-tot','s-sh','s-pf','s-dd'].forEach(id => document.getElementById(id).textContent = '-');
    return;
  }
  const m = STRAT_META[curStrat];
  document.getElementById('s-n').textContent = n;

  const wins = ft.filter(t => t.pnl > 0).length;
  const wr = wins / n * 100;
  const wrEl = document.getElementById('s-wr');
  wrEl.textContent = wr.toFixed(1) + '%';
  wrEl.className = 'sv ' + (wr > 50 ? 'pos' : 'neg');

  const tot = ft.reduce((s, t) => s + t.pnl, 0);
  const avg = tot / n;

  const avgEl = document.getElementById('s-avg');
  avgEl.textContent = fmtD(avg);
  avgEl.className = 'sv ' + (avg >= 0 ? 'pos' : 'neg');

  const totEl = document.getElementById('s-tot');
  totEl.textContent = fmtD(tot);
  totEl.className = 'sv ' + (tot >= 0 ? 'pos' : 'neg');

  const shEl = document.getElementById('s-sh');
  shEl.textContent = m.sharpe.toFixed(3);
  shEl.className = 'sv ' + (m.sharpe > 1.5 ? 'pos' : m.sharpe > 0.5 ? '' : 'neg');

  const pfEl = document.getElementById('s-pf');
  pfEl.textContent = m.pf.toFixed(2);
  pfEl.className = 'sv ' + (m.pf > 1.5 ? 'pos' : m.pf > 1 ? '' : 'neg');

  const ddEl = document.getElementById('s-dd');
  ddEl.textContent = '-$' + (m.max_dd >= 1000 ? (m.max_dd/1000).toFixed(0) + 'k' : m.max_dd.toFixed(0));
  ddEl.className = 'sv neg';

  const yr = curMonth.getFullYear(), mo = curMonth.getMonth();
  const moTrades = ft.filter(t => { const d = new Date(t.date + 'T12:00:00'); return d.getFullYear() === yr && d.getMonth() === mo; });
  const moPnl = moTrades.reduce((s, t) => s + t.pnl, 0);
  const moEl = document.getElementById('s-mo');
  moEl.textContent = fmtD(moPnl) + ' (' + moTrades.length + ')';
  moEl.className = 'sv ' + (moPnl >= 0 ? 'pos' : 'neg');

  const badge = document.getElementById('sharpe-badge');
  badge.textContent = 'Sharpe ' + m.sharpe.toFixed(3);
  badge.className = 'sharpe-badge ' + (m.sharpe >= 1.5 ? 'good' : m.sharpe >= 0.8 ? 'ok' : 'bad');
}

function renderEquity() {
  const c = document.getElementById('eq-container');
  if (eqChart) { eqChart.remove(); eqChart = null; eqSeries = null; }

  const ft = getFiltered();
  if (!ft.length) {
    c.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#444;font-size:12px">No trades</div>';
    return;
  }
  c.innerHTML = '';
  eqChart = LightweightCharts.createChart(c, {
    width: c.clientWidth, height: 130,
    layout: { background: { color: '#0f1117' }, textColor: '#777', fontSize: 10 },
    grid: { vertLines: { visible: false }, horzLines: { color: 'rgba(255,255,255,0.03)' } },
    rightPriceScale: { borderVisible: false, drawTicks: false },
    timeScale: { borderVisible: false, timeVisible: false, fixLeftEdge: true, fixRightEdge: true },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    handleScroll: true, handleScale: true
  });

  const byD = {};
  ft.forEach(t => { if (!byD[t.date]) byD[t.date] = 0; byD[t.date] += t.pnl; });
  let cum = 0;
  const data = Object.keys(byD).sort().map(d => { cum += byD[d]; return { time: d, value: Math.round(cum) }; });

  eqSeries = eqChart.addAreaSeries({
    topColor: cum >= 0 ? 'rgba(38,166,154,0.35)' : 'rgba(239,83,80,0.35)',
    bottomColor: cum >= 0 ? 'rgba(38,166,154,0.02)' : 'rgba(239,83,80,0.02)',
    lineColor: cum >= 0 ? '#26a69a' : '#ef5350', lineWidth: 2,
    lastValueVisible: true, priceLineVisible: false
  });
  eqSeries.setData(data);
  eqChart.timeScale().fitContent();
  new ResizeObserver(() => { if (eqChart) eqChart.applyOptions({ width: c.clientWidth }); }).observe(c);
}

function renderCal() {
  const g = document.getElementById('cal-grid');
  const yr = curMonth.getFullYear(), mo = curMonth.getMonth();
  document.getElementById('m-title').textContent = new Date(yr, mo).toLocaleString('en-US', { month: 'long', year: 'numeric' });
  const first = new Date(yr, mo, 1), last = new Date(yr, mo + 1, 0);
  const pad = first.getDay(), dim = last.getDate();
  const ft = getFiltered();
  const byD = {};
  ft.forEach(t => { if (!byD[t.date]) byD[t.date] = []; byD[t.date].push(t); });
  const today = new Date().toISOString().slice(0, 10);

  let html = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(d => '<div class="cal-hdr">' + d + '</div>').join('');
  const prev = new Date(yr, mo, 0);
  for (let i = pad - 1; i >= 0; i--) html += '<div class="cal-cell om"><div class="dn">' + (prev.getDate() - i) + '</div></div>';

  for (let d = 1; d <= dim; d++) {
    const ds = yr + '-' + String(mo+1).padStart(2,'0') + '-' + String(d).padStart(2,'0');
    const dt = byD[ds] || [];
    const has = dt.length > 0;
    const dayP = dt.reduce((s, t) => s + t.pnl, 0);
    let cls = 'cal-cell';
    if (ds === today) cls += ' today';
    if (has) cls += ' has';
    if (ds === selDate) cls += ' sel';
    let inner = '<div class="dn">' + d + '</div>';
    dt.forEach(t => {
      const w = t.pnl > 0;
      inner += '<div class="pill ' + (w ? 'w' : 'l') + '"><span class="plbl">' + t.side + '</span><span class="ppnl">' + fmtD(t.pnl) + '</span></div>';
    });
    if (has) {
      inner += '<div class="day-total ' + (dayP >= 0 ? 'pos' : 'neg') + '">' + fmtD(dayP) + '</div>';
    }
    const oc = has ? ' onclick="selectDay(\\'' + ds + '\\')"' : '';
    html += '<div class="' + cls + '"' + oc + '>' + inner + '</div>';
  }
  const rem = (7 - ((pad + dim) % 7)) % 7;
  for (let i = 1; i <= rem; i++) html += '<div class="cal-cell om"><div class="dn">' + i + '</div></div>';
  g.innerHTML = html;
}

function selectDay(ds) {
  detailCharts.forEach(c => c.remove()); detailCharts = [];
  selDate = ds;
  renderCal();
  const sec = document.getElementById('detail');
  const dt = getFiltered().filter(t => t.date === ds);
  if (!dt.length) { sec.innerHTML = ''; return; }
  const dl = new Date(ds + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
  const dayP = dt.reduce((s, t) => s + t.pnl, 0);
  let html = '<div class="detail-date">' + dl + ' — ' + dt.length + ' Trade' + (dt.length > 1 ? 's' : '') + ' — <span class="' + (dayP >= 0 ? 'pos' : 'neg') + '">' + fmtD(dayP) + '</span></div>';

  dt.forEach((t, idx) => {
    const w = t.pnl > 0;
    const pc = w ? '#26a69a' : '#ef5350';
    const sideCls = t.side === 'BUY' ? 'buy' : 'short';
    const held = calcHeld(t);
    const notional = t.shares * t.entry_price;
    const notFmt = notional >= 1000000 ? '$' + (notional/1000000).toFixed(1) + 'M' : '$' + (notional/1000).toFixed(0) + 'K';

    html += '<div class="tblock">' +
    '<div class="tblock-hdr">' +
      '<span class="tbadge ' + sideCls + '">' + t.side + '</span>' +
      '<span style="color:#999;font-size:12px">' + curStrat + ' sizing</span>' +
      '<span class="tpnl" style="color:' + pc + '">' + fmtP(t.pnl_pct) + ' ' + fmtD(t.pnl) + '</span>' +
    '</div>' +
    '<div class="tmeta">' +
      '<div class="mc"><div class="ml">P&L</div><div class="mv ' + (w ? 'pos' : 'neg') + '" style="font-weight:700">' + fmtD(t.pnl) + '</div></div>' +
      '<div class="mc"><div class="ml">P&L %</div><div class="mv ' + (w ? 'pos' : 'neg') + '">' + fmtP(t.pnl_pct) + '</div></div>' +
      '<div class="mc"><div class="ml">Entry</div><div class="mv">$' + t.entry_price.toFixed(2) + '</div></div>' +
      '<div class="mc"><div class="ml">Exit</div><div class="mv">$' + t.exit_price.toFixed(2) + '</div></div>' +
      '<div class="mc"><div class="ml">Shares</div><div class="mv">' + t.shares.toLocaleString() + '</div></div>' +
      '<div class="mc"><div class="ml">Notional</div><div class="mv">' + notFmt + '</div></div>' +
      '<div class="mc"><div class="ml">Entry Time</div><div class="mv">' + fmtT12(t.entry_time) + '</div></div>' +
      '<div class="mc"><div class="ml">Exit Time</div><div class="mv">' + fmtT12(t.exit_time) + '</div></div>' +
      '<div class="mc"><div class="ml">Held</div><div class="mv">' + held + '</div></div>' +
      '<div class="mc"><div class="ml">Fees</div><div class="mv" style="color:#ef9a9a">$' + Math.abs(t.fees) + '</div></div>' +
    '</div>' +
    '<div class="tcharts">' +
      '<div class="tcbox">' +
        '<div class="tclbl">SPY 1-Min with VWAP + Entry/Exit</div>' +
        '<div class="tccont" id="spy-' + idx + '"></div>' +
        '<div class="tt-ov" id="spy-tt-' + idx + '"></div>' +
      '</div>' +
    '</div>' +
    '</div>';
  });

  sec.innerHTML = html;
  sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
  dt.forEach((t, idx) => loadCharts(t, idx));
}

function calcHeld(t) {
  if (!t.entry_time || !t.exit_time) return '-';
  const ep = t.entry_time.split(':').map(Number);
  const xp = t.exit_time.split(':').map(Number);
  const mins = (xp[0] * 60 + xp[1]) - (ep[0] * 60 + ep[1]);
  if (mins < 0) return '-';
  if (mins >= 60) return Math.floor(mins/60) + 'h ' + (mins%60) + 'm';
  return mins + 'm';
}

function switchStrat(name) {
  curStrat = name;
  document.getElementById('strat-sel').value = name;
  selDate = null;
  document.getElementById('detail').innerHTML = '';
  detailCharts.forEach(c => c.remove()); detailCharts = [];
  refresh();
}

// Charts
function tsToSec(ms) { return Math.floor(ms / 1000); }
function tsNY(sec) { return new Date(sec * 1000).toLocaleString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit', hour12: true }); }
function findNearest(data, ts) {
  if (!data.length) return null;
  let b = data[0].time, bd = Math.abs(b - ts);
  for (const d of data) { const diff = Math.abs(d.time - ts); if (diff < bd) { bd = diff; b = d.time; } }
  return b;
}

function makeChart(container, h) {
  return LightweightCharts.createChart(container, {
    width: container.clientWidth, height: h || 500,
    layout: { background: { color: '#0f1117' }, textColor: '#999', fontSize: 10 },
    grid: { vertLines: { color: 'rgba(255,255,255,0.03)' }, horzLines: { color: 'rgba(255,255,255,0.03)' } },
    timeScale: { borderColor: '#2a2e3d', timeVisible: true, secondsVisible: false, tickMarkFormatter: tsNY },
    rightPriceScale: { borderColor: '#2a2e3d' },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    localization: { timeFormatter: tsNY }
  });
}

function setupTT(chart, series, ttId) {
  const tt = document.getElementById(ttId);
  if (!tt) return;
  chart.subscribeCrosshairMove(p => {
    if (!p.time || !p.seriesData || !p.seriesData.get(series)) { tt.style.display = 'none'; return; }
    const d = p.seriesData.get(series);
    tt.style.display = 'block';
    const time = tsNY(p.time);
    if (d.open !== undefined) {
      tt.innerHTML = '<div style="color:#666;font-size:9px">' + time + '</div>' +
        '<div>O <span class="' + (d.close >= d.open ? 'pos' : 'neg') + '">' + d.open.toFixed(2) + '</span></div>' +
        '<div>H <span class="pos">' + d.high.toFixed(2) + '</span></div>' +
        '<div>L <span class="neg">' + d.low.toFixed(2) + '</span></div>' +
        '<div>C <span class="' + (d.close >= d.open ? 'pos' : 'neg') + '">' + d.close.toFixed(2) + '</span></div>';
    }
  });
}

async function fetchBars(ticker, dateStr) {
  const ck = ticker + '_' + dateStr;
  if (fcache[ck]) return fcache[ck];
  try {
    const url = 'https://api.polygon.io/v2/aggs/ticker/' + ticker + '/range/1/minute/' + dateStr + '/' + dateStr + '?adjusted=true&sort=asc&limit=50000&apiKey=' + PK;
    const r = await fetch(url);
    const j = await r.json();
    if (!j.results) { fcache[ck] = []; return []; }
    const bars = j.results.map(r => ({ t: r.t, o: r.o, h: r.h, l: r.l, c: r.c, v: r.v || 0 }));
    fcache[ck] = bars;
    return bars;
  } catch (e) { console.error('Fetch error:', ticker, e); fcache[ck] = []; return []; }
}

async function loadCharts(trade, idx) {
  const spyC = document.getElementById('spy-' + idx);
  if (!spyC) return;
  const bars = await fetchBars('SPY', trade.date);
  if (!bars.length) { spyC.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#444;font-size:12px">No data</div>'; return; }

  const chart = makeChart(spyC);
  detailCharts.push(chart);
  const candles = chart.addCandlestickSeries({ upColor: '#26a69a', downColor: '#ef5350', borderUpColor: '#26a69a', borderDownColor: '#ef5350', wickUpColor: '#26a69a', wickDownColor: '#ef5350' });
  const cdata = bars.map(b => ({ time: tsToSec(b.t), open: b.o, high: b.h, low: b.l, close: b.c }));
  candles.setData(cdata);

  // Volume
  const vol = chart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'vol' });
  chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
  vol.setData(bars.map(b => ({ time: tsToSec(b.t), value: b.v, color: b.c >= b.o ? 'rgba(38,166,154,0.25)' : 'rgba(239,83,80,0.25)' })));

  // VWAP
  let cumTPV = 0, cumV = 0;
  const vwap = bars.map(b => { const tp = (b.h + b.l + b.c) / 3; cumTPV += tp * b.v; cumV += b.v; return { time: tsToSec(b.t), value: cumV > 0 ? cumTPV / cumV : b.c }; });
  const vwapS = chart.addLineSeries({ color: '#ff9800', lineWidth: 2, lastValueVisible: false, priceLineVisible: false });
  vwapS.setData(vwap);

  chart.priceScale('right').applyOptions({ autoScale: true, scaleMargins: { top: 0.05, bottom: 0.15 } });

  // Entry/exit dots — match by converting bar UTC timestamps to Eastern HH:MM (handles DST correctly)
  function barToEasternHHMM(epochSec) {
    return new Date(epochSec * 1000).toLocaleString('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false });
  }
  function findBarByTime(cdata, hhmm) {
    for (const bar of cdata) {
      if (barToEasternHHMM(bar.time) === hhmm) return bar.time;
    }
    return findNearest(cdata, cdata[0] ? cdata[0].time : 0);
  }
  const ct1 = findBarByTime(cdata, trade.entry_time);
  const ct2 = findBarByTime(cdata, trade.exit_time);

  // Entry dot (blue)
  if (ct1) {
    const entrySeries = chart.addLineSeries({
      color: 'rgba(0,0,0,0)', lineWidth: 0, lastValueVisible: false, priceLineVisible: false,
      pointMarkersVisible: true, pointMarkersRadius: 6,
    });
    entrySeries.setData([{ time: ct1, value: trade.entry_price }]);
    entrySeries.applyOptions({ color: '#2962ff' });
    // Label via marker on candle series
    candles.setMarkers([
      ...(ct1 ? [{ time: ct1, position: 'aboveBar', color: '#2962ff', shape: 'arrowDown', text: 'ENTRY $' + trade.entry_price.toFixed(2) }] : []),
      ...(ct2 ? [{ time: ct2, position: 'belowBar', color: trade.pnl >= 0 ? '#26a69a' : '#ef5350', shape: 'arrowUp', text: 'EXIT $' + trade.exit_price.toFixed(2) }] : []),
    ].sort((a, b) => a.time - b.time));
  }

  // Exit dot (green/red)
  if (ct2) {
    const exitSeries = chart.addLineSeries({
      color: 'rgba(0,0,0,0)', lineWidth: 0, lastValueVisible: false, priceLineVisible: false,
      pointMarkersVisible: true, pointMarkersRadius: 6,
    });
    exitSeries.setData([{ time: ct2, value: trade.exit_price }]);
    exitSeries.applyOptions({ color: trade.pnl >= 0 ? '#26a69a' : '#ef5350' });
  }

  setupTT(chart, candles, 'spy-tt-' + idx);
  chart.timeScale().fitContent();
  new ResizeObserver(() => chart.applyOptions({ width: spyC.clientWidth })).observe(spyC);
}

// Strategy comparison table
function renderStratPanel() {
  const sec = document.getElementById('strat-panel');
  const order = ['V16','Champion','Grade10','RangeOnly','V9','V16b'];
  let rows = '';
  order.forEach((name, i) => {
    const m = STRAT_META[name];
    const active = name === curStrat ? ' active' : '';
    const rank = i < 3 ? '<span class="rank-badge rank-' + (i+1) + '">' + (i+1) + '</span>' : '<span style="display:inline-block;width:26px"></span>';
    const shClass = m.sharpe >= 1.5 ? 'pos' : m.sharpe >= 0.8 ? '' : 'neg';
    rows += '<tr class="' + active + '" onclick="switchStrat(\\'' + name + '\\')">' +
      '<td>' + rank + name + '</td>' +
      '<td class="num">' + m.n + '</td>' +
      '<td class="num ' + (m.wr > 50 ? 'pos' : 'neg') + '">' + m.wr.toFixed(1) + '%</td>' +
      '<td class="num ' + (m.avg >= 0 ? 'pos' : 'neg') + '">' + fmtD(m.avg) + '</td>' +
      '<td class="num ' + (m.total >= 0 ? 'pos' : 'neg') + '">' + fmtD(m.total) + '</td>' +
      '<td class="num ' + shClass + '">' + m.sharpe.toFixed(3) + '</td>' +
      '<td class="num ' + (m.pf >= 1.5 ? 'pos' : m.pf >= 1 ? '' : 'neg') + '">' + m.pf.toFixed(2) + '</td>' +
      '<td class="num neg">-$' + (m.max_dd/1000).toFixed(0) + 'K</td>' +
    '</tr>';
  });

  sec.innerHTML = '<div style="border-top:1px solid #2a2e3d;padding-top:16px;margin-top:8px">' +
    '<h3 style="color:#e0e0e0;font-size:14px;margin-bottom:4px">Strategy Comparison <span style="color:#555;font-size:11px;font-weight:400">(click row to switch)</span></h3>' +
    '<table class="strat-tbl">' +
      '<tr><th>Strategy</th><th class="num">Trades</th><th class="num">Win Rate</th><th class="num">Avg P&L</th><th class="num">Total P&L</th><th class="num">Sharpe</th><th class="num">PF</th><th class="num">Max DD</th></tr>' +
      rows +
    '</table></div>';
}

// NAV & FILTERS
document.getElementById('prev-m').onclick = () => {
  curMonth = new Date(curMonth.getFullYear(), curMonth.getMonth() - 1, 1);
  selDate = null; document.getElementById('detail').innerHTML = '';
  detailCharts.forEach(c => c.remove()); detailCharts = [];
  refresh();
};
document.getElementById('next-m').onclick = () => {
  curMonth = new Date(curMonth.getFullYear(), curMonth.getMonth() + 1, 1);
  selDate = null; document.getElementById('detail').innerHTML = '';
  detailCharts.forEach(c => c.remove()); detailCharts = [];
  refresh();
};
document.querySelectorAll('.fbtn').forEach(b => b.onclick = () => {
  document.querySelectorAll('.fbtn').forEach(x => x.classList.remove('on'));
  b.classList.add('on');
  filter = b.dataset.f;
  selDate = null; document.getElementById('detail').innerHTML = '';
  detailCharts.forEach(c => c.remove()); detailCharts = [];
  refresh();
});
document.getElementById('strat-sel').onchange = (e) => { switchStrat(e.target.value); };

function refresh() { updateStats(); renderEquity(); renderCal(); renderStratPanel(); }

// INIT
(function init() {
  const t = trades();
  if (t.length) {
    const lastDate = t[t.length - 1].date;
    const d = new Date(lastDate + 'T12:00:00');
    curMonth = new Date(d.getFullYear(), d.getMonth(), 1);
  }
  refresh();
})();
</script>
</body>
</html>"""

out_path = os.path.join(BASE, 'kite_dashboard.html')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"\nDashboard written to {out_path} ({len(html):,} bytes)")
