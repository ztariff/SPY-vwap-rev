#!/usr/bin/env python3
"""Build SPY ALT calendar dashboard from KITE backtest trades."""

import json

# Load trade data
with open('C:/Users/n7add/SPX-Intra-Rev/spy_alt_trades_by_date.json') as f:
    trade_data = json.load(f)

trade_json = json.dumps(trade_data, separators=(',', ':'))

html = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>C-Shark | SPY ALT VWAP Mean Reversion Calendar</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #131722; color: #DDD; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }

/* Header */
#header {
    padding: 16px 24px;
    background: #1e2130;
    border-bottom: 1px solid #2a2e3d;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
#header h1 { font-size: 18px; font-weight: 600; color: #fff; }
#header .subtitle { font-size: 12px; color: #888; margin-top: 2px; }
#summary-bar {
    display: flex; gap: 24px; font-size: 13px;
}
#summary-bar .stat { text-align: right; }
#summary-bar .stat-val { font-size: 16px; font-weight: 600; }
#summary-bar .stat-label { font-size: 11px; color: #888; }
.up { color: #26a69a; }
.dn { color: #ef5350; }

/* Main layout */
#main { display: flex; height: calc(100vh - 70px); }
#calendar-panel {
    width: 100%;
    overflow-y: auto;
    padding: 16px 24px;
    transition: width 0.3s;
}
#calendar-panel.shrunk { width: 45%; }
#detail-panel {
    width: 0;
    overflow-y: auto;
    overflow-x: hidden;
    border-left: 1px solid #2a2e3d;
    background: #181c28;
    transition: width 0.3s;
}
#detail-panel.open { width: 55%; }

/* Month navigator */
.month-nav {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 0; margin-bottom: 12px;
}
.month-nav h2 { font-size: 18px; font-weight: 600; text-align: center; flex: 1; }
.nav-btn {
    background: #2a2e3d; border: 1px solid #3a3f52; color: #aaa;
    border-radius: 6px; width: 36px; height: 36px;
    font-size: 18px; cursor: pointer; display: flex;
    align-items: center; justify-content: center;
    transition: all 0.15s;
}
.nav-btn:hover { background: #363c52; color: #fff; }
.month-stats-bar {
    display: flex; justify-content: center; gap: 20px;
    font-size: 12px; color: #888; margin-bottom: 14px;
}
.month-stats-bar span { white-space: nowrap; }

/* Month grid */
.month-block { margin-bottom: 16px; }
.weekday-header {
    display: grid; grid-template-columns: repeat(7, 1fr);
    gap: 2px; margin-bottom: 2px;
}
.weekday-header span { text-align: center; font-size: 10px; color: #555; padding: 2px; }
.month-grid {
    display: grid; grid-template-columns: repeat(7, 1fr);
    gap: 2px;
}
.day-cell {
    aspect-ratio: 1.4;
    border-radius: 4px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    cursor: default;
    position: relative;
    min-height: 36px;
}
.day-cell.empty { background: transparent; }
.day-cell.no-trade { background: #1a1e2e; color: #444; }
.day-cell.has-trade { cursor: pointer; transition: all 0.15s; }
.day-cell.has-trade:hover { transform: scale(1.08); z-index: 2; box-shadow: 0 0 8px rgba(255,255,255,0.15); }
.day-cell.has-trade.selected { outline: 2px solid #2962ff; z-index: 3; }
.day-cell.win { background: rgba(38,166,154,0.25); color: #26a69a; }
.day-cell.loss { background: rgba(239,83,80,0.25); color: #ef5350; }
.day-cell.flat { background: rgba(150,150,150,0.15); color: #888; }
.day-num { font-size: 11px; font-weight: 600; }
.day-pnl { font-size: 9px; margin-top: 1px; }

/* Detail panel */
#detail-content { padding: 16px; }
.detail-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 16px;
}
.detail-header h3 { font-size: 16px; }
.close-btn {
    background: #2a2e3d; border: 1px solid #3a3f52; color: #aaa;
    border-radius: 4px; padding: 4px 12px; cursor: pointer; font-size: 12px;
}
.close-btn:hover { background: #363c52; color: #fff; }

/* Trade card */
.trade-card {
    background: #1e2130;
    border: 1px solid #2a2e3d;
    border-radius: 8px;
    margin-bottom: 16px;
    overflow: hidden;
}
.trade-card-header {
    display: flex; flex-wrap: wrap; gap: 12px;
    padding: 10px 14px;
    background: #252a3a;
    border-bottom: 1px solid #2a2e3d;
    align-items: center;
}
.trade-stat { text-align: center; }
.trade-stat .tv { font-size: 14px; font-weight: 600; }
.trade-stat .tl { font-size: 10px; color: #888; text-transform: uppercase; }
.trade-chart { width: 100%; height: 350px; position: relative; }
.trade-chart .ohlc-tip {
    position: absolute; top: 6px; left: 10px; z-index: 10;
    background: rgba(19,23,34,0.85); border: 1px solid #2a2e3d;
    border-radius: 4px; padding: 4px 8px; font-size: 11px;
    pointer-events: none; display: none; line-height: 1.6;
    backdrop-filter: blur(4px);
}
.ohlc-tip .tt-label { color: #888; }
.ohlc-tip .tt-up { color: #26a69a; }
.ohlc-tip .tt-dn { color: #ef5350; }
.ohlc-tip .tt-time { color: #888; font-size: 10px; }

/* Cumulative strip */
.cum-strip {
    margin: 8px 0 20px 0;
    padding: 10px 14px;
    background: #1e2130;
    border-radius: 6px;
    border: 1px solid #2a2e3d;
}
.cum-strip canvas { width: 100%; height: 60px; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: #131722; }
::-webkit-scrollbar-thumb { background: #2a2e3d; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #3a3f52; }
</style>
</head>
<body>

<div id="header">
    <div>
        <h1>C-Shark | SPY VWAP Mean Reversion</h1>
        <div class="subtitle">BUY 0.4% below VWAP | Target 0.75% | Stop 1.0% | 15-min exit | KITE Backtest 2022-2026</div>
    </div>
    <div id="summary-bar"></div>
</div>

<div id="main">
    <div id="calendar-panel"></div>
    <div id="detail-panel">
        <div id="detail-content"></div>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
<script>
const TRADE_DATA = __TRADE_JSON__;

const POLYGON_KEY = 'cBE5Kbq9yllt0Yj29mDQjBcIKfAYQlHF';
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const WEEKDAYS = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
let selectedDate = null;
let chartInstances = [];

function renderSummary() {
    const bar = document.getElementById('summary-bar');
    let totalPnl = 0, wins = 0, losses = 0, n = 0;
    for (const [date, info] of Object.entries(TRADE_DATA)) {
        totalPnl += info.total_pnl;
        n += info.n_trades;
        if (info.total_pnl > 0) wins++;
        else if (info.total_pnl < 0) losses++;
    }
    const wr = n > 0 ? (wins / Object.keys(TRADE_DATA).length * 100).toFixed(1) : '0';
    const cls = totalPnl >= 0 ? 'up' : 'dn';
    bar.innerHTML =
        '<div class="stat"><div class="stat-val">' + n + '</div><div class="stat-label">Trades</div></div>' +
        '<div class="stat"><div class="stat-val ' + cls + '">$' + totalPnl.toLocaleString(undefined,{maximumFractionDigits:0}) + '</div><div class="stat-label">Total P&L</div></div>' +
        '<div class="stat"><div class="stat-val">' + wr + '%</div><div class="stat-label">Win Rate</div></div>' +
        '<div class="stat"><div class="stat-val">' + wins + '</div><div class="stat-label">Wins</div></div>' +
        '<div class="stat"><div class="stat-val">' + losses + '</div><div class="stat-label">Losses</div></div>';
}

// Current month view state
var currentYear = 2022;
var currentMonth = 1;
var MIN_YEAR = 2022, MIN_MONTH = 1;
var MAX_YEAR = 2026, MAX_MONTH = 3;

function prevMonth() {
    currentMonth--;
    if (currentMonth < 1) { currentMonth = 12; currentYear--; }
    if (currentYear < MIN_YEAR || (currentYear === MIN_YEAR && currentMonth < MIN_MONTH)) {
        currentYear = MIN_YEAR; currentMonth = MIN_MONTH;
    }
    renderCalendar();
}

function nextMonth() {
    currentMonth++;
    if (currentMonth > 12) { currentMonth = 1; currentYear++; }
    if (currentYear > MAX_YEAR || (currentYear === MAX_YEAR && currentMonth > MAX_MONTH)) {
        currentYear = MAX_YEAR; currentMonth = MAX_MONTH;
    }
    renderCalendar();
}

function renderCalendar() {
    const panel = document.getElementById('calendar-panel');
    panel.innerHTML = '';

    var yr = currentYear;
    var m = currentMonth;

    // Gather month data
    var monthPnl = 0, monthN = 0, monthWins = 0;
    for (var dateKey in TRADE_DATA) {
        if (parseInt(dateKey.slice(0,4)) === yr && parseInt(dateKey.slice(5,7)) === m) {
            monthPnl += TRADE_DATA[dateKey].total_pnl;
            monthN += TRADE_DATA[dateKey].n_trades;
            if (TRADE_DATA[dateKey].total_pnl > 0) monthWins++;
        }
    }

    // Navigation bar
    var nav = document.createElement('div');
    nav.className = 'month-nav';
    var mCls = monthPnl >= 0 ? 'up' : 'dn';
    nav.innerHTML =
        '<button class="nav-btn" onclick="prevMonth()">&larr;</button>' +
        '<h2>' + MONTHS[m-1] + ' ' + yr + '</h2>' +
        '<button class="nav-btn" onclick="nextMonth()">&rarr;</button>';
    panel.appendChild(nav);

    // Month stats
    var statsBar = document.createElement('div');
    statsBar.className = 'month-stats-bar';
    var mWr = monthN > 0 ? (monthWins / monthN * 100).toFixed(0) : '0';
    statsBar.innerHTML =
        '<span>' + monthN + ' trades</span>' +
        '<span>' + mWr + '% WR</span>' +
        '<span class="' + mCls + '">$' + monthPnl.toLocaleString(undefined,{maximumFractionDigits:0}) + '</span>';
    panel.appendChild(statsBar);

    // Cumulative P&L sparkline for this month
    var monthDates = [];
    for (var dateKey in TRADE_DATA) {
        if (parseInt(dateKey.slice(0,4)) === yr && parseInt(dateKey.slice(5,7)) === m) {
            monthDates.push(dateKey);
        }
    }
    monthDates.sort();
    if (monthDates.length > 0) {
        var cumDiv = document.createElement('div');
        cumDiv.className = 'cum-strip';
        var canvas = document.createElement('canvas');
        canvas.height = 60;
        cumDiv.appendChild(canvas);
        panel.appendChild(cumDiv);
        requestAnimationFrame(function() {
            drawCumPnl(canvas, monthDates.map(function(d) { return TRADE_DATA[d].total_pnl; }));
        });
    }

    // Month grid
    var block = document.createElement('div');
    block.className = 'month-block';

    var wdh = document.createElement('div');
    wdh.className = 'weekday-header';
    ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].forEach(function(wd) {
        var s = document.createElement('span');
        s.textContent = wd;
        wdh.appendChild(s);
    });
    block.appendChild(wdh);

    var grid = document.createElement('div');
    grid.className = 'month-grid';
    var firstDay = new Date(yr, m - 1, 1);
    var startDow = firstDay.getDay();
    startDow = startDow === 0 ? 6 : startDow - 1;
    for (var i = 0; i < startDow; i++) {
        var empty = document.createElement('div');
        empty.className = 'day-cell empty';
        grid.appendChild(empty);
    }
    var daysInMonth = new Date(yr, m, 0).getDate();
    for (var d = 1; d <= daysInMonth; d++) {
        var dateStr = yr + '-' + String(m).padStart(2,'0') + '-' + String(d).padStart(2,'0');
        var cell = document.createElement('div');
        cell.className = 'day-cell';
        var info = TRADE_DATA[dateStr];
        if (info) {
            var pnl = info.total_pnl;
            if (pnl > 0) cell.classList.add('has-trade', 'win');
            else if (pnl < 0) cell.classList.add('has-trade', 'loss');
            else cell.classList.add('has-trade', 'flat');
            cell.innerHTML = '<span class="day-num">' + d + '</span><span class="day-pnl">$' + Math.round(pnl).toLocaleString() + '</span>';
            cell.dataset.date = dateStr;
            cell.addEventListener('click', (function(ds, c) { return function() { selectDay(ds, c); }; })(dateStr, cell));
            if (dateStr === selectedDate) cell.classList.add('selected');
        } else {
            cell.classList.add('no-trade');
            cell.innerHTML = '<span class="day-num">' + d + '</span>';
        }
        grid.appendChild(cell);
    }
    block.appendChild(grid);
    panel.appendChild(block);
}

function drawCumPnl(canvas, pnls) {
    const ctx = canvas.getContext('2d');
    canvas.width = canvas.offsetWidth * 2;
    canvas.height = 60 * 2;
    ctx.scale(2, 2);
    const w = canvas.offsetWidth;
    const h = 60;
    var cum = [], running = 0;
    for (var i = 0; i < pnls.length; i++) { running += pnls[i]; cum.push(running); }
    const maxV = Math.max.apply(null, cum.map(Math.abs).concat([1]));
    const midY = h / 2;
    ctx.beginPath();
    ctx.strokeStyle = cum[cum.length - 1] >= 0 ? '#26a69a' : '#ef5350';
    ctx.lineWidth = 1.5;
    for (var i = 0; i < cum.length; i++) {
        const x = (i / (cum.length - 1 || 1)) * w;
        const y = midY - (cum[i] / maxV) * (midY - 4);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.beginPath();
    ctx.strokeStyle = 'rgba(255,255,255,0.1)';
    ctx.lineWidth = 0.5;
    ctx.setLineDash([4, 4]);
    ctx.moveTo(0, midY);
    ctx.lineTo(w, midY);
    ctx.stroke();
    ctx.setLineDash([]);
}

function selectDay(dateStr, cell) {
    document.querySelectorAll('.day-cell.selected').forEach(function(c) { c.classList.remove('selected'); });
    if (selectedDate === dateStr) { selectedDate = null; closeDetail(); return; }
    selectedDate = dateStr;
    cell.classList.add('selected');
    document.getElementById('calendar-panel').classList.add('shrunk');
    document.getElementById('detail-panel').classList.add('open');
    renderDetail(dateStr);
}

function closeDetail() {
    selectedDate = null;
    document.querySelectorAll('.day-cell.selected').forEach(function(c) { c.classList.remove('selected'); });
    document.getElementById('calendar-panel').classList.remove('shrunk');
    document.getElementById('detail-panel').classList.remove('open');
    destroyCharts();
}

function destroyCharts() {
    for (var i = 0; i < chartInstances.length; i++) {
        try { chartInstances[i].remove(); } catch(e) {}
    }
    chartInstances = [];
}

function renderDetail(dateStr) {
    destroyCharts();
    const content = document.getElementById('detail-content');
    const info = TRADE_DATA[dateStr];
    if (!info) { content.innerHTML = '<p>No trade data.</p>'; return; }
    const d = new Date(dateStr + 'T12:00:00');
    const dayName = WEEKDAYS[d.getDay()];
    const pnlCls = info.total_pnl >= 0 ? 'up' : 'dn';
    var html = '<div class="detail-header"><h3>' + dayName + ', ' + dateStr +
        ' &nbsp; <span class="' + pnlCls + '">$' + info.total_pnl.toLocaleString(undefined,{maximumFractionDigits:2}) +
        '</span></h3><button class="close-btn" onclick="closeDetail()">Close</button></div>';

    for (var i = 0; i < info.trades.length; i++) {
        var t = info.trades[i];
        var tCls = t.pnl >= 0 ? 'up' : 'dn';
        var holdStr = t.hold_min < 60 ? t.hold_min.toFixed(1) + 'm' : (t.hold_min / 60).toFixed(1) + 'h';
        var entryTime = t.entry_time.slice(11);
        var exitTime = t.exit_time.slice(11);
        var pnlSign = t.pnl_pct >= 0 ? '+' : '';

        html += '<div class="trade-card">' +
            '<div class="trade-card-header">' +
            '<div class="trade-stat"><div class="tv ' + tCls + '">$' + t.pnl.toLocaleString(undefined,{maximumFractionDigits:2}) + '</div><div class="tl">P&L</div></div>' +
            '<div class="trade-stat"><div class="tv ' + tCls + '">' + pnlSign + t.pnl_pct.toFixed(3) + '%</div><div class="tl">Return</div></div>' +
            '<div class="trade-stat"><div class="tv">' + t.side + '</div><div class="tl">Side</div></div>' +
            '<div class="trade-stat"><div class="tv">$' + t.entry_price.toFixed(2) + '</div><div class="tl">Entry</div></div>' +
            '<div class="trade-stat"><div class="tv">$' + t.exit_price.toFixed(2) + '</div><div class="tl">Exit</div></div>' +
            '<div class="trade-stat"><div class="tv">' + t.shares.toLocaleString() + '</div><div class="tl">Shares</div></div>' +
            '<div class="trade-stat"><div class="tv">' + entryTime + '</div><div class="tl">Entry Time</div></div>' +
            '<div class="trade-stat"><div class="tv">' + exitTime + '</div><div class="tl">Exit Time</div></div>' +
            '<div class="trade-stat"><div class="tv">' + holdStr + '</div><div class="tl">Hold</div></div>' +
            '<div class="trade-stat"><div class="tv">$' + Math.round(t.notional).toLocaleString() + '</div><div class="tl">Notional</div></div>' +
            '<div class="trade-stat"><div class="tv">$' + t.fees.toFixed(2) + '</div><div class="tl">Fees</div></div>' +
            '</div>' +
            '<div class="trade-chart" id="chart-' + dateStr + '-' + i + '">' +
            '<div class="ohlc-tip" id="tip-' + dateStr + '-' + i + '"></div>' +
            '</div></div>';
    }
    content.innerHTML = html;
    document.getElementById('detail-panel').scrollTop = 0;
    for (var i = 0; i < info.trades.length; i++) {
        loadTradeChart(dateStr, i, info.trades[i]);
    }
}

async function loadTradeChart(dateStr, idx, trade) {
    var containerId = 'chart-' + dateStr + '-' + idx;
    var tipId = 'tip-' + dateStr + '-' + idx;
    var container = document.getElementById(containerId);
    if (!container) return;

    var url = 'https://api.polygon.io/v2/aggs/ticker/SPY/range/1/minute/' + dateStr + '/' + dateStr +
        '?adjusted=true&sort=asc&limit=1000&apiKey=' + POLYGON_KEY;

    var bars = [];
    try {
        var resp = await fetch(url);
        var json = await resp.json();
        if (json.results) {
            // Convert UTC timestamps to ET by applying offset
            // Determine if date is in EDT or EST
            var testDate = new Date(dateStr + 'T12:00:00Z');
            var jan = new Date(testDate.getFullYear(), 0, 1);
            var jul = new Date(testDate.getFullYear(), 6, 1);
            var stdOffset = Math.max(jan.getTimezoneOffset(), jul.getTimezoneOffset());
            // Check if this specific date is in DST
            var dateObj = new Date(dateStr + 'T12:00:00');
            var isDST = dateObj.getTimezoneOffset() < stdOffset;
            // If system timezone is not ET, use a fixed offset
            // ET = UTC-5 (EST) or UTC-4 (EDT)
            // We detect EDT: second Sunday in March to first Sunday in November
            var month = parseInt(dateStr.slice(5,7));
            var day = parseInt(dateStr.slice(8,10));
            var yr = parseInt(dateStr.slice(0,4));
            // Simple DST check for US Eastern
            var marchSecondSun = 14 - new Date(yr, 2, 1).getDay();
            var novFirstSun = 7 - new Date(yr, 10, 1).getDay();
            if (novFirstSun === 7) novFirstSun = 0;
            var isEDT = (month > 3 && month < 11) ||
                        (month === 3 && day >= marchSecondSun) ||
                        (month === 11 && day < novFirstSun);
            var etOffsetSec = isEDT ? -4 * 3600 : -5 * 3600;

            bars = json.results.map(function(r) {
                // Shift UTC timestamp to ET for display
                var utcSec = r.t / 1000;
                var etSec = utcSec + etOffsetSec;
                return { time: etSec, open: r.o, high: r.h, low: r.l, close: r.c, volume: r.v };
            });
        }
    } catch(e) {
        container.innerHTML = '<div style="padding:20px;color:#888">Chart data unavailable</div>';
        return;
    }
    if (!bars.length) {
        container.innerHTML = '<div style="padding:20px;color:#888">No bar data for this date</div>';
        return;
    }

    var chart = LightweightCharts.createChart(container, {
        width: container.offsetWidth,
        height: 350,
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        layout: { background: { color: '#1e2130' }, textColor: '#DDD' },
        localization: {
            timeFormatter: function(ts) {
                // Times are already shifted to ET, just read UTC hours/minutes
                var d = new Date(ts * 1000);
                var hh = String(d.getUTCHours()).padStart(2, '0');
                var mm = String(d.getUTCMinutes()).padStart(2, '0');
                return hh + ':' + mm + ' ET';
            },
        },
        timeScale: { borderColor: '#2a2e3d', timeVisible: true, secondsVisible: false },
        rightPriceScale: { borderColor: '#2a2e3d' },
        grid: {
            vertLines: { color: 'rgba(255,255,255,0.03)' },
            horzLines: { color: 'rgba(255,255,255,0.03)' },
        },
    });
    chartInstances.push(chart);

    var candleSeries = chart.addCandlestickSeries({
        upColor: '#26a69a', downColor: '#ef5350',
        borderUpColor: '#26a69a', borderDownColor: '#ef5350',
        wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    });
    candleSeries.setData(bars);

    // Entry/Exit timestamps - parse as ET, convert to same shifted basis as bars
    // Trade times are in ET. Convert to UTC then apply same ET shift.
    var entryParts = trade.entry_time.split(/[- :]/);
    var exitParts = trade.exit_time.split(/[- :]/);
    // Build ET timestamp: treat as UTC then subtract offset to get real UTC, then add offset back
    // Simpler: the bar times are UTC+etOffset. Trade times are ET.
    // So trade ET time as unix = Date.UTC(y,m-1,d,h,min,s) with ET hours directly
    var entryTs = Date.UTC(parseInt(entryParts[0]), parseInt(entryParts[1])-1, parseInt(entryParts[2]),
                           parseInt(entryParts[3]), parseInt(entryParts[4]), parseInt(entryParts[5]||0)) / 1000;
    var exitTs = Date.UTC(parseInt(exitParts[0]), parseInt(exitParts[1])-1, parseInt(exitParts[2]),
                          parseInt(exitParts[3]), parseInt(exitParts[4]), parseInt(exitParts[5]||0)) / 1000;

    // Find nearest bar timestamps
    var entryBar = bars.reduce(function(prev, curr) {
        return Math.abs(curr.time - entryTs) < Math.abs(prev.time - entryTs) ? curr : prev;
    });
    var exitBar = bars.reduce(function(prev, curr) {
        return Math.abs(curr.time - exitTs) < Math.abs(prev.time - exitTs) ? curr : prev;
    });

    var isWin = trade.pnl >= 0;
    var markers = [
        {
            time: entryBar.time,
            position: 'belowBar',
            color: '#2962ff',
            shape: 'arrowUp',
            text: 'BUY $' + trade.entry_price.toFixed(2),
        },
        {
            time: exitBar.time,
            position: 'aboveBar',
            color: isWin ? '#26a69a' : '#ef5350',
            shape: 'arrowDown',
            text: (isWin ? '+' : '') + '$' + trade.pnl.toLocaleString(undefined,{maximumFractionDigits:0}),
        },
    ];
    markers.sort(function(a, b) { return a.time - b.time; });
    candleSeries.setMarkers(markers);

    // VWAP line (approximation from bar data)
    // We compute cumulative VWAP from the bars
    var vwapData = [];
    var cumTPV = 0, cumV = 0;
    for (var bi = 0; bi < bars.length; bi++) {
        var b = bars[bi];
        var tp = (b.high + b.low + b.close) / 3;
        cumTPV += tp * b.volume;
        cumV += b.volume;
        if (cumV > 0) {
            vwapData.push({ time: b.time, value: cumTPV / cumV });
        }
    }
    var vwapSeries = chart.addLineSeries({
        color: 'rgba(255,152,0,0.6)',
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Solid,
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
        title: 'VWAP',
    });
    vwapSeries.setData(vwapData);

    // OHLC tooltip
    var tooltip = document.getElementById(tipId);
    chart.subscribeCrosshairMove(function(param) {
        if (!param || !param.time || !param.seriesData) {
            tooltip.style.display = 'none';
            return;
        }
        var candle = param.seriesData.get(candleSeries);
        var vwap = param.seriesData.get(vwapSeries);
        if (!candle) { tooltip.style.display = 'none'; return; }
        var isUp = candle.close >= candle.open;
        var cls = isUp ? 'tt-up' : 'tt-dn';
        var pf = function(v) { return v != null ? v.toFixed(2) : '-'; };
        var vf = function(v) { return v != null ? v.toLocaleString() : '-'; };
        var td = new Date(param.time * 1000);
        var timeStr = String(td.getUTCHours()).padStart(2,'0') + ':' + String(td.getUTCMinutes()).padStart(2,'0') + ' ET';
        tooltip.innerHTML =
            '<span class="tt-time">' + timeStr + '</span><br>' +
            '<span class="tt-label">O</span> <span class="' + cls + '">' + pf(candle.open) + '</span> ' +
            '<span class="tt-label">H</span> <span class="' + cls + '">' + pf(candle.high) + '</span> ' +
            '<span class="tt-label">L</span> <span class="' + cls + '">' + pf(candle.low) + '</span> ' +
            '<span class="tt-label">C</span> <span class="' + cls + '">' + pf(candle.close) + '</span> ' +
            (vwap ? ' <span class="tt-label">VWAP</span> <span style="color:#ff9800">' + pf(vwap.value) + '</span>' : '');
        tooltip.style.display = 'block';
    });

    chart.timeScale().fitContent();

    var ro = new ResizeObserver(function() {
        chart.applyOptions({ width: container.offsetWidth });
    });
    ro.observe(container);
}

document.addEventListener('DOMContentLoaded', function() {
    renderSummary();
    renderCalendar();
});
</script>
</body>
</html>'''

# Inject trade data
html = html.replace('__TRADE_JSON__', trade_json)

with open('C:/Users/n7add/SPX-Intra-Rev/spy_alt_calendar.html', 'w', encoding='utf-8') as f:
    f.write(html)

print(f"Dashboard written: {len(html):,} bytes")
print("File: C:/Users/n7add/SPX-Intra-Rev/spy_alt_calendar.html")
