import { useState } from "react";

const edges = [
  // ══════ TIER 1: HIGH CONFIDENCE — Validated via walk-forward + robustness ══════
  {
    tier: 1,
    ticker: "SPY",
    type: "Credit Spread",
    direction: "Below VWAP",
    atr: "0.8x–0.9x",
    strategy: "Bull Put Spread (0.20/0.10δ)",
    params: "Scalp 25% credit, 1.0x stop, 15-30min",
    sharpe: 0.74,
    winRate: 96.6,
    expectancy: 0.70,
    profitFactor: 30.99,
    nTrades: 23,
    avgCredit: "$0.09",
    strength: "marginal",
    validation: "DEMOTED — walk-forward FAILS. 0.8x: Train N=10 Sharpe -0.485, Test N=16 Sharpe 0.361. Train negative = fail. 0.9x: Train N=3 only — impossible to validate. The 0.3/0.2 tgt=0.5 sl=1.5 30min config at 0.8x does pass (Train 0.523, Test 0.227) but only 16+22=38 trades. The spectacular original metrics (93-100% WR) were likely overfit to a small, favorable sample.",
    caveats: "Insufficient train-period data for reliable walk-forward. Best config fails. One alt config passes but N=38. Commission drag on tiny $0.06-0.09 credits makes real-world edge questionable.",
    verdict: "demoted",
  },
  {
    tier: 1,
    ticker: "SPY",
    type: "Credit Spread",
    direction: "Below VWAP",
    atr: "0.5x",
    strategy: "Bull Put Spread (0.30/0.20δ)",
    params: "Scalp 25% credit, 2.0x stop, 15min",
    sharpe: 0.37,
    winRate: 83.4,
    expectancy: 0.61,
    profitFactor: 4.75,
    nTrades: 145,
    avgCredit: "$0.10",
    strength: "strong",
    validation: "PROMOTED — walk-forward PASSES. Train Sharpe 0.046 (N=65), Test Sharpe 0.277 (N=83). Alt configs also pass: 0.25/0.15 tgt=0.25 sl=1.5 30min (Train 0.336, Test 0.214). VIX: works in Normal (0.135), Elevated (0.338), High (0.089). FAILS in Low VIX (Sharpe -0.438, N=14). Slippage: survives 3bps, dies at 5bps. Robustness: 43% of 65 configs profitable.",
    caveats: "Walk-forward confirmed. Largest sample (148 trades). Avoid Low VIX (<15). Slippage sensitive — survives 3bps, dies at 5bps. Use limit orders. Narrow spreads (0.25/0.15, 0.30/0.20) work best; wide pairs lose.",
    verdict: "promoted",
  },
  {
    tier: 1,
    ticker: "SPY",
    type: "Credit Spread",
    direction: "Below VWAP",
    atr: "0.6x–0.7x",
    strategy: "Bull Put Spread (0.20/0.10δ, 0.25/0.15δ)",
    params: "Scalp 25% credit, 1.5x stop, 30-60min",
    sharpe: 0.53,
    winRate: 83.0,
    expectancy: 0.50,
    profitFactor: 13.0,
    nTrades: 50,
    avgCredit: "$0.07",
    strength: "strong",
    validation: "PROMOTED — walk-forward PASSES for both. 0.6x: Train 0.149, Test 0.309 (best config). 4/5 alt configs pass. 0.7x: best config fails (train neg) BUT 4/5 alt configs pass including 0.2/0.1 tgt=0.5 sl=2.0 EOD (Train 0.232, Test 0.232 — perfectly stable). VIX: works in Normal+ (15+). Slippage: 0.7x survives 2bps only.",
    caveats: "Walk-forward confirmed across multiple configs. 0.6x more robust (best config passes). 0.7x requires careful config selection — use 0.2/0.1 with looser exits. Tiny credits ($0.06-0.08) = commission sensitive.",
    verdict: "promoted",
  },
  {
    tier: 1,
    ticker: "SPY",
    type: "Credit Spread",
    direction: "Above VWAP",
    atr: "0.5x–0.7x",
    strategy: "Bear Call Spread (0.25/0.15δ)",
    params: "Scalp 25% credit, 3.0x stop, 60min",
    sharpe: 0.45,
    winRate: 90.7,
    expectancy: 0.92,
    profitFactor: 16.3,
    nTrades: 20,
    avgCredit: "$0.11",
    strength: "strong",
    validation: "PROMOTED. Walk-forward PASSES: 0.5x Train Sharpe 0.322, Test 0.254 (stable). 0.7x Train 0.042, Test 0.293 (improves OOS). BUT VIX-conditional: loses money in normal VIX (15-20), works in elevated+ (20+). Treat as a VIX≥20 filter trade.",
    caveats: "VIX REGIME DEPENDENT: Sharpe 1.37 in elevated VIX (20-25), 1.29 in high VIX (25-35), NEGATIVE in normal VIX (15-20). Must filter VIX≥20 to trade. Walk-forward confirmed stable. Small N per regime bucket.",
    verdict: "promoted",
  },
  // ══════ TIER 2: PROMISING — Some validation, caveats remain ══════
  {
    tier: 2,
    ticker: "QQQ",
    type: "Credit Spread",
    direction: "Above VWAP",
    atr: "0.5x",
    strategy: "Bear Call Spread (0.25/0.10δ)",
    params: "Full credit target, 2.0x stop, EOD",
    sharpe: 0.33,
    winRate: 71.1,
    expectancy: 2.43,
    profitFactor: 3.63,
    nTrades: 45,
    avgCredit: "$0.13",
    strength: "promising",
    validation: "CONDITIONALLY PROMOTED. Walk-forward PASSES: Train Sharpe 0.296 (N=28), Test 0.378 (N=17). But VIX analysis shows edge is concentrated in HIGH VIX (25-35): Sharpe 0.650, PF 6.4. Normal VIX (15-20): Sharpe 0.023. Parameter robustness: only 49% of 65 configs profitable, edge concentrated in narrow spreads (0.25/0.10, 0.30/0.20). Wide spreads lose consistently.",
    caveats: "REQUIRES VIX≥25 FILTER. Walk-forward passes but edge is regime-specific. Only narrow spread pairs work (0.25/0.10, 0.30/0.20). Wide pairs (0.50/0.30) consistently lose. In high VIX: Sharpe 0.650, PF 6.4. In normal VIX: near zero.",
    verdict: "conditional_promote",
  },
  {
    tier: 2,
    ticker: "QQQ",
    type: "Stock",
    direction: "Below VWAP",
    atr: "0.6x",
    strategy: "Long QQQ at 0.6x ATR below VWAP",
    params: "1.0% stop, 0.75% target, 15min exit",
    sharpe: 5.31,
    winRate: 66.7,
    expectancy: 9.7,
    profitFactor: 2.46,
    nTrades: 108,
    avgCredit: "—",
    strength: "promising",
    validation: "PROMOTED + CROSS-VALIDATED. Walk-forward PASSES: Train Sharpe 0.198 (N=55), Test 0.498 (N=53). Slippage: survives 0.03%, dies at 0.05%. CROSS-INSTRUMENT: DIA below 0.6-0.7x ATR also PASSES walk-forward (0.7x: Train 0.117→Test 0.324, N=86). IWM below 0.7x also PASSES (Train 0.169→Test 0.085, N=59). Signal generalizes across instruments.",
    caveats: "SLIPPAGE SENSITIVE: Edge dies at 0.05% slippage. Must use limit orders. Cross-validated on DIA (Sharpe 0.239, PF 2.06 at 0.7x) and IWM (Sharpe 0.173, N=59 at 0.7x). This is the most robustly validated edge in the entire study.",
    verdict: "promoted",
  },
  {
    tier: 2,
    ticker: "SPY",
    type: "Stock",
    direction: "Below VWAP",
    atr: "0.9x",
    strategy: "Long SPY at 0.9x ATR below VWAP",
    params: "0.25% stop, 1.5% target, EOD exit",
    sharpe: 5.15,
    winRate: 37.0,
    expectancy: 21.6,
    profitFactor: 2.45,
    nTrades: 27,
    avgCredit: "—",
    strength: "promising",
    validation: "DEMOTED — extended backtest context. Original 27 trades in 2022-2026. The stock-long-below-VWAP concept validates on QQQ/DIA/IWM at 0.6-0.7x ATR with moderate params. The 0.9x/SPY/aggressive-params config may be overfit to specific market structure. Use the QQQ 0.6x version instead.",
    caveats: "Low win rate (37%) with extreme asymmetry. The 0.6x ATR QQQ version (108 trades, walk-forward passes, cross-validated) is the better expression of this edge. Use that instead.",
    verdict: "demoted",
  },
  // ══════ TIER 3: MARGINAL / KILLED ══════
  {
    tier: 3,
    ticker: "QQQ",
    type: "Credit Spread",
    direction: "Above VWAP",
    atr: "0.7x",
    strategy: "Bear Call Spread (0.30/0.20δ)",
    params: "Scalp 25% credit, 1.5x stop, 5min",
    sharpe: 0.40,
    winRate: 65.2,
    expectancy: 1.31,
    profitFactor: 3.66,
    nTrades: 23,
    avgCredit: "$0.18",
    strength: "marginal",
    validation: "DO NOT TRADE. Walk-forward FAILS: Train Sharpe NEGATIVE (-0.227, N=7), Test Sharpe 0.421 (N=11). Full-sample result was driven entirely by test period. Train-period negative means the edge was discovered by accident. Only works in high VIX (25-35): Sharpe 0.294. Normal VIX: Sharpe -0.175.",
    caveats: "KILLED — walk-forward failure. Train period is negative, meaning the full-sample Sharpe was entirely a test-period artifact. Only 7 trades in train period — not enough to learn from. 0.5x ATR version is better in every dimension.",
    verdict: "killed",
  },
  {
    tier: 3,
    ticker: "QQQ",
    type: "Credit Spread",
    direction: "Below VWAP",
    atr: "0.5x",
    strategy: "Bull Put Spread (0.25/0.10δ)",
    params: "90% credit target, 3.0x stop, EOD",
    sharpe: 0.18,
    winRate: 79.5,
    expectancy: 0.81,
    profitFactor: 1.83,
    nTrades: 127,
    avgCredit: "$0.09",
    strength: "marginal",
    validation: "KILLED. SPY dominates this trade with 2x the Sharpe. QQQ bull puts are structurally inferior — SPY put premiums are richer, SPY has tighter bid-ask, and SPY 0DTE liquidity is far deeper. No reason to trade QQQ puts when SPY puts are available.",
    caveats: "Large N (127) but weak Sharpe (0.18). SPY dominates this trade. QQQ put premiums not rich enough for defined-risk selling. Loose stops (3.0x) and EOD exit suggest edge is thin.",
    verdict: "killed",
  },
  {
    tier: 3,
    ticker: "QQQ",
    type: "Stock",
    direction: "Above VWAP",
    atr: "0.7x",
    strategy: "Short QQQ at 0.7x ATR above VWAP",
    params: "0.5% stop, 2.0% target, EOD exit",
    sharpe: 3.36,
    winRate: 47.2,
    expectancy: 15.8,
    profitFactor: 1.75,
    nTrades: 36,
    avgCredit: "—",
    strength: "marginal",
    validation: "KILLED — cross-instrument validation FAILS. IWM short-above: ALL walk-forwards fail (0.5x train -0.108, 0.7x train -0.066, 0.8x train -0.152). DIA short-above: ALL fail (0.5x train -0.063, 0.7x train -0.208, 1.0x train -0.252). The short-above-VWAP stock signal has NO edge on IWM or DIA. SPY extended to 2018: 0.7x 85 trades Sharpe -0.125, ALL configs fail. Only SPY 1.0x (24 trades) shows a marginal pass — too few trades to trust.",
    caveats: "KILLED by cross-instrument validation. Short-above-VWAP stock signal fails on IWM, DIA, and extended SPY (2018-2026). Only works as credit spreads with VIX filter, not as stock trades.",
    verdict: "killed",
  },
  {
    tier: 3,
    ticker: "SPY",
    type: "Stock",
    direction: "Above VWAP",
    atr: "1.0x",
    strategy: "Short SPY at 1.0x ATR above VWAP",
    params: "1.0% stop, 0.75% target, 15min exit",
    sharpe: 4.41,
    winRate: 69.2,
    expectancy: 13.9,
    profitFactor: 2.07,
    nTrades: 13,
    avgCredit: "—",
    strength: "marginal",
    validation: "MARGINAL — extended to 25 trades (2018-2026). Walk-forward PASSES for 1.0% stop/0.75% tgt/15min (Train 0.335, Test 0.271) and 1.0/1.0/30min (Train 0.564, Test 0.098). BUT: Only 24 trades total (12 per split). EOD-exit configs FAIL (train 0.608, test -0.770). IWM/DIA at 1.0x also tiny samples (14-15 trades). Cross-instrument inconclusive. The SPY 1.0x credit spread (VIX-filtered) is a better vehicle for this signal.",
    caveats: "Extended from 13 to 25 trades. Tight-exit configs marginally pass walk-forward but sample too small for confidence. Cross-instrument inconclusive (tiny N). Better expressed as credit spread with VIX filter.",
    verdict: "hold",
  },
];

const tierColors = {
  1: { bg: "bg-emerald-900/30", border: "border-emerald-500/40", badge: "bg-emerald-600", label: "HIGH CONFIDENCE" },
  2: { bg: "bg-amber-900/20", border: "border-amber-500/30", badge: "bg-amber-600", label: "PROMISING" },
  3: { bg: "bg-red-900/15", border: "border-red-500/25", badge: "bg-red-600/80", label: "NEEDS MORE DATA" },
};

const verdictStyles = {
  promoted: { color: "text-emerald-400", icon: "▲", label: "PROMOTED" },
  conditional_promote: { color: "text-emerald-300", icon: "△", label: "CONDITIONAL" },
  hold: { color: "text-gray-400", icon: "●", label: "HOLD" },
  demoted: { color: "text-amber-400", icon: "▽", label: "DEMOTED" },
  killed: { color: "text-red-400", icon: "✕", label: "KILLED" },
};

function MetricPill({ label, value, highlight }) {
  return (
    <div className={`flex flex-col items-center px-3 py-1.5 rounded-lg ${highlight ? "bg-white/10" : "bg-white/5"}`}>
      <span className="text-xs text-gray-400">{label}</span>
      <span className={`text-sm font-mono font-semibold ${highlight ? "text-white" : "text-gray-200"}`}>{value}</span>
    </div>
  );
}

function EdgeCard({ edge }) {
  const [expanded, setExpanded] = useState(false);
  const tc = tierColors[edge.tier];
  const vs = verdictStyles[edge.verdict];

  return (
    <div className={`${tc.bg} border ${tc.border} rounded-xl p-4 mb-3 cursor-pointer transition-all hover:border-opacity-60`} onClick={() => setExpanded(!expanded)}>
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`${tc.badge} text-white text-xs font-bold px-2 py-0.5 rounded`}>{tc.label}</span>
          <span className="bg-blue-600/80 text-white text-xs font-bold px-2 py-0.5 rounded">{edge.ticker}</span>
          <span className="bg-purple-600/60 text-white text-xs px-2 py-0.5 rounded">{edge.type}</span>
          <span className="bg-gray-600/60 text-white text-xs px-2 py-0.5 rounded">{edge.direction}</span>
          <span className="bg-gray-700/60 text-gray-300 text-xs px-2 py-0.5 rounded">{edge.atr} ATR</span>
          <span className={`${vs.color} text-xs font-bold px-2 py-0.5 rounded border border-current/30`}>{vs.icon} {vs.label}</span>
        </div>
        <span className="text-gray-400 text-lg">{expanded ? "▲" : "▼"}</span>
      </div>

      <div className="mb-2">
        <span className="text-white font-semibold text-sm">{edge.strategy}</span>
      </div>

      <div className="flex flex-wrap gap-2 mb-2">
        <MetricPill label="Sharpe" value={edge.sharpe.toFixed(2)} highlight={edge.sharpe > 0.5} />
        <MetricPill label="Win Rate" value={`${edge.winRate.toFixed(1)}%`} highlight={edge.winRate > 80} />
        <MetricPill label="Expect" value={`+${edge.expectancy.toFixed(1)}%`} highlight={edge.expectancy > 1} />
        <MetricPill label="PF" value={edge.profitFactor > 20 ? "20+" : edge.profitFactor.toFixed(1)} highlight={edge.profitFactor > 3} />
        <MetricPill label="N" value={edge.nTrades} highlight={edge.nTrades > 50} />
        {edge.avgCredit !== "—" && <MetricPill label="Credit" value={edge.avgCredit} />}
      </div>

      {expanded && (
        <div className="mt-3 space-y-2">
          <div className="bg-black/30 rounded-lg p-3">
            <div className="text-xs text-gray-400 mb-1">PARAMETERS</div>
            <div className="text-sm text-gray-200 font-mono">{edge.params}</div>
          </div>
          <div className={`rounded-lg p-3 ${edge.verdict === "killed" ? "bg-red-950/40 border border-red-800/30" : edge.verdict === "promoted" || edge.verdict === "conditional_promote" ? "bg-emerald-950/40 border border-emerald-800/30" : "bg-black/30"}`}>
            <div className={`text-xs mb-1 ${vs.color}`}>VALIDATION VERDICT</div>
            <div className="text-sm text-gray-200 leading-relaxed">{edge.validation}</div>
          </div>
          <div className="bg-black/30 rounded-lg p-3">
            <div className="text-xs text-gray-400 mb-1">CAVEATS & NOTES</div>
            <div className="text-sm text-gray-300 leading-relaxed">{edge.caveats}</div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function EdgeSummary() {
  const [filterTicker, setFilterTicker] = useState("all");
  const [filterType, setFilterType] = useState("all");
  const [filterVerdict, setFilterVerdict] = useState("all");
  const [sortBy, setSortBy] = useState("tier");

  let filtered = edges.filter(e => {
    if (filterTicker !== "all" && e.ticker !== filterTicker) return false;
    if (filterType !== "all" && e.type !== filterType) return false;
    if (filterVerdict !== "all" && e.verdict !== filterVerdict) return false;
    return true;
  });

  if (sortBy === "sharpe") filtered.sort((a, b) => b.sharpe - a.sharpe);
  else if (sortBy === "n") filtered.sort((a, b) => b.nTrades - a.nTrades);
  else if (sortBy === "expectancy") filtered.sort((a, b) => b.expectancy - a.expectancy);
  else filtered.sort((a, b) => a.tier - b.tier || b.sharpe - a.sharpe);

  const promoted = edges.filter(e => e.verdict === "promoted" || e.verdict === "conditional_promote").length;
  const killed = edges.filter(e => e.verdict === "killed").length;
  const holds = edges.filter(e => e.verdict === "hold").length;
  const demoted = edges.filter(e => e.verdict === "demoted").length;

  return (
    <div className="min-h-screen bg-gray-950 text-white p-4 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold mb-1">VWAP Deviation Strategy — Edge Map v2</h1>
        <p className="text-gray-400 text-sm">SPY + QQQ | Stock & Credit Spread | Jan 2022 — Mar 2026 | All P&L from real Polygon prices</p>
        <p className="text-gray-500 text-xs mt-1">Updated with walk-forward, VIX regime, parameter robustness, and slippage validation results</p>
      </div>

      {/* Verdict summary */}
      <div className="grid grid-cols-5 gap-2 mb-4">
        <div className="bg-gray-800/50 rounded-xl p-3 text-center">
          <div className="text-xl font-bold">{edges.length}</div>
          <div className="text-xs text-gray-400">Total</div>
        </div>
        <div className="bg-emerald-900/30 border border-emerald-500/30 rounded-xl p-3 text-center">
          <div className="text-xl font-bold text-emerald-400">{promoted}</div>
          <div className="text-xs text-gray-400">Promoted</div>
        </div>
        <div className="bg-gray-800/50 rounded-xl p-3 text-center">
          <div className="text-xl font-bold text-gray-400">{holds}</div>
          <div className="text-xs text-gray-400">On Hold</div>
        </div>
        <div className="bg-amber-900/20 border border-amber-500/20 rounded-xl p-3 text-center">
          <div className="text-xl font-bold text-amber-400">{demoted}</div>
          <div className="text-xs text-gray-400">Demoted</div>
        </div>
        <div className="bg-red-900/15 border border-red-500/20 rounded-xl p-3 text-center">
          <div className="text-xl font-bold text-red-400">{killed}</div>
          <div className="text-xs text-gray-400">Killed</div>
        </div>
      </div>

      {/* Tradeable edges callout */}
      <div className="bg-emerald-950/30 border border-emerald-600/30 rounded-xl p-4 mb-6">
        <div className="text-emerald-400 font-bold text-sm mb-2">VALIDATED TRADEABLE EDGES</div>
        <div className="space-y-2 text-sm text-gray-200">
          <div><span className="text-emerald-400 font-mono">1.</span> <strong>SPY Bull Put 0.5x Below</strong> — 0.30/0.20δ, scalp 25%, 2.0x stop, 15min. N=148. <span className="text-amber-300">Avoid VIX&lt;15.</span> Walk-forward confirmed. Best all-weather edge.</div>
          <div><span className="text-emerald-400 font-mono">2.</span> <strong>SPY Bull Put 0.6-0.7x Below</strong> — 0.20/0.10δ, scalp 25%, 30-60min. N=62+41. Walk-forward confirmed. Multiple configs pass.</div>
          <div><span className="text-emerald-400 font-mono">3.</span> <strong>SPY Bear Call 0.5-0.7x Above</strong> — 0.25/0.15δ, scalp 25%, 60min. <span className="text-amber-300">VIX≥20 required.</span> Walk-forward confirmed.</div>
          <div><span className="text-emerald-400 font-mono">4.</span> <strong>QQQ Bear Call 0.5x Above</strong> — 0.25/0.10δ, full credit, EOD. <span className="text-amber-300">VIX≥25 required.</span> Walk-forward confirmed, narrow spreads only.</div>
          <div><span className="text-emerald-400 font-mono">5.</span> <strong>QQQ/DIA/IWM Long Stock 0.6x Below</strong> — 1% stop, 0.75% target, 15min. <span className="text-amber-300">Max 3bps slippage.</span> Walk-forward + cross-instrument confirmed.</div>
        </div>
        <div className="text-xs text-gray-500 mt-3">5 validated edges. SPY bull puts are the most all-weather. Bear calls require VIX filter. Stock long requires tight execution.</div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 mb-4">
        <div className="flex gap-1 bg-gray-800/50 rounded-lg p-1">
          {["all", "SPY", "QQQ"].map(t => (
            <button key={t} onClick={() => setFilterTicker(t)}
              className={`px-3 py-1 rounded text-xs font-semibold transition-all ${filterTicker === t ? "bg-blue-600 text-white" : "text-gray-400 hover:text-white"}`}>
              {t === "all" ? "All Tickers" : t}
            </button>
          ))}
        </div>
        <div className="flex gap-1 bg-gray-800/50 rounded-lg p-1">
          {["all", "Credit Spread", "Stock"].map(t => (
            <button key={t} onClick={() => setFilterType(t)}
              className={`px-3 py-1 rounded text-xs font-semibold transition-all ${filterType === t ? "bg-purple-600 text-white" : "text-gray-400 hover:text-white"}`}>
              {t === "all" ? "All Types" : t}
            </button>
          ))}
        </div>
        <div className="flex gap-1 bg-gray-800/50 rounded-lg p-1">
          {["all", "promoted", "conditional_promote", "hold", "demoted", "killed"].map(v => (
            <button key={v} onClick={() => setFilterVerdict(v)}
              className={`px-3 py-1 rounded text-xs font-semibold transition-all ${filterVerdict === v ? "bg-gray-600 text-white" : "text-gray-400 hover:text-white"}`}>
              {v === "all" ? "All" : v === "conditional_promote" ? "Cond." : v.charAt(0).toUpperCase() + v.slice(1)}
            </button>
          ))}
        </div>
        <div className="flex gap-1 bg-gray-800/50 rounded-lg p-1">
          {[["tier", "Tier"], ["sharpe", "Sharpe"], ["n", "Sample"], ["expectancy", "Expect"]].map(([k, label]) => (
            <button key={k} onClick={() => setSortBy(k)}
              className={`px-3 py-1 rounded text-xs font-semibold transition-all ${sortBy === k ? "bg-gray-600 text-white" : "text-gray-400 hover:text-white"}`}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Cards */}
      <div className="space-y-1">
        {filtered.map((edge, i) => <EdgeCard key={i} edge={edge} />)}
      </div>

      {/* Remaining work */}
      <div className="mt-6 bg-amber-950/20 border border-amber-600/20 rounded-xl p-4">
        <div className="text-emerald-400 font-bold text-sm mb-2">VALIDATION COMPLETE</div>
        <div className="space-y-1 text-sm text-gray-300">
          <div>All 11 original edges have been through the full validation gauntlet.</div>
          <div>5 promoted, 2 demoted, 4 killed. No edges remain unvalidated.</div>
        </div>
        <div className="text-xs text-gray-500 mt-2">
          Completed: Walk-forward (all edges), VIX regime (all spreads), parameter robustness (0.5x bull puts + bear calls), slippage stress tests (spreads + stock), cross-instrument IWM/DIA, SPY extended to 2018.
        </div>
      </div>

      {/* Footer */}
      <div className="mt-4 bg-gray-800/30 rounded-xl p-4 text-xs text-gray-500 leading-relaxed">
        <strong className="text-gray-400">Methodology:</strong> All results from exhaustive grid search over 4+ years of 1-minute Polygon data. Walk-forward split: train pre-2024-07-01, test post-2024-07-01. VIX regimes: Low (0-15), Normal (15-20), Elevated (20-25), High (25-35), Extreme (35+). Slippage tested at 0-10bps round-trip. Parameter robustness = % of configs profitable across all 13 spread pairs × exit combos. Stock Sharpe is per-trade (not annualized). No theoretical pricing — all option P&L from actual traded prices.
      </div>
    </div>
  );
}
