from ktg.interfaces import Strategy, Event


class VwapMeanReversion(Strategy):
    """SPY/QQQ VWAP mean reversion strategy (C-Shark).

    Entry: resting limit at VWAP - entry_pct% (buys).
    Exit: resting limit target, limit stop, time exit, EOD exit.
    One trade per direction per day.

    Sizing modes (controlled by sizing_mode parameter):
      0 = flat (risk_budget on every trade)
      1 = G1 composite v1 (gap pre-filtered in dates)
      2 = G3 composite v2 (gap pre-filtered in dates)
      3 = G4 composite v2 + skip TOD 30-45m
      4 = F6 skip(gap+2d+body pre-filtered) + 1.67x wide prior + trend
          also skips TOD 30-45m in code
      5 = V16 asymmetric heavy penalty (optimized thresholds, no TOD skip)
      6 = V16b asymmetric heavy penalty + skip first 10 minutes
      7 = V9 kitchen sink (v2_opt + slope + velocity) + skip first 10 minutes
      8 = Champion: V16b prior-day + intraday range + dist_open + vol_ratio
          skip first 10 minutes, intraday features computed at entry time
      9 = Range-only: intraday range sizing only (no prior-day signals)
          skip first 10 minutes, isolates intraday range signal
     10 = Weighted grade: 7-feature continuous scoring system
          Each feature scored -1 to +1, weighted by correlation with P&L
          Negative scores penalized 1.5x (asymmetric), scale=0.25
          skip first 10 minutes

    All sizing features are PRIOR-DAY only (zero hindsight) EXCEPT:
    - V9 velocity: computed intraday from bars before entry
    - Modes 8/9 today_range_pct: session range from bars before entry
    - Mode 8 dist_from_open: distance from session open at entry time
    Daily features loaded from kite_daily_features.csv via service.read_file().
    """

    __script_name__ = 'vwap_mean_reversion'

    DAY_GAP_US = 4 * 3600 * 1000000

    ST_FLAT = 0
    ST_ENTRY_PENDING = 1
    ST_IN_POSITION = 2
    ST_EXIT_PENDING = 3

    NOTIONAL_CAP = 25000000

    def __init__(self, **kwargs):
        self.direction = kwargs.get('direction', 'buy')
        self.entry_pct = kwargs.get('entry_pct', 0.4)
        self.stop_pct = kwargs.get('stop_pct', 1.0)
        self.target_pct = kwargs.get('target_pct', 0.75)
        self.time_exit_minutes = kwargs.get('time_exit_minutes', 15)
        self.sizing_mode = kwargs.get('sizing_mode', 0)
        self.risk_budget = kwargs.get('risk_budget', 150000.0)
        self.min_bars_for_vwap = kwargs.get('min_bars_for_vwap', 5)
        self.eod_exit_hour = kwargs.get('eod_exit_hour', 15)
        self.eod_exit_minute = kwargs.get('eod_exit_minute', 55)
        self.buy_algo = kwargs.get('buy_algo', '10b39bea-8f18-4838-9207-cca44e05794d')
        self.sell_algo = kwargs.get('sell_algo', '8cfeb551-7c2a-4a9a-8888-601324d0fcd2')

    @classmethod
    def on_strategy_start(cls, md, service, account):
        from ktg.interfaces import LastLoadedStrategy
        params = LastLoadedStrategy.parameters
        service.info(f"VwapMeanReversion params: {params}")

    @classmethod
    def is_symbol_qualified(cls, symbol, md, service, account):
        return False

    @classmethod
    def using_extra_symbols(cls, symbol, md, service, account):
        return False

    def on_start(self, md, order, service, account):
        self.state = self.ST_FLAT
        self.position_side = 0
        self.entry_price = 0.0
        self.target_price = 0.0
        self.stop_price = 0.0
        self.bars_since_entry = 0

        self.entry_limit_price = 0.0
        self.entry_side = 0
        self.entry_shares = 0

        self.cum_tp_vol = 0.0
        self.cum_vol = 0.0
        self.bar_count = 0

        self.traded_buy_today = False
        self.traded_fade_today = False
        self.last_bar_ts = 0
        self._last_close = 0.0

        # Sizing multiplier for today (loaded from CSV)
        self.today_sizing_mult = 1.0

        # TOD skip modes:
        #   'none' = no skip
        #   '30-45' = skip bars 30-45 (modes 3, 4)
        #   'first10' = skip first 10 bars (modes 6, 7, 8, 9)
        if self.sizing_mode in (3, 4):
            self.tod_skip_mode = '30-45'
        elif self.sizing_mode in (6, 7, 8, 9, 10):
            self.tod_skip_mode = 'first10'
        else:
            self.tod_skip_mode = 'none'

        # V9 velocity tracking: count bars where close >= VWAP
        self.velocity_bars_above = 0
        self.velocity_bars_total = 0

        # Modes 8/9/10: intraday session tracking
        self.session_high = 0.0
        self.session_low = 999999.0
        self.session_open = 0.0
        self.today_vol_ratio = 1.0

        # Mode 10: prior-day features for weighted grade
        self.today_prior_day_range = 1.0
        self.today_prior_day_body = 0.4
        self.today_return_2d = 0.0
        self.today_sma5_above_sma20 = 0
        self.today_sma_slope = 0.0

        # Load daily features CSV
        self._daily_features = {}
        self._load_features(service)

        service.clear_event_triggers()
        service.add_event_trigger([md.symbol], [
            Event.MINUTE_BAR, Event.FILL, Event.REJECT, Event.CANCEL
        ])

        service.info(
            f"Started {md.symbol} dir={self.direction} "
            f"entry={self.entry_pct}% stop={self.stop_pct}% "
            f"target={self.target_pct}% sizing_mode={self.sizing_mode}"
        )

    def _load_features(self, service):
        """Load pre-computed daily features from uploaded CSV."""
        try:
            raw = service.read_file("kite_daily_features.csv")
            if not raw:
                service.info("WARNING: kite_daily_features.csv empty or not found")
                return
            lines = raw.strip().split('\n')
            if len(lines) < 2:
                return
            header = lines[0].split(',')
            for line in lines[1:]:
                parts = line.split(',')
                if len(parts) != len(header):
                    continue
                row = {}
                for j, col in enumerate(header):
                    row[col] = parts[j]
                date_str = row.get('date', '')
                if date_str:
                    self._daily_features[date_str] = row
            service.info(f"Loaded {len(self._daily_features)} daily feature rows")
        except Exception as e:
            service.info(f"WARNING: Failed to load features: {e}")

    def _get_sizing_mult(self, date_str, service):
        """Get sizing multiplier for a date based on sizing_mode."""
        if self.sizing_mode == 0:
            return 1.0

        row = self._daily_features.get(date_str)
        if not row:
            service.info(f"No features for {date_str}, using 1.0x")
            return 1.0

        if self.sizing_mode == 1:
            # G1: composite v1
            return float(row.get('score_v1', '1.0'))
        elif self.sizing_mode == 2:
            # G3: composite v2
            return float(row.get('score_v2', '1.0'))
        elif self.sizing_mode == 3:
            # G4: composite v2 + TOD skip (TOD handled separately)
            return float(row.get('score_v2', '1.0'))
        elif self.sizing_mode == 4:
            # F6: 1.67x wide prior * (1.2 trend / 0.8 no trend)
            return float(row.get('f6_mult', '1.0'))
        elif self.sizing_mode in (5, 6):
            # V16/V16b: asymmetric heavy penalty (V16b TOD skip handled separately)
            return float(row.get('score_v16', '1.0'))
        elif self.sizing_mode == 7:
            # V9: base score from CSV (velocity added at entry time)
            return float(row.get('score_v9_base', '1.0'))
        elif self.sizing_mode == 8:
            # Champion: V16b prior-day base (intraday adjustments at entry)
            return float(row.get('score_v16', '1.0'))
        elif self.sizing_mode == 9:
            # Range-only: no prior-day sizing, intraday range at entry
            return 1.0
        elif self.sizing_mode == 10:
            # Weighted grade: base=1.0, full computation at entry time
            return 1.0
        return 1.0

    # ------------------------------------------------------------------
    # Daily reset
    # ------------------------------------------------------------------

    def _reset_daily(self, service):
        self.cum_tp_vol = 0.0
        self.cum_vol = 0.0
        self.bar_count = 0
        self.traded_buy_today = False
        self.traded_fade_today = False
        self.today_sizing_mult = 1.0
        self.velocity_bars_above = 0
        self.velocity_bars_total = 0
        self.session_high = 0.0
        self.session_low = 999999.0
        self.session_open = 0.0
        self.today_vol_ratio = 1.0
        # Mode 10 prior-day features
        self.today_prior_day_range = 1.0
        self.today_prior_day_body = 0.4
        self.today_return_2d = 0.0
        self.today_sma5_above_sma20 = 0
        self.today_sma_slope = 0.0
        service.info("New trading day - VWAP reset")

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def _compute_shares(self, entry_price, risk_budget):
        if entry_price <= 0 or self.stop_pct <= 0:
            return 0
        shares = int(risk_budget / (entry_price * self.stop_pct / 100.0))
        max_shares = int(self.NOTIONAL_CAP / entry_price)
        shares = min(shares, max_shares)
        return max(shares, 1) if shares > 0 else 0

    # ------------------------------------------------------------------
    # Main bar handler
    # ------------------------------------------------------------------

    def on_minute_bar(self, event, md, order, service, account, bar):
        if self.last_bar_ts > 0:
            if (event.timestamp - self.last_bar_ts) > self.DAY_GAP_US:
                self._handle_new_day(md, order, service, account)
        self.last_bar_ts = event.timestamp

        self._last_close = event.close

        if event.volume > 0:
            tp = (event.high + event.low + event.close) / 3.0
            self.cum_tp_vol += tp * event.volume
            self.cum_vol += event.volume
        self.bar_count += 1

        # Track intraday session high/low/open for modes 8/9/10
        if self.sizing_mode in (8, 9, 10):
            if event.high > self.session_high:
                self.session_high = event.high
            if event.low < self.session_low:
                self.session_low = event.low
            if self.bar_count == 1:
                self.session_open = event.open

        # First bar: compute today's sizing multiplier
        if self.bar_count == 1:
            # Extract date from system_time
            ts_str = service.time_to_string(event.timestamp)
            date_str = ts_str[:10] if ts_str and len(ts_str) >= 10 else ''
            self.today_sizing_mult = self._get_sizing_mult(date_str, service)
            # Load prior-day features for modes 8 and 10
            if self.sizing_mode in (8, 10):
                row = self._daily_features.get(date_str)
                if row:
                    self.today_vol_ratio = float(row.get('daily_vol_ratio', '1.0'))
                    if self.sizing_mode == 10:
                        self.today_prior_day_range = float(row.get('prior_day_range', '1.0'))
                        self.today_prior_day_body = float(row.get('prior_day_body', '0.4'))
                        self.today_return_2d = float(row.get('return_2d', '0'))
                        self.today_sma5_above_sma20 = int(float(row.get('sma5_above_sma20', '0')))
                        self.today_sma_slope = float(row.get('sma5_slope', '0'))
            service.info(f"Today={date_str} sizing_mult={self.today_sizing_mult:.3f}")

        if self.bar_count < self.min_bars_for_vwap or self.cum_vol <= 0:
            return

        vwap = self.cum_tp_vol / self.cum_vol

        # V9 velocity tracking: count bars where close >= VWAP
        if self.sizing_mode == 7:
            self.velocity_bars_total += 1
            if event.close >= vwap:
                self.velocity_bars_above += 1

        if self.state == self.ST_FLAT:
            self._handle_flat(vwap, md, order, service, account)
        elif self.state == self.ST_ENTRY_PENDING:
            self._handle_entry_pending(vwap, md, order, service, account)
        elif self.state == self.ST_IN_POSITION:
            self.bars_since_entry += 1
            self._check_exits(event, md, order, service, account)

    # ------------------------------------------------------------------
    # FLAT: place resting limit
    # ------------------------------------------------------------------

    def _handle_flat(self, vwap, md, order, service, account):
        if service.system_time >= service.time(self.eod_exit_hour, self.eod_exit_minute):
            return

        # TOD skip logic
        if self.tod_skip_mode == '30-45' and 30 <= self.bar_count < 45:
            return
        if self.tod_skip_mode == 'first10' and self.bar_count < 10:
            return

        buy_threshold = vwap * (1.0 - self.entry_pct / 100.0)
        fade_threshold = vwap * (1.0 + self.entry_pct / 100.0)

        if self.direction in ('buy', 'both') and not self.traded_buy_today:
            if buy_threshold > 0:
                self._place_entry_limit(1, buy_threshold, vwap, md, order, service, account)
                return

        if self.direction in ('fade', 'both') and not self.traded_fade_today:
            if fade_threshold > 0:
                self._place_entry_limit(-1, fade_threshold, vwap, md, order, service, account)
                return

    # ------------------------------------------------------------------
    # ENTRY_PENDING: update limit when threshold shifts
    # ------------------------------------------------------------------

    def _handle_entry_pending(self, vwap, md, order, service, account):
        if service.system_time >= service.time(self.eod_exit_hour, self.eod_exit_minute):
            order.cancel()
            self.state = self.ST_FLAT
            return

        # If we drifted into TOD skip zone with a pending order, cancel it
        if self.tod_skip_mode == '30-45' and 30 <= self.bar_count < 45:
            order.cancel()
            self.state = self.ST_FLAT
            return
        if self.tod_skip_mode == 'first10' and self.bar_count < 10:
            order.cancel()
            self.state = self.ST_FLAT
            return

        if self.entry_side == 1:
            new_threshold = vwap * (1.0 - self.entry_pct / 100.0)
        else:
            new_threshold = vwap * (1.0 + self.entry_pct / 100.0)

        if new_threshold <= 0:
            return

        new_price = round(max(new_threshold, 0.01), 2)

        if abs(new_price - self.entry_limit_price) > 0.01:
            order.cancel()
            self._place_entry_limit(self.entry_side, new_threshold, vwap, md, order, service, account)

    # ------------------------------------------------------------------
    # Place entry limit order
    # ------------------------------------------------------------------

    def _place_entry_limit(self, side, threshold, vwap, md, order, service, account):
        if md.L1.bid <= 0 or md.L1.ask <= 0:
            return

        # Apply sizing multiplier from daily features
        mult = self.today_sizing_mult

        # V9: add velocity adjustment at entry time
        if self.sizing_mode == 7 and self.velocity_bars_total > 0:
            vel_pct = (self.velocity_bars_above / self.velocity_bars_total) * 100
            if vel_pct > 15:
                mult += 0.15
            if vel_pct < 3:
                mult -= 0.15
            mult = max(mult, 0.2)

        # Mode 8 (Champion): intraday range + dist_open + vol_ratio
        if self.sizing_mode == 8:
            # today_range_pct from session bars seen so far
            if self.session_high > 0 and self._last_close > 0:
                today_range = (self.session_high - self.session_low) / self._last_close * 100
                if today_range > 1.0:
                    mult -= 1.0
                elif today_range < 0.6:
                    mult += 0.3
            # dist_from_open: penalize entries above session open
            if self.session_open > 0 and self._last_close > 0:
                dist_open = (self._last_close - self.session_open) / self.session_open * 100
                if dist_open > 0:
                    mult -= 0.2
            # daily vol ratio from CSV
            if self.today_vol_ratio > 1.5:
                mult -= 0.4
            mult = max(mult, 0.1)

        # Mode 9 (Range-only): only intraday range sizing
        if self.sizing_mode == 9:
            if self.session_high > 0 and self._last_close > 0:
                today_range = (self.session_high - self.session_low) / self._last_close * 100
                if today_range > 1.0:
                    mult = 0.3
                elif today_range > 0.6:
                    mult = 0.8
                elif today_range < 0.4:
                    mult = 1.5
                else:
                    mult = 1.0

        # Mode 10 (Weighted grade): 7-feature continuous scoring
        # scale=0.25, asymmetry=1.5x on negative scores
        if self.sizing_mode == 10:
            score = 0.0

            # prior_day_range (weight 1.504)
            r = self.today_prior_day_range
            if r > 1.8: s = 1.0
            elif r > 1.2: s = 0.5
            elif r > 0.8: s = 0.0
            elif r > 0.5: s = -0.5
            else: s = -1.0
            score += s * 1.504 * (1.5 if s < 0 else 1.0)

            # prior_day_body (weight 1.682)
            b = self.today_prior_day_body
            if b > 0.8: s = 1.0
            elif b > 0.5: s = 0.5
            elif b > 0.35: s = 0.0
            elif b > 0.2: s = -0.5
            else: s = -1.0
            score += s * 1.682 * (1.5 if s < 0 else 1.0)

            # return_2d (weight 1.108)
            r2 = self.today_return_2d
            if r2 < -2.0: s = 1.0
            elif r2 < -1.0: s = 0.5
            elif r2 < 0.5: s = 0.0
            elif r2 < 1.2: s = -0.5
            else: s = -1.0
            score += s * 1.108 * (1.5 if s < 0 else 1.0)

            # trend: sma5_above_sma20 (weight 1.046)
            s = 1.0 if self.today_sma5_above_sma20 else -1.0
            score += s * 1.046 * (1.5 if s < 0 else 1.0)

            # sma_slope (weight 0.870)
            sl = self.today_sma_slope
            if sl > 1.0: s = 1.0
            elif sl > 0.3: s = 0.5
            elif sl > -0.3: s = 0.0
            elif sl > -1.0: s = -0.5
            else: s = -1.0
            score += s * 0.870 * (1.5 if s < 0 else 1.0)

            # vol_ratio (weight 1.705)
            v = self.today_vol_ratio
            if v < 0.7: s = 0.5
            elif v < 1.2: s = 0.0
            elif v < 1.5: s = -0.3
            else: s = -1.0
            score += s * 1.705 * (1.5 if s < 0 else 1.0)

            # today_range - intraday (weight 1.925)
            if self.session_high > 0 and self._last_close > 0:
                tr = (self.session_high - self.session_low) / self._last_close * 100
            else:
                tr = 0.5
            if tr < 0.4: s = 1.0
            elif tr < 0.6: s = 0.7
            elif tr < 0.8: s = 0.3
            elif tr < 1.0: s = 0.0
            elif tr < 1.5: s = -0.5
            elif tr < 2.0: s = -0.8
            else: s = -1.0
            score += s * 1.925 * (1.5 if s < 0 else 1.0)

            mult = 1.0 + score * 0.25
            mult = max(mult, 0.1)
            service.info(f"Grade10: score={score:.3f} mult={mult:.3f} tr={tr:.2f}")

        risk = self.risk_budget * mult

        shares = self._compute_shares(threshold, risk)
        if shares <= 0:
            return

        price = round(max(threshold, 0.01), 2)

        if side == 1:
            order_id = order.algo_buy(
                md.symbol, self.buy_algo, "init",
                order_quantity=shares, price=price
            )
        else:
            order_id = order.algo_sell(
                md.symbol, self.sell_algo, "init",
                order_quantity=shares, price=price
            )

        if order_id:
            self.state = self.ST_ENTRY_PENDING
            self.entry_limit_price = price
            self.entry_side = side
            self.entry_shares = shares
            side_str = "BUY" if side == 1 else "SELL"
            notional = shares * price
            service.info(
                f"LIMIT {side_str}: {shares} sh @ ${price:.2f} "
                f"VWAP=${vwap:.4f} risk=${risk:.0f} mult={mult:.2f} "
                f"notional=${notional:,.0f} bar={self.bar_count}"
            )

    # ------------------------------------------------------------------
    # Exit logic
    # ------------------------------------------------------------------

    def _check_exits(self, evt, md, order, service, account):
        if service.system_time >= service.time(self.eod_exit_hour, self.eod_exit_minute):
            order.cancel()
            self._market_exit(md, order, service, account, "eod")
            return

        if self.time_exit_minutes > 0 and self.bars_since_entry >= self.time_exit_minutes:
            order.cancel()
            self._market_exit(md, order, service, account, "time_exit")
            return

        if self.position_side == 1:
            if evt.low <= self.stop_price:
                order.cancel()
                self._stop_exit(md, order, service, account)
                return
        elif self.position_side == -1:
            if evt.high >= self.stop_price:
                order.cancel()
                self._stop_exit(md, order, service, account)
                return

    def _stop_exit(self, md, order, service, account):
        current_shares = account[md.symbol].position.shares
        if current_shares == 0:
            self.state = self.ST_FLAT
            self.position_side = 0
            self.entry_price = 0.0
            return

        stop = max(self.stop_price, 0.01)
        if current_shares > 0:
            if md.L1.bid >= stop:
                order_id = order.algo_sell(md.symbol, self.sell_algo, "exit", price=stop)
            else:
                order_id = order.algo_sell(md.symbol, self.sell_algo, "exit")
        else:
            if md.L1.ask <= stop:
                order_id = order.algo_buy(md.symbol, self.buy_algo, "exit", price=stop)
            else:
                order_id = order.algo_buy(md.symbol, self.buy_algo, "exit")

        if order_id:
            self.state = self.ST_EXIT_PENDING
            service.info(f"STOP EXIT: {abs(int(current_shares))} shares @ ${stop:.2f}")

    def _market_exit(self, md, order, service, account, reason):
        current_shares = account[md.symbol].position.shares
        if current_shares == 0:
            self.state = self.ST_FLAT
            self.position_side = 0
            self.entry_price = 0.0
            return

        if current_shares > 0:
            order_id = order.algo_sell(md.symbol, self.sell_algo, "exit")
        else:
            order_id = order.algo_buy(md.symbol, self.buy_algo, "exit")

        if order_id:
            self.state = self.ST_EXIT_PENDING
            service.info(f"MARKET EXIT ({reason}): {abs(int(current_shares))} shares")

    # ------------------------------------------------------------------
    # New day
    # ------------------------------------------------------------------

    def _handle_new_day(self, md, order, service, account):
        if self.state == self.ST_ENTRY_PENDING:
            order.cancel()
        if self.state == self.ST_IN_POSITION:
            order.cancel()
            self._market_exit(md, order, service, account, "overnight")
        if self.state != self.ST_EXIT_PENDING:
            self.state = self.ST_FLAT
            self.position_side = 0
            self.entry_price = 0.0
        self._reset_daily(service)

    # ------------------------------------------------------------------
    # Order events
    # ------------------------------------------------------------------

    def on_fill(self, event, md, order, service, account):
        current_shares = account[md.symbol].position.shares

        if self.state == self.ST_ENTRY_PENDING and current_shares != 0:
            self.position_side = 1 if current_shares > 0 else -1
            self.entry_price = event.price
            self.bars_since_entry = 0

            if self.position_side == 1:
                self.traded_buy_today = True
            else:
                self.traded_fade_today = True

            if self.position_side == 1:
                self.target_price = round(self.entry_price * (1.0 + self.target_pct / 100.0), 2)
                self.stop_price = round(self.entry_price * (1.0 - self.stop_pct / 100.0), 2)
            else:
                self.target_price = round(self.entry_price * (1.0 - self.target_pct / 100.0), 2)
                self.stop_price = round(self.entry_price * (1.0 + self.stop_pct / 100.0), 2)

            if self.position_side == 1:
                order.algo_sell(md.symbol, self.sell_algo, "exit",
                               price=max(self.target_price, 0.01))
            else:
                order.algo_buy(md.symbol, self.buy_algo, "exit",
                               price=max(self.target_price, 0.01))

            self.state = self.ST_IN_POSITION
            notional = abs(current_shares) * event.price
            service.info(
                f"ENTRY FILLED: {current_shares:.0f} @ ${event.price:.2f} "
                f"target=${self.target_price:.2f} stop=${self.stop_price:.2f} "
                f"notional=${notional:,.0f} mult={self.today_sizing_mult:.2f}"
            )

        elif self.state == self.ST_IN_POSITION and current_shares == 0:
            pnl = self._calc_pnl(event.price, abs(event.shares))
            self.state = self.ST_FLAT
            service.info(f"TARGET FILLED @ ${event.price:.2f}, P&L=${pnl:.2f}")
            self.position_side = 0
            self.entry_price = 0.0

        elif self.state == self.ST_EXIT_PENDING and current_shares == 0:
            pnl = self._calc_pnl(event.price, abs(event.shares))
            self.state = self.ST_FLAT
            service.info(f"EXIT FILLED @ ${event.price:.2f}, P&L=${pnl:.2f}")
            self.position_side = 0
            self.entry_price = 0.0

        else:
            service.info(
                f"FILL: {event.shares:.0f} @ ${event.price:.2f}, "
                f"net={current_shares:.0f} state={self.state}"
            )

    def _calc_pnl(self, exit_price, shares):
        if self.position_side == 1:
            return (exit_price - self.entry_price) * shares
        elif self.position_side == -1:
            return (self.entry_price - exit_price) * shares
        return 0.0

    def on_reject(self, event, md, order, service, account):
        service.info(f"ORDER REJECTED: {event.reject_reason}")
        if account[md.symbol].position.shares == 0:
            self.state = self.ST_FLAT
            self.position_side = 0
            self.entry_price = 0.0
        elif self.state == self.ST_EXIT_PENDING:
            self.state = self.ST_IN_POSITION

    def on_cancel(self, event, md, order, service, account):
        pass

    def on_finish(self, md, order, service, account):
        current_shares = account[md.symbol].position.shares
        if current_shares != 0:
            service.info(f"Finishing with {current_shares:.0f} shares still open")

    def _on_feedback(self, md, service, account):
        states = {0: 'FLAT', 1: 'ENTRY_PEND', 2: 'IN_POS', 3: 'EXIT_PEND'}
        vwap_str = ""
        if self.cum_vol > 0:
            vwap = self.cum_tp_vol / self.cum_vol
            vwap_str = f"VWAP={vwap:.2f} "
        return f"{vwap_str}m={self.today_sizing_mult:.2f} {states.get(self.state, '?')} bars={self.bar_count}"
