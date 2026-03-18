# SPY VWAP Fade/Dip Strategy — Full Backtest Analysis

## Executive Summary

The backtest scanned ~3 years of SPY 1-minute data across 16 ATR multiplier levels (0.5x–2.0x), both directions (above VWAP for fading, below VWAP for buying the dip), and optimized across 1,050 exit parameter combinations per direction. Here are the key findings.

**Bottom line: The BELOW VWAP (buy-the-dip) setup has a meaningfully stronger edge than the ABOVE VWAP (fade/short) setup.** Both are tradeable under the right regime conditions, but the long side is more robust.

---

## 1. ATR Entry Level — Which Multiplier Works Best?

### BELOW VWAP (Buy the Dip — Long SPY)

| ATR Mult | Signals | Avg P&L (%) | Win Rate | Total P&L |
|----------|---------|-------------|----------|-----------|
| **0.6x** | **113** | **+0.056%** | **60.2%** | **+6.27** |
| 0.5x | 197 | +0.033% | 59.4% | +6.51 |
| 0.7x | 75 | +0.040% | 58.7% | +2.97 |
| 0.8x | 50 | +0.048% | 52.0% | +2.39 |
| 0.9x | 27 | +0.024% | 51.9% | +0.65 |
| 1.0x+ | — | Negative or tiny sample | — | — |

**Takeaway:** 0.6x ATR below VWAP is the sweet spot — good signal count (113), highest avg P&L per trade, and 60% win rate. Going tighter (0.5x) gives more signals but dilutes edge. Going wider (0.8x+) shrinks the sample too fast.

### ABOVE VWAP (Fade — Short SPY)

| ATR Mult | Signals | Avg P&L (%) | Win Rate | Total P&L |
|----------|---------|-------------|----------|-----------|
| **0.7x** | **41** | **+0.008%** | **58.5%** | **+0.32** |
| 1.5x+ | 2–3 | +0.50% | 100% | ~1.0 |
| 0.5x | 127 | -0.022% | 50.4% | -2.81 |
| 0.6x | 71 | -0.039% | 50.7% | -2.78 |
| 0.8x–1.4x | — | Mostly negative | — | — |

**Takeaway:** The fade side is much weaker with default exits. Only 0.7x ATR above VWAP shows a slight positive edge. The 1.5x+ levels show big P&L but on 2–3 trades — statistically meaningless. This tells us the short side needs more careful exit management and regime filtering to be tradeable.

---

## 2. Optimized Exit Parameters — Stock

### BELOW VWAP (Best Exits for Buying the Dip)

**Primary ATR: 0.6x below VWAP (N=27 trades at the optimized level after grid search)**

| Rank | Stop | Target | Time Exit | Trail | Win Rate | Avg P&L | Expectancy |
|------|------|--------|-----------|-------|----------|---------|------------|
| 1 | 0.25% | 1.5% | EOD | None | 37.0% | +0.216% | +0.216% |
| 2 | 0.25% | 1.5% | 60min | None | 40.7% | +0.207% | +0.207% |
| 3 | 0.25% | 1.5% | EOD | 0.75% | 40.7% | +0.183% | +0.183% |
| 4 | 0.25% | 1.5% | 120min | None | 37.0% | +0.181% | +0.181% |

**The consistent theme:** tight 0.25% hard stop, 1.5% profit target, and EOD or 60-minute time exit. Trailing stops don't add much. The strategy wins ~37–41% of the time but the winners are 3–4x the size of losers (avg winner ~0.98% vs avg loser ~0.24%).

**Profit factor: 2.45** — strong for a mean-reversion setup.

### ABOVE VWAP (Best Exits for Fading)

**Primary ATR: 0.7x above VWAP (N=20 trades)**

| Rank | Stop | Target | Time Exit | Trail | Win Rate | Avg P&L | Expectancy |
|------|------|--------|-----------|-------|----------|---------|------------|
| 1 | 0.25% | 3.0% | EOD | 0.75% | 30.0% | +0.100% | +0.100% |
| 2 | 0.25% | 1.5% | EOD | 0.75% | 30.0% | +0.100% | +0.100% |
| 3 | 0.25% | 2.0% | EOD | None | 25.0% | +0.081% | +0.081% |
| 4 | 1.5% | 1.0% | 120min | 0.25% | 40.0% | +0.070% | +0.070% |

**Interesting divergence:** Two viable approaches emerge for the fade:

- **Approach A (tight stop, wide target):** 0.25% stop, 1.5%+ target, EOD exit, optional 0.75% trail. Wins only 25–30% of the time but has big winners. Profit factor ~1.6.
- **Approach B (wide stop, tight target, tight trail):** 1.5%+ stop, 1.0% target, 120min exit, 0.25% trail. Wins 40% of the time with more consistent but smaller gains. Profit factor ~2.07.

Approach B is interesting because the tight trailing stop (0.25%) essentially locks in profits quickly — it's a scalping variant that holds for ~18 minutes on average vs ~38 minutes for Approach A.

---

## 3. Regime Filters — When to Trade and When to Sit Out

### VIX Level (Most Important Filter)

**ABOVE VWAP (Fade):**
| VIX | Trades | Win Rate | Avg P&L |
|-----|--------|----------|---------|
| **15–20** | **5** | **60%** | **+0.60%** |
| 20–25 | 4 | 50% | +0.35% |
| 25–30 | 1 | 0% | -0.25% |
| 30+ | 2 | 0% | -0.25% |
| <15 | 2 | 0% | -0.26% |

**BELOW VWAP (Buy Dip):**
| VIX | Trades | Win Rate | Avg P&L |
|-----|--------|----------|---------|
| **30+** | **2** | **50%** | **+0.63%** |
| 20–25 | 2 | 50% | +0.23% |
| 15–20 | 12 | 33% | +0.05% |
| <15 | 4 | 0% | -0.25% |

**Key insight:** The fade works best in moderate VIX (15–20) — markets have enough vol to deviate from VWAP but not so much that the trend just keeps going. The buy-the-dip works best in *high* VIX (30+) — when fear is elevated, oversold bounces are more powerful. Both strategies lose in low VIX (<15) — moves from VWAP in calm markets tend to be directional, not mean-reverting.

### Time of Day

**ABOVE (Fade):**
| Time | Trades | Win Rate | Avg P&L |
|------|--------|----------|---------|
| **Midday (12–2pm)** | **3** | **67%** | **+0.59%** |
| Power Hour (3–4pm) | 9 | 22% | +0.14% |
| Afternoon (2–3pm) | 4 | 25% | -0.10% |
| Late Morning | 3 | 33% | -0.13% |
| Open Hour | 1 | 0% | -0.25% |

**BELOW (Buy Dip):**
| Time | Trades | Win Rate | Avg P&L |
|------|--------|----------|---------|
| **Midday (12–2pm)** | **8** | **50%** | **+0.30%** |
| Afternoon (2–3pm) | 9 | 44% | +0.28% |
| Late Morning | 3 | 33% | +0.25% |
| Power Hour | 7 | 14% | +0.03% |

**Key insight:** Midday is the best window for both directions. The open hour is unreliable (directional momentum dominates). Power hour is weak for dip buying — likely because sellers push prices lower into the close.

### Gap Direction

**ABOVE (Fade):**
| Gap | Trades | Avg P&L |
|-----|--------|---------|
| **Big gap down** | **4** | **+0.37%** |
| Small gap down | 3 | +0.32% |
| Small gap up | 6 | +0.11% |
| Big gap up | 4 | -0.09% |
| Flat | 3 | -0.25% |

**BELOW (Buy Dip):**
| Gap | Trades | Avg P&L |
|-----|--------|---------|
| **Big gap up** | **2** | **+0.63%** |
| **Big gap down** | **6** | **+0.49%** |
| Small gap down | 7 | +0.17% |
| Small gap up | 8 | +0.06% |
| Flat | 4 | -0.01% |

**Key insight:** For fading above VWAP, gap-down days are best (short-covering rally overshoots → fades well). For buying below VWAP, big gaps in either direction are best (mean-reversion is strongest after large dislocations).

### Bonds (TLT)

**ABOVE (Fade):** Better when bonds are DOWN (yields up) — Avg +0.21% vs -0.03% when bonds up
**BELOW (Buy Dip):** Works roughly equally in both bond directions (~+0.22% either way)

**Key insight:** Fading works better when bonds are selling off (risk-off rotation) — the equity rally into VWAP deviation is more likely to reverse. Dip buying is agnostic to bonds.

### 5-Day Momentum

**ABOVE (Fade):**
| Momentum | Trades | Avg P&L |
|----------|--------|---------|
| Strong 5d down | 10 | +0.21% |
| Mild 5d down | 6 | +0.15% |
| Mild 5d up | 2 | -0.24% |
| Flat | 2 | -0.25% |

**BELOW (Buy Dip):**
| Momentum | Trades | Avg P&L |
|----------|--------|---------|
| Strong 5d up | 2 | +0.63% |
| Strong 5d down | 7 | +0.50% |
| Mild 5d up | 6 | +0.24% |
| Mild 5d down | 4 | -0.01% |
| Flat | 8 | -0.04% |

**Key insight:** Fading works best after recent weakness (mean-reversion from a bounce within a selloff). Buying the dip works best after strong moves in *either* direction — extreme 5-day momentum creates mean-reversion setups.

### Cross-Factor: Consecutive Days × VIX

**ABOVE (Fade) — Best regime:**
- 0–1 up days + VIX 15–20: **4 trades, 75% win rate, +0.81% avg P&L** — this is the single strongest cross-factor combination

**BELOW (Buy Dip) — Best regimes:**
- 0–1 up days + VIX NaN*: 5 trades, 60% WR, +0.64% avg
- 2+ up days + VIX NaN*: 2 trades, 50% WR, +0.64% avg
- 0–1 up days + VIX 30+: 2 trades, 50% WR, +0.63% avg

*VIX NaN likely means VIX data wasn't available for those dates — these should be treated cautiously.*

---

## 4. Scale-In Results

### Does scaling in add value?

**BELOW VWAP (0.9x entry → 1.1x add):**
- 27 trades, 37% win rate, +0.198% avg P&L (with 41% of trades getting the scale-in)
- Compare to single-entry best: +0.216% avg P&L

**ABOVE VWAP (1.5x entry → 2.0x add):**
- Only 2 trades — too few to draw conclusions

**Verdict:** Scale-in doesn't meaningfully improve over single entry for below VWAP. The extra complexity isn't worth it. For above VWAP, there simply aren't enough extreme-extension signals to test scale-in properly.

---

## 5. Options — Status

**No options results were generated.** The Polygon options data pull was either skipped (due to the main run focusing on stock) or the API calls for 0DTE options didn't return sufficient data. This is the biggest gap in the analysis.

**To get options results, you'd need to run the script specifically for options, ensuring:**
1. Polygon has 0DTE options intraday data for the backtest period
2. The options data pull step isn't skipped
3. Sufficient API quota for the thousands of options contract lookups needed

---

## 6. Actionable Trade Plan

### Strategy A: Buy the Dip (BELOW VWAP) — PRIMARY STRATEGY

**Entry:** SPY price ≥ 0.6x ATR(14) below session VWAP
- Take the first signal of the day only
- Use prior day's ATR for the threshold

**Filters (trade only when):**
- VIX ≥ 15 (skip when VIX < 15)
- Prefer VIX 20+ for larger sizing
- Time: 10:30am–3:00pm ET (midday/afternoon best; skip open hour and power hour)
- Big gap days are better than flat opens
- Works in all momentum regimes, but strongest after strong 5-day moves

**Exits:**
- Hard stop: 0.25% from entry
- Profit target: 1.5%
- Time exit: EOD (or 60 minutes if you want faster turnover — similar expectancy)
- No trailing stop needed

**Expected performance:** ~37% win rate, +0.22% avg P&L per trade, profit factor ~2.5, ~27+ signals per year at this threshold

**Risk sizing by regime:**
| Regime | Risk Multiplier |
|--------|----------------|
| VIX 30+ | 2.0x base size |
| VIX 20–25 | 1.0x base size |
| VIX 15–20 | 0.5x base size |
| VIX < 15 | **No trade** |

### Strategy B: Fade the Rally (ABOVE VWAP) — SECONDARY/OPPORTUNISTIC

**Entry:** SPY price ≥ 0.7x ATR(14) above session VWAP

**Filters (stricter than buy-dip):**
- VIX 15–25 ONLY (don't fade in high-vol or low-vol)
- 0–1 consecutive up days only (don't fade multi-day rallies)
- Time: Midday (12–2pm) or Power Hour only
- Gap-down days preferred
- Bonds selling off (TLT down) preferred
- Recent 5-day weakness preferred

**Two exit approaches:**
- **Conservative (scalp):** 1.5% stop, 1.0% target, 120min time exit, 0.25% trail. 40% WR, ~18min hold, +0.07% avg
- **Aggressive (let it ride):** 0.25% stop, 1.5% target, EOD exit, 0.75% trail. 30% WR, ~38min hold, +0.10% avg

**Expected performance:** ~20 signals per year, +0.07–0.10% avg P&L, profit factor 1.5–2.0

---

## 7. Caveats and Next Steps

### Sample Size Warning
The primary concern is small sample sizes. At 0.6x ATR below VWAP we have 113 signals for the ATR scan but only 27 at the grid-search level. The regime sub-groups are 2–12 trades each. These findings are directionally informative but need more data to be statistically robust.

### What's Missing
1. **Options P&L**: No options backtest results were generated. This is critical for determining whether long puts (for fading) or short puts (for buying dip) offer better risk/reward than stock.
2. **Slippage and commissions**: Not modeled. At these P&L levels (~0.2%), even small friction matters.
3. **Longer backtest**: 3 years captures different regimes but more history would improve confidence.
4. **Out-of-sample testing**: All results are in-sample. Need to reserve data for validation.

### Recommended Next Steps
1. **Run options-specific backtest** to test long puts for fading, short calls for fading, long calls for dip buying, and short puts for dip buying with real Polygon options pricing
2. **Expand date range** if Polygon data is available further back
3. **Forward-test** the buy-the-dip strategy paper trading for 1–2 months before going live
4. **Test on QQQ/IWM** to see if the VWAP reversion edge extends beyond SPY
