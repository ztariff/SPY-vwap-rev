import { useState } from "react";

const edges = [
  {
    id: 1, ticker: "SPY", type: "Bull Put", direction: "Below", atr: "0.5x",
    strategy: "0.30/0.20δ · Scalp 25% · 2.0x stop · 15min",
    sharpe: 0.37, winRate: 83.4, expectancy: 0.61, profitFactor: 4.75, nTrades: 148, avgCredit: "$0.10",
    wfTrain: 0.046, wfTest: 0.277, slipTol: "3bps", vixFilter: "Avoid <15",
    robustness: "43% configs profitable", verdict: "promoted",
  },
  {
    id: 2, ticker: "SPY", type: "Bull Put", direction: "Below", atr: "0.6x",
    strategy: "0.20/0.10δ · Scalp 25% · 1.5x stop · 30min",
    sharpe: 0.53, winRate: 83.0, expectancy: 0.50, profitFactor: 13.0, nTrades: 62, avgCredit: "$0.07",
    wfTrain: 0.149, wfTest: 0.309, slipTol: "3bps", vixFilter: "Normal+ (≥15)",
    robustness: "4/5 alts pass WF", verdict: "promoted",
  },
  {
    id: 3, ticker: "SPY", type: "Bull Put", direction: "Below", atr: "0.7x",
    strategy: "0.20/0.10δ · Tgt 50% · 2.0x stop · EOD",
    sharpe: 0.53, winRate: 83.0, expectancy: 0.50, profitFactor: 13.0, nTrades: 41, avgCredit: "$0.06",
    wfTrain: 0.232, wfTest: 0.232, slipTol: "2bps", vixFilter: "Normal+ (≥15)",
    robustness: "4/5 alts pass WF", verdict: "promoted",
  },
  {
    id: 4, ticker: "SPY", type: "Bear Call", direction: "Above", atr: "0.5–0.7x",
    strategy: "0.25/0.15δ · Scalp 25% · 3.0x stop · 60min",
    sharpe: 0.45, winRate: 90.7, expectancy: 0.92, profitFactor: 16.3, nTrades: 20, avgCredit: "$0.11",
    wfTrain: 0.322, wfTest: 0.254, slipTol: "5bps", vixFilter: "VIX ≥ 20 ONLY",
    robustness: "Stable across 0.5–0.7x", verdict: "promoted",
  },
  {
    id: 5, ticker: "QQQ", type: "Bear Call", direction: "Above", atr: "0.5x",
    strategy: "0.25/0.10δ · Full credit · 2.0x stop · EOD",
    sharpe: 0.33, winRate: 71.1, expectancy: 2.43, profitFactor: 3.63, nTrades: 45, avgCredit: "$0.13",
    wfTrain: 0.296, wfTest: 0.378, slipTol: "5bps", vixFilter: "VIX ≥ 25 ONLY",
    robustness: "49% configs profitable, narrow spreads only", verdict: "conditional",
  },
  {
    id: 6, ticker: "QQQ", type: "Stock Long", direction: "Below", atr: "0.6x",
    strategy: "Long QQQ · 1% stop · 0.75% tgt · 15min",
    sharpe: 5.31, winRate: 66.7, expectancy: 9.7, profitFactor: 2.46, nTrades: 108, avgCredit: "—",
    wfTrain: 0.198, wfTest: 0.498, slipTol: "3bps", vixFilter: "All regimes",
    robustness: "Cross-validated: DIA ✓ IWM ✓", verdict: "promoted",
  },
  {
    id: 7, ticker: "SPY", type: "Bull Put", direction: "Below", atr: "0.8–0.9x",
    strategy: "0.20/0.10δ · Scalp 25% · 1.0x stop · 15–30min",
    sharpe: 0.74, winRate: 96.6, expectancy: 0.70, profitFactor: 30.99, nTrades: 23, avgCredit: "$0.09",
    wfTrain: -0.485, wfTest: 0.361, slipTol: "—", vixFilter: "—",
    robustness: "Train negative → overfit", verdict: "demoted",
  },
  {
    id: 8, ticker: "SPY", type: "Stock Long", direction: "Below", atr: "0.9x",
    strategy: "Long SPY · 0.25% stop · 1.5% tgt · EOD",
    sharpe: 5.15, winRate: 37.0, expectancy: 21.6, profitFactor: 2.45, nTrades: 27, avgCredit: "—",
    wfTrain: null, wfTest: null, slipTol: "—", vixFilter: "—",
    robustness: "Use QQQ 0.6x instead", verdict: "demoted",
  },
  {
    id: 9, ticker: "QQQ", type: "Bear Call", direction: "Above", atr: "0.7x",
    strategy: "0.30/0.20δ · Scalp 25% · 1.5x stop · 5min",
    sharpe: 0.40, winRate: 65.2, expectancy: 1.31, profitFactor: 3.66, nTrades: 23, avgCredit: "$0.18",
    wfTrain: -0.227, wfTest: 0.421, slipTol: "—", vixFilter: "—",
    robustness: "Train negative → spurious", verdict: "killed",
  },
  {
    id: 10, ticker: "QQQ", type: "Bull Put", direction: "Below", atr: "0.5x",
    strategy: "0.25/0.10δ · 90% credit · 3.0x stop · EOD",
    sharpe: 0.18, winRate: 79.5, expectancy: 0.81, profitFactor: 1.83, nTrades: 127, avgCredit: "$0.09",
    wfTrain: null, wfTest: null, slipTol: "—", vixFilter: "—",
    robustness: "SPY dominates this trade", verdict: "killed",
  },
  {
    id: 11, ticker: "QQQ", type: "Stock Short", direction: "Above", atr: "0.7x",
    strategy: "Short QQQ · 0.5% stop · 2.0% tgt · EOD",
    sharpe: 3.36, winRate: 47.2, expectancy: 15.8, profitFactor: 1.75, nTrades: 36, avgCredit: "—",
    wfTrain: null, wfTest: null, slipTol: "—", vixFilter: "—",
    robustness: "Cross-instrument FAILS: IWM ✗ DIA ✗ SPY ext ✗", verdict: "killed",
  },
];

const verdictConfig = {
  promoted:    { bg: "rgb(6,78,59)",    border: "rgb(16,185,129)", text: "rgb(52,211,153)", label: "PROMOTED", icon: "▲" },
  conditional: { bg: "rgb(30,64,45)",   border: "rgb(74,222,128)", text: "rgb(134,239,172)", label: "CONDITIONAL", icon: "△" },
  demoted:     { bg: "rgb(69,46,3)",    border: "rgb(245,158,11)", text: "rgb(251,191,36)", label: "DEMOTED", icon: "▽" },
  killed:      { bg: "rgb(69,10,10)",   border: "rgb(239,68,68)",  text: "rgb(248,113,113)", label: "KILLED", icon: "✕" },
};

const MetricBar = ({ value, max, color }) => (
  <div style={{ width: "100%", height: 6, background: "rgba(255,255,255,0.06)", borderRadius: 3 }}>
    <div style={{ width: `${Math.min((value / max) * 100, 100)}%`, height: 6, background: color, borderRadius: 3, transition: "width 0.4s" }} />
  </div>
);

export default function Dashboard() {
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("verdict");

  const order = { promoted: 0, conditional: 1, demoted: 2, killed: 3 };

  let items = filter === "all" ? [...edges] : edges.filter(e => e.verdict === filter);
  if (sort === "verdict") items.sort((a, b) => order[a.verdict] - order[b.verdict] || b.sharpe - a.sharpe);
  else if (sort === "sharpe") items.sort((a, b) => b.sharpe - a.sharpe);
  else if (sort === "trades") items.sort((a, b) => b.nTrades - a.nTrades);
  else if (sort === "winrate") items.sort((a, b) => b.winRate - a.winRate);

  const counts = { promoted: 0, conditional: 0, demoted: 0, killed: 0 };
  edges.forEach(e => counts[e.verdict]++);

  const btnStyle = (active) => ({
    padding: "4px 12px", borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: "pointer", border: "none",
    background: active ? "rgba(255,255,255,0.15)" : "transparent",
    color: active ? "#fff" : "rgba(255,255,255,0.4)",
    transition: "all 0.2s",
  });

  return (
    <div style={{ fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif", background: "#0a0a0f", color: "#fff", padding: 20, minHeight: "100vh" }}>

      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, letterSpacing: "-0.02em" }}>VWAP Deviation Strategy — Final Scorecard</h1>
        <p style={{ color: "rgba(255,255,255,0.4)", fontSize: 13, margin: "4px 0 0" }}>SPY + QQQ | 0DTE Options & Stock | Jan 2022 – Mar 2026 | All P&L from real Polygon trades</p>
      </div>

      {/* Summary Boxes */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 10, marginBottom: 20 }}>
        <div style={{ background: "rgba(255,255,255,0.05)", borderRadius: 10, padding: "12px 8px", textAlign: "center" }}>
          <div style={{ fontSize: 26, fontWeight: 700 }}>{edges.length}</div>
          <div style={{ fontSize: 11, color: "rgba(255,255,255,0.4)" }}>TOTAL EDGES</div>
        </div>
        {Object.entries(counts).map(([v, n]) => {
          const vc = verdictConfig[v];
          return (
            <div key={v} style={{ background: `${vc.bg}44`, border: `1px solid ${vc.border}55`, borderRadius: 10, padding: "12px 8px", textAlign: "center", cursor: "pointer" }} onClick={() => setFilter(filter === v ? "all" : v)}>
              <div style={{ fontSize: 26, fontWeight: 700, color: vc.text }}>{n}</div>
              <div style={{ fontSize: 11, color: "rgba(255,255,255,0.4)" }}>{vc.label}</div>
            </div>
          );
        })}
      </div>

      {/* Filters + Sort */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: 8, padding: 3, display: "flex", gap: 2 }}>
          {["all", "promoted", "conditional", "demoted", "killed"].map(v => (
            <button key={v} style={btnStyle(filter === v)} onClick={() => setFilter(v)}>
              {v === "all" ? "All" : verdictConfig[v]?.label || v}
            </button>
          ))}
        </div>
        <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: 8, padding: 3, display: "flex", gap: 2 }}>
          <span style={{ color: "rgba(255,255,255,0.3)", fontSize: 11, padding: "4px 6px" }}>Sort:</span>
          {[["verdict","Verdict"],["sharpe","Sharpe"],["trades","Trades"],["winrate","Win %"]].map(([k,l]) => (
            <button key={k} style={btnStyle(sort === k)} onClick={() => setSort(k)}>{l}</button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "separate", borderSpacing: "0 4px", fontSize: 13 }}>
          <thead>
            <tr style={{ color: "rgba(255,255,255,0.35)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              <th style={{ textAlign: "left", padding: "8px 10px", fontWeight: 600 }}>Edge</th>
              <th style={{ textAlign: "center", padding: "8px 6px", fontWeight: 600 }}>Verdict</th>
              <th style={{ textAlign: "right", padding: "8px 6px", fontWeight: 600 }}>Sharpe</th>
              <th style={{ textAlign: "right", padding: "8px 6px", fontWeight: 600 }}>Win %</th>
              <th style={{ textAlign: "right", padding: "8px 6px", fontWeight: 600 }}>Expect %</th>
              <th style={{ textAlign: "right", padding: "8px 6px", fontWeight: 600 }}>PF</th>
              <th style={{ textAlign: "right", padding: "8px 6px", fontWeight: 600 }}>N</th>
              <th style={{ textAlign: "center", padding: "8px 6px", fontWeight: 600 }}>WF Train</th>
              <th style={{ textAlign: "center", padding: "8px 6px", fontWeight: 600 }}>WF Test</th>
              <th style={{ textAlign: "center", padding: "8px 6px", fontWeight: 600 }}>Slip Tol</th>
              <th style={{ textAlign: "center", padding: "8px 6px", fontWeight: 600 }}>VIX Filter</th>
            </tr>
          </thead>
          <tbody>
            {items.map(e => {
              const vc = verdictConfig[e.verdict];
              return (
                <tr key={e.id} style={{ background: `${vc.bg}22`, borderRadius: 8 }}>
                  <td style={{ padding: "10px 10px", borderLeft: `3px solid ${vc.border}`, borderRadius: "8px 0 0 8px" }}>
                    <div style={{ fontWeight: 600, fontSize: 13 }}>
                      <span style={{ color: "rgb(96,165,250)", marginRight: 6 }}>{e.ticker}</span>
                      <span style={{ color: "rgba(255,255,255,0.8)" }}>{e.type}</span>
                      <span style={{ color: "rgba(255,255,255,0.3)", marginLeft: 6, fontSize: 11 }}>{e.direction} {e.atr}</span>
                    </div>
                    <div style={{ color: "rgba(255,255,255,0.35)", fontSize: 11, marginTop: 2, fontFamily: "monospace" }}>{e.strategy}</div>
                  </td>
                  <td style={{ textAlign: "center", padding: "10px 6px" }}>
                    <span style={{ color: vc.text, fontWeight: 700, fontSize: 12, padding: "2px 8px", borderRadius: 4, border: `1px solid ${vc.border}66`, background: `${vc.bg}66` }}>
                      {vc.icon} {vc.label}
                    </span>
                  </td>
                  <td style={{ textAlign: "right", padding: "10px 6px", fontFamily: "monospace" }}>
                    <div style={{ marginBottom: 3, fontWeight: 600, color: e.sharpe >= 0.4 ? "rgb(52,211,153)" : e.sharpe >= 0.2 ? "rgb(251,191,36)" : "rgb(248,113,113)" }}>{e.sharpe.toFixed(2)}</div>
                    <MetricBar value={e.sharpe} max={1.0} color={e.sharpe >= 0.4 ? "rgb(52,211,153)" : e.sharpe >= 0.2 ? "rgb(251,191,36)" : "rgb(248,113,113)"} />
                  </td>
                  <td style={{ textAlign: "right", padding: "10px 6px", fontFamily: "monospace" }}>
                    <div style={{ marginBottom: 3, fontWeight: 600, color: e.winRate >= 75 ? "rgb(52,211,153)" : "rgba(255,255,255,0.7)" }}>{e.winRate.toFixed(1)}%</div>
                    <MetricBar value={e.winRate} max={100} color={e.winRate >= 75 ? "rgb(52,211,153)" : "rgba(255,255,255,0.3)"} />
                  </td>
                  <td style={{ textAlign: "right", padding: "10px 6px", fontFamily: "monospace", fontWeight: 600, color: e.expectancy >= 1 ? "rgb(52,211,153)" : "rgba(255,255,255,0.7)" }}>
                    +{e.expectancy.toFixed(1)}%
                  </td>
                  <td style={{ textAlign: "right", padding: "10px 6px", fontFamily: "monospace", fontWeight: 600, color: e.profitFactor >= 3 ? "rgb(52,211,153)" : "rgba(255,255,255,0.7)" }}>
                    {e.profitFactor > 20 ? "20+" : e.profitFactor.toFixed(1)}
                  </td>
                  <td style={{ textAlign: "right", padding: "10px 6px" }}>
                    <span style={{ fontFamily: "monospace", fontWeight: 700, fontSize: 14, color: e.nTrades >= 50 ? "rgb(52,211,153)" : e.nTrades >= 20 ? "rgb(251,191,36)" : "rgb(248,113,113)" }}>{e.nTrades}</span>
                  </td>
                  <td style={{ textAlign: "center", padding: "10px 6px", fontFamily: "monospace", fontSize: 12 }}>
                    {e.wfTrain !== null ? (
                      <span style={{ color: e.wfTrain > 0 ? "rgb(134,239,172)" : "rgb(248,113,113)", fontWeight: 600 }}>{e.wfTrain.toFixed(3)}</span>
                    ) : <span style={{ color: "rgba(255,255,255,0.2)" }}>—</span>}
                  </td>
                  <td style={{ textAlign: "center", padding: "10px 6px", fontFamily: "monospace", fontSize: 12 }}>
                    {e.wfTest !== null ? (
                      <span style={{ color: e.wfTest > 0 ? "rgb(134,239,172)" : "rgb(248,113,113)", fontWeight: 600 }}>{e.wfTest.toFixed(3)}</span>
                    ) : <span style={{ color: "rgba(255,255,255,0.2)" }}>—</span>}
                  </td>
                  <td style={{ textAlign: "center", padding: "10px 6px", fontSize: 11, color: e.slipTol !== "—" ? "rgb(147,197,253)" : "rgba(255,255,255,0.2)" }}>
                    {e.slipTol}
                  </td>
                  <td style={{ textAlign: "center", padding: "10px 6px", fontSize: 11, borderRadius: "0 8px 8px 0" }}>
                    <span style={{ color: e.vixFilter.includes("ONLY") ? "rgb(251,191,36)" : e.vixFilter === "—" ? "rgba(255,255,255,0.2)" : "rgba(255,255,255,0.5)" }}>
                      {e.vixFilter}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Tradeable Summary */}
      <div style={{ marginTop: 20, background: "rgba(6,78,59,0.2)", border: "1px solid rgba(16,185,129,0.25)", borderRadius: 12, padding: 16 }}>
        <div style={{ color: "rgb(52,211,153)", fontWeight: 700, fontSize: 13, marginBottom: 10 }}>5 VALIDATED TRADEABLE EDGES</div>
        <div style={{ display: "grid", gap: 8, fontSize: 13 }}>
          {[
            { n: "1", name: "SPY Bull Put 0.5x", desc: "0.30/0.20δ, scalp 25%, N=148", note: "Best all-weather edge. Avoid VIX<15." },
            { n: "2", name: "SPY Bull Put 0.6–0.7x", desc: "0.20/0.10δ, scalp 25%, N=103", note: "Multiple configs pass WF. Commission sensitive." },
            { n: "3", name: "SPY Bear Call 0.5–0.7x", desc: "0.25/0.15δ, scalp 25%, N=20", note: "VIX ≥ 20 required. High win rate." },
            { n: "4", name: "QQQ Bear Call 0.5x", desc: "0.25/0.10δ, full credit, N=45", note: "VIX ≥ 25 required. Narrow spreads only." },
            { n: "5", name: "QQQ/DIA/IWM Long 0.6x", desc: "1% stop, 0.75% tgt, N=108", note: "Cross-validated across 3 instruments." },
          ].map(({ n, name, desc, note }) => (
            <div key={n} style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
              <span style={{ color: "rgb(52,211,153)", fontFamily: "monospace", fontWeight: 700, flexShrink: 0 }}>{n}.</span>
              <div>
                <span style={{ fontWeight: 600, color: "rgba(255,255,255,0.9)" }}>{name}</span>
                <span style={{ color: "rgba(255,255,255,0.4)", marginLeft: 8 }}>{desc}</span>
                <span style={{ color: "rgb(251,191,36)", marginLeft: 8, fontSize: 11 }}>{note}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Methodology Footer */}
      <div style={{ marginTop: 16, padding: 14, background: "rgba(255,255,255,0.02)", borderRadius: 10, fontSize: 11, color: "rgba(255,255,255,0.3)", lineHeight: 1.6 }}>
        <strong style={{ color: "rgba(255,255,255,0.5)" }}>Methodology:</strong> Exhaustive grid search over 4+ years of 1-min Polygon data. Walk-forward split: train pre-2024-07-01, test post. VIX regimes: Low (&lt;15), Normal (15-20), Elevated (20-25), High (25-35), Extreme (35+). Slippage tested 0-10bps round-trip. Sharpe = per-trade (not annualized) for stock, on-risk for spreads. No theoretical pricing — all option P&L from actual traded prices.
      </div>
    </div>
  );
}
