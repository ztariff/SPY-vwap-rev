"""
Report Generator v2
====================
Comprehensive HTML report for both directions + scale-in + ATR heatmap.
"""

import pandas as pd
import numpy as np
from datetime import datetime
import json
import os


def generate_report(stock_results, stock_best, put_results, put_best_per_delta,
                    put_best_overall, call_results, call_best_per_delta,
                    call_best_overall, regime_analyses, risk_recommendations,
                    signals_summary, output_dir="results",
                    # v2 additions
                    below_stock_results=None, below_stock_best=None,
                    below_options_results=None, below_options_best=None,
                    atr_scan_results=None, scalein_results=None,
                    direction_comparison=None):
    """Generate comprehensive HTML report."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    html = _build_html(
        stock_results, stock_best, put_results, put_best_per_delta,
        put_best_overall, call_results, call_best_per_delta,
        call_best_overall, regime_analyses, risk_recommendations,
        signals_summary, below_stock_results, below_stock_best,
        below_options_results, below_options_best,
        atr_scan_results, scalein_results, direction_comparison
    )

    report_path = os.path.join(output_dir, f"spy_vwap_report_{timestamp}.html")
    with open(report_path, "w") as f:
        f.write(html)

    # Save CSVs
    for direction, label in [("above", "above"), ("below", "below")]:
        if isinstance(stock_results, dict) and direction in stock_results:
            df = stock_results[direction]
            if not df.empty:
                df.to_csv(os.path.join(output_dir, f"stock_{label}_{timestamp}.csv"), index=False)
        elif isinstance(stock_results, pd.DataFrame) and not stock_results.empty and direction == "above":
            stock_results.to_csv(os.path.join(output_dir, f"stock_above_{timestamp}.csv"), index=False)

    if put_results is not None and not put_results.empty:
        put_results.to_csv(os.path.join(output_dir, f"puts_above_{timestamp}.csv"), index=False)
    if call_results is not None and not call_results.empty:
        call_results.to_csv(os.path.join(output_dir, f"calls_above_{timestamp}.csv"), index=False)

    if atr_scan_results:
        for direction, df in atr_scan_results.items():
            if not df.empty:
                df.to_csv(os.path.join(output_dir, f"atr_scan_{direction}_{timestamp}.csv"), index=False)

    if scalein_results:
        for direction, df in scalein_results.items():
            if not df.empty:
                df.to_csv(os.path.join(output_dir, f"scalein_{direction}_{timestamp}.csv"), index=False)

    for direction, analyses in (regime_analyses or {}).items():
        if isinstance(analyses, dict):
            for name, df in analyses.items():
                if isinstance(df, pd.DataFrame) and not df.empty:
                    df.to_csv(os.path.join(output_dir, f"regime_{direction}_{name}_{timestamp}.csv"), index=False)

    if risk_recommendations:
        with open(os.path.join(output_dir, f"risk_sizing_{timestamp}.json"), "w") as f:
            json.dump(risk_recommendations, f, indent=2, default=str)

    print(f"\n  Report saved to: {report_path}")
    return report_path


CSS = """
body { font-family: 'Segoe UI', system-ui, sans-serif; max-width: 1300px;
       margin: 0 auto; padding: 20px; background: #0d1117; color: #c9d1d9; }
h1 { color: #58a6ff; border-bottom: 2px solid #30363d; padding-bottom: 10px; }
h2 { color: #79c0ff; margin-top: 40px; border-bottom: 1px solid #21262d; padding-bottom: 8px; }
h3 { color: #d2a8ff; }
.summary-box { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
               padding: 20px; margin: 15px 0; }
.metric { display: inline-block; margin: 10px 20px 10px 0; }
.metric-label { font-size: 12px; color: #8b949e; text-transform: uppercase; }
.metric-value { font-size: 24px; font-weight: bold; }
.positive { color: #3fb950; }
.negative { color: #f85149; }
.neutral { color: #d29922; }
table { border-collapse: collapse; width: 100%; margin: 15px 0;
        font-size: 13px; background: #161b22; }
th { background: #21262d; color: #79c0ff; padding: 10px 8px;
     text-align: left; border: 1px solid #30363d; }
td { padding: 8px; border: 1px solid #30363d; }
tr:hover { background: #1c2128; }
.highlight-row { background: #1a2233 !important; border-left: 3px solid #58a6ff; }
.key-finding { background: #1a2233; border-left: 4px solid #58a6ff;
               padding: 15px; margin: 10px 0; border-radius: 0 8px 8px 0; }
.risk-badge { display: inline-block; padding: 3px 10px; border-radius: 12px;
              font-size: 12px; font-weight: bold; }
.risk-high { background: #3fb950; color: #0d1117; }
.risk-medium { background: #d29922; color: #0d1117; }
.risk-low { background: #f85149; color: #0d1117; }
.heatmap-cell { text-align: center; font-weight: bold; padding: 6px 10px; }
.tab-container { margin: 20px 0; }
.tab-btn { background: #21262d; color: #8b949e; border: 1px solid #30363d;
           padding: 10px 20px; cursor: pointer; font-size: 14px; margin-right: 4px; }
.tab-btn.active { background: #161b22; color: #58a6ff; border-bottom: 2px solid #58a6ff; }
.tab-content { display: none; }
.tab-content.active { display: block; }
code { background: #21262d; padding: 2px 6px; border-radius: 3px; font-size: 13px; }
.timestamp { color: #8b949e; font-size: 12px; }
.direction-above { border-left: 3px solid #f85149; padding-left: 10px; }
.direction-below { border-left: 3px solid #3fb950; padding-left: 10px; }
"""


def _build_html(stock_results, stock_best, put_results, put_best_per_delta,
                put_best_overall, call_results, call_best_per_delta,
                call_best_overall, regime_analyses, risk_recommendations,
                signals_summary, below_stock_results, below_stock_best,
                below_options_results, below_options_best,
                atr_scan_results, scalein_results, direction_comparison):

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>SPY VWAP Strategy Report</title>
<style>{CSS}</style></head><body>
<h1>SPY VWAP Deviation Strategy — Full Optimization Report (v2)</h1>
<p class="timestamp">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
<p>Tests <strong>both directions</strong>: fading above VWAP AND buying below VWAP,
with fine-grained ATR thresholds (0.5x-2.0x) and scale-in analysis.</p>
"""

    # ─── ATR Level Heatmap ───────────────────────────────────────────
    if atr_scan_results:
        html += "<h2>ATR Threshold Scan (Entry Level Optimization)</h2>"
        html += "<p>Quick scan across all ATR multipliers using default exit (0.75% stop, 0.50% target, EOD). "
        html += "Shows which entry threshold gives the best edge for each direction.</p>"

        for direction in ["above", "below"]:
            if direction not in atr_scan_results:
                continue
            df = atr_scan_results[direction]
            if df.empty:
                continue
            dir_label = "ABOVE VWAP → SHORT (Fade)" if direction == "above" else "BELOW VWAP → LONG (Buy Dip)"
            div_class = "direction-above" if direction == "above" else "direction-below"
            html += f'<div class="{div_class}"><h3>{dir_label}</h3>'
            html += "<table><tr><th>ATR Mult</th><th>N Signals</th><th>Win Rate</th>"
            html += "<th>Avg P&L</th><th>Total P&L</th></tr>"

            best_pnl = df["avg_pnl"].max()
            for _, row in df.sort_values("atr_mult").iterrows():
                hl = ' class="highlight-row"' if row["avg_pnl"] == best_pnl else ""
                pnl_cls = "positive" if row["avg_pnl"] > 0 else "negative"
                html += f'<tr{hl}><td><strong>{row["atr_mult"]:.1f}x</strong></td>'
                html += f'<td>{row["n_signals"]}</td>'
                html += f'<td>{row["win_rate"]:.1f}%</td>'
                html += f'<td class="{pnl_cls}">{row["avg_pnl"]:+.4f}%</td>'
                html += f'<td class="{pnl_cls}">{row["total_pnl"]:+.2f}%</td></tr>'
            html += "</table></div>"

    # ─── Direction Comparison ────────────────────────────────────────
    if direction_comparison is not None and not direction_comparison.empty:
        html += "<h2>Direction Comparison: Above vs Below VWAP</h2>"
        html += _df_to_html_table(direction_comparison, "Performance by Direction & Regime")

    # ─── Stock Results: ABOVE ────────────────────────────────────────
    html += '<h2 class="direction-above">ABOVE VWAP — Short Stock (Fade)</h2>'
    above_results = stock_results.get("above") if isinstance(stock_results, dict) else stock_results
    above_best = stock_best.get("above") if isinstance(stock_best, dict) else stock_best
    html += _render_stock_section(above_results, above_best)

    # ─── Stock Results: BELOW ────────────────────────────────────────
    if below_stock_results is not None and not below_stock_results.empty:
        html += '<h2 class="direction-below">BELOW VWAP — Long Stock (Buy Dip)</h2>'
        html += _render_stock_section(below_stock_results, below_stock_best)

    # ─── Scale-In Results ────────────────────────────────────────────
    if scalein_results:
        html += "<h2>Scale-In Analysis</h2>"
        html += "<p>Tested entering at one ATR level and adding to the position at a higher level. "
        html += "50/50 allocation between the two entries.</p>"
        for direction in ["above", "below"]:
            if direction not in scalein_results:
                continue
            df = scalein_results[direction]
            if df.empty:
                continue
            dir_label = "ABOVE (Short)" if direction == "above" else "BELOW (Long)"
            div_class = "direction-above" if direction == "above" else "direction-below"
            html += f'<div class="{div_class}">'
            html += _df_to_html_table(df.head(20),
                f"{dir_label} — Top 20 Scale-In Combos (by expectancy)", highlight_first=True)
            html += "</div>"

    # ─── Options: ABOVE ──────────────────────────────────────────────
    html += '<h2 class="direction-above">ABOVE VWAP — Options (Fade Products)</h2>'
    html += _render_options_section(put_results, put_best_per_delta, put_best_overall,
                                    "Long 0DTE Puts (buy puts to profit from reversal down)")
    html += _render_options_section(call_results, call_best_per_delta, call_best_overall,
                                    "Short 0DTE Calls (sell calls expecting decay/drop)")

    # ─── Options: BELOW ──────────────────────────────────────────────
    if below_options_results:
        html += '<h2 class="direction-below">BELOW VWAP — Options (Buy Dip Products)</h2>'
        for (dir_key, prod), res_df in below_options_results.items():
            if dir_key != "below" or res_df.empty:
                continue
            label = prod.replace("_", " ").title()
            best = below_options_best.get((dir_key, prod)) if below_options_best else None
            per_delta = pd.DataFrame()
            if best is not None:
                from backtest_options import get_best_options_params
                per_delta, _ = get_best_options_params(res_df)
            html += _render_options_section(res_df, per_delta, best, label)

    # ─── Regime Analysis ─────────────────────────────────────────────
    for direction in ["above", "below"]:
        if direction not in (regime_analyses or {}):
            continue
        analyses = regime_analyses[direction]
        dir_label = "ABOVE VWAP (Fade)" if direction == "above" else "BELOW VWAP (Buy Dip)"
        div_class = "direction-above" if direction == "above" else "direction-below"
        html += f'<h2 class="{div_class}">Regime Analysis — {dir_label}</h2>'
        for name, df in analyses.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                html += _df_to_html_table(df, name.replace("_", " ").title())

    # ─── Risk Sizing ─────────────────────────────────────────────────
    for direction in ["above", "below"]:
        if direction not in (risk_recommendations or {}) or not risk_recommendations[direction]:
            continue
        dir_label = "ABOVE" if direction == "above" else "BELOW"
        html += f"<h2>Risk Sizing — {dir_label}</h2>"
        html += _render_risk_table(risk_recommendations[direction])

    # ─── Methodology ─────────────────────────────────────────────────
    html += """
    <h2>Methodology</h2>
    <div class="summary-box">
        <ul>
            <li><strong>VWAP:</strong> Session VWAP reset at 9:30 ET, cumsum(TP×V)/cumsum(V) on 1-min bars.</li>
            <li><strong>ATR:</strong> 14-period Wilder's smoothed ATR (prior day's value used for signal day).</li>
            <li><strong>Entry:</strong> First bar where |close − VWAP| ≥ ATR × multiplier.</li>
            <li><strong>ATR Grid:</strong> 0.5x through 2.0x in 0.1 steps (16 levels).</li>
            <li><strong>Scale-In:</strong> Enter partial at level A, add at level B; 50/50 allocation; exits on averaged cost basis.</li>
            <li><strong>Options:</strong> ALL P&L from real Polygon market data. Zero Black-Scholes.</li>
            <li><strong>Delta Selection:</strong> Strike distance proxy only for selecting which contracts to pull. P&L is always real prices.</li>
            <li><strong>Both Directions:</strong> Above VWAP = fade (short), Below VWAP = buy (long). Identical framework, mirrored.</li>
        </ul>
    </div>
    """

    html += "</body></html>"
    return html


def _render_stock_section(results_df, best_params):
    """Render a stock results section."""
    html = ""
    if best_params is not None:
        b = best_params if isinstance(best_params, dict) else best_params
        pnl_class = "positive" if b.get("expectancy", 0) > 0 else "negative"
        html += f"""<div class="key-finding">
        <h3>Optimal Parameters</h3>
        <div class="metric"><div class="metric-label">Stop</div>
            <div class="metric-value">{b.get('stop_loss', 'N/A')}%</div></div>
        <div class="metric"><div class="metric-label">Target</div>
            <div class="metric-value">{b.get('target', 'N/A')}%</div></div>
        <div class="metric"><div class="metric-label">Trail</div>
            <div class="metric-value">{b.get('trailing_stop', 'None')}</div></div>
        <div class="metric"><div class="metric-label">Time Exit</div>
            <div class="metric-value">{b.get('time_exit', 'None')}</div></div>
        <br>
        <div class="metric"><div class="metric-label">Expectancy</div>
            <div class="metric-value {pnl_class}">{b.get('expectancy', 0):+.4f}%</div></div>
        <div class="metric"><div class="metric-label">Win Rate</div>
            <div class="metric-value">{b.get('win_rate', 0):.1f}%</div></div>
        <div class="metric"><div class="metric-label">Profit Factor</div>
            <div class="metric-value">{b.get('profit_factor', 0):.2f}</div></div>
        <div class="metric"><div class="metric-label">N</div>
            <div class="metric-value">{b.get('n_trades', 0)}</div></div>
        <div class="metric"><div class="metric-label">Avg Hold</div>
            <div class="metric-value">{b.get('avg_minutes_held', 0):.0f} min</div></div>
        </div>"""

    if results_df is not None and not results_df.empty:
        html += _df_to_html_table(results_df.head(25),
                                   "Top 25 Parameter Combos", highlight_first=True)
    return html


def _render_options_section(results_df, best_per_delta, best_overall, title):
    """Render an options results section."""
    html = f"<h3>{title}</h3>"
    if best_overall is not None:
        b = best_overall if isinstance(best_overall, dict) else best_overall
        pnl_class = "positive" if b.get("expectancy", 0) > 0 else "negative"
        html += f"""<div class="key-finding">
        <div class="metric"><div class="metric-label">Delta</div>
            <div class="metric-value">{b.get('delta', 'N/A')}</div></div>
        <div class="metric"><div class="metric-label">Target</div>
            <div class="metric-value">{b.get('profit_target', 'N/A')}x</div></div>
        <div class="metric"><div class="metric-label">Stop</div>
            <div class="metric-value">{b.get('stop_loss', 'N/A')}x</div></div>
        <div class="metric"><div class="metric-label">Time</div>
            <div class="metric-value">{b.get('time_exit', 'N/A')}</div></div>
        <br>
        <div class="metric"><div class="metric-label">Expectancy</div>
            <div class="metric-value {pnl_class}">{b.get('expectancy', 0):+.2f}%</div></div>
        <div class="metric"><div class="metric-label">Win Rate</div>
            <div class="metric-value">{b.get('win_rate', 0):.1f}%</div></div>
        <div class="metric"><div class="metric-label">Avg Premium</div>
            <div class="metric-value">${b.get('avg_entry_premium', 0):.2f}</div></div>
        <div class="metric"><div class="metric-label">N</div>
            <div class="metric-value">{b.get('n_trades', 0)}</div></div>
        </div>"""

    if best_per_delta is not None and isinstance(best_per_delta, pd.DataFrame) and not best_per_delta.empty:
        html += _df_to_html_table(best_per_delta, "Best Params Per Delta")

    if results_df is not None and not results_df.empty:
        html += _df_to_html_table(results_df.head(20), "Top 20 Combos", highlight_first=True)

    return html


def _render_risk_table(recommendations):
    """Render risk sizing recommendations table."""
    html = "<table><tr><th>Regime</th><th>Risk Mult</th><th>Avg P&L</th>"
    html += "<th>Win Rate</th><th>N</th><th>Confidence</th></tr>"
    for regime, info in sorted(recommendations.items(),
                                key=lambda x: x[1]["risk_multiplier"], reverse=True):
        conf = info["confidence"]
        badge = {"high": "risk-high", "medium": "risk-medium", "low": "risk-low"}[conf]
        pnl_cls = "positive" if info["avg_pnl"] > 0 else "negative"
        html += f'<tr><td>{regime}</td>'
        html += f'<td><strong>{info["risk_multiplier"]}x</strong></td>'
        html += f'<td class="{pnl_cls}">{info["avg_pnl"]:+.4f}%</td>'
        html += f'<td>{info["win_rate"]:.1f}%</td><td>{info["n_trades"]}</td>'
        html += f'<td><span class="risk-badge {badge}">{conf}</span></td></tr>'
    html += "</table>"
    return html


def _df_to_html_table(df, title, highlight_first=False):
    """Convert DataFrame to styled HTML table."""
    html = f"<h3>{title}</h3><table><tr>"
    exclude = ["exit_reasons"]
    cols = [c for c in df.columns if c not in exclude]
    for col in cols:
        html += f"<th>{col}</th>"
    html += "</tr>"
    for i, (_, row) in enumerate(df.iterrows()):
        rc = ' class="highlight-row"' if (i == 0 and highlight_first) else ""
        html += f"<tr{rc}>"
        for col in cols:
            val = row[col]
            cc = ""
            if isinstance(val, float):
                if any(k in col.lower() for k in ["pnl", "expectancy"]):
                    cc = ' class="positive"' if val > 0 else ' class="negative"' if val < 0 else ""
                val = f"{val:.4f}" if abs(val) < 1 else f"{val:.2f}"
            html += f"<td{cc}>{val}</td>"
        html += "</tr>"
    html += "</table>"
    return html
