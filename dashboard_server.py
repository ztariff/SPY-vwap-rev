#!/usr/bin/env python3
"""
C-Shark Dashboard Server — serves the KITE backtest dashboard with live refresh.
Fetches trades directly from the KITE API (kiteapi.ktginnovation.com).

Local:   python dashboard_server.py
Railway: Deployed via Procfile, uses $PORT and $KITE_TOKEN env vars.
"""

import json, os, time, mimetypes, csv, io, threading
import urllib.request
import urllib.error
import numpy as np
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

BASE = os.path.dirname(os.path.abspath(__file__))

KITE_API = 'https://kiteapi.ktginnovation.com/v2'
KITE_TOKEN = os.environ.get('KITE_TOKEN', '23684e7f-34a0-44ba-8d88-3ab9626f8fe9')

# Strategy -> list of backtest submission hashes
STRATEGY_HASHES = {}
hashes_path = os.path.join(BASE, 'all_strategy_hashes.json')
if os.path.exists(hashes_path):
    with open(hashes_path) as f:
        STRATEGY_HASHES = json.load(f)

STRATEGY_ORDER = ['V16', 'Champion', 'Grade10', 'RangeOnly', 'V9', 'V16b']

# In-memory trade cache (populated on startup from JSON files, updated on refresh)
_trade_cache = {}       # strategy_name -> [processed trades]
_meta_cache = {}        # strategy_name -> stats dict
_total_trades = 0
_last_refresh = None
_refresh_lock = threading.Lock()
_is_refreshing = False


# ----- trade processing -----

def parse_csv_trades(csv_text):
    """Parse CSV trade data from KITE API into list of dicts."""
    if not csv_text or not csv_text.strip():
        return []
    reader = csv.DictReader(io.StringIO(csv_text))
    return list(reader)


def process_trades(raw_trades):
    """Convert raw KITE trade dicts to dashboard display format."""
    trades = []
    for t in raw_trades:
        try:
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
        except (KeyError, ValueError, TypeError) as e:
            continue
    trades.sort(key=lambda x: x['date'] + x['entry_time'])
    return trades


def compute_meta(trades):
    """Compute strategy-level stats."""
    pnls = [t['pnl'] for t in trades]
    n = len(pnls)
    if n == 0:
        return {'n': 0, 'total': 0, 'avg': 0, 'wr': 0, 'sharpe': 0, 'pf': 0, 'max_dd': 0}
    total = sum(pnls)
    avg = total / n
    wins = sum(1 for p in pnls if p > 0)
    wr = wins / n * 100
    std = float(np.std(pnls, ddof=1)) if n > 1 else 1
    sharpe = avg / std * np.sqrt(n / 4.2) if std > 0 else 0
    gain_sum = sum(p for p in pnls if p > 0)
    loss_sum = abs(sum(p for p in pnls if p < 0))
    pf = gain_sum / loss_sum if loss_sum > 0 else 99
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    max_dd = float(np.max(peak - cum))
    return {
        'n': n, 'total': round(total, 0), 'avg': round(avg, 0), 'wr': round(wr, 1),
        'sharpe': round(float(sharpe), 3), 'pf': round(float(pf), 2), 'max_dd': round(max_dd, 0)
    }


# ----- KITE API calls -----

def kite_fetch_trades(submission_hash):
    """Fetch trades for a single submission hash from KITE API."""
    url = f'{KITE_API}/pta/trades?submission={submission_hash}'
    req = urllib.request.Request(url, headers={'TATH-Token': KITE_TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode('utf-8')
            # API returns raw CSV (not JSON) with TATH-Token auth
            return parse_csv_trades(data)
    except Exception as e:
        print(f'  Error fetching {submission_hash[:12]}: {e}')
        return []


def fetch_all_strategy_trades():
    """Fetch all trades for all strategies from KITE API."""
    global _trade_cache, _meta_cache, _total_trades, _last_refresh

    all_data = {}
    strat_meta = {}
    total = 0

    for strat_name in STRATEGY_ORDER:
        hashes = STRATEGY_HASHES.get(strat_name, [])
        if not hashes:
            all_data[strat_name] = []
            strat_meta[strat_name] = compute_meta([])
            continue

        raw_trades = []
        errors = 0
        for i, h in enumerate(hashes):
            batch = kite_fetch_trades(h)
            raw_trades.extend(batch)
            if not batch:
                errors += 1
            # Small delay to avoid rate limiting
            if i < len(hashes) - 1:
                time.sleep(0.3)

        trades = process_trades(raw_trades)
        all_data[strat_name] = trades
        strat_meta[strat_name] = compute_meta(trades)
        total += len(trades)
        print(f'  {strat_name}: {len(trades)} trades from {len(hashes)} batches ({errors} errors)')

    # Update cache
    _trade_cache = all_data
    _meta_cache = strat_meta
    _total_trades = total
    _last_refresh = time.strftime('%H:%M:%S')

    return all_data, strat_meta, total


def load_from_json_files():
    """Load trades from local JSON files (startup fallback)."""
    global _trade_cache, _meta_cache, _total_trades, _last_refresh

    json_files = {
        'V16': 'kite_v16_trades.json',
        'Champion': 'kite_champion_trades.json',
        'Grade10': 'kite_grade10_trades.json',
        'RangeOnly': 'kite_rangeonly_trades.json',
        'V9': 'kite_v9_trades.json',
        'V16b': 'kite_v16b_trades.json',
    }

    all_data = {}
    strat_meta = {}
    total = 0

    for name in STRATEGY_ORDER:
        fname = json_files.get(name, '')
        fpath = os.path.join(BASE, fname)
        if os.path.exists(fpath):
            with open(fpath) as f:
                raw = json.load(f)
            trades = process_trades(raw)
        else:
            trades = []
        all_data[name] = trades
        strat_meta[name] = compute_meta(trades)
        total += len(trades)

    _trade_cache = all_data
    _meta_cache = strat_meta
    _total_trades = total
    _last_refresh = time.strftime('%H:%M:%S')

    return all_data, strat_meta, total


# ----- HTTP handler -----

class DashboardHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.lstrip('/')

        if path == '' or path == 'index.html':
            path = 'kite_dashboard.html'

        if path == 'api/data':
            return self._json_ok(self._current_payload())

        # Serve static files
        fpath = os.path.join(BASE, path)
        if os.path.isfile(fpath) and self._is_safe_file(path):
            return self._serve_file(fpath)

        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/refresh':
            return self._handle_refresh()
        self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def _current_payload(self):
        return {
            'trades': _trade_cache,
            'meta': _meta_cache,
            'total_trades': _total_trades,
            'timestamp': _last_refresh or time.strftime('%H:%M:%S'),
            'is_refreshing': _is_refreshing,
        }

    def _handle_refresh(self):
        global _is_refreshing
        if _is_refreshing:
            return self._json_ok({
                **self._current_payload(),
                'message': 'Refresh already in progress...',
            })

        _is_refreshing = True
        try:
            print(f'\n[{time.strftime("%H:%M:%S")}] Refresh triggered — fetching from KITE API...')
            fetch_all_strategy_trades()
            print(f'[{time.strftime("%H:%M:%S")}] Refresh complete — {_total_trades} total trades\n')
            return self._json_ok(self._current_payload())
        except Exception as e:
            print(f'Refresh error: {e}')
            return self._json_err(str(e))
        finally:
            _is_refreshing = False

    def _json_ok(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _json_err(self, msg):
        body = json.dumps({'error': msg}).encode()
        self.send_response(500)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, fpath):
        try:
            with open(fpath, 'rb') as f:
                body = f.read()
            ctype, _ = mimetypes.guess_type(fpath)
            self.send_response(200)
            self.send_header('Content-Type', ctype or 'application/octet-stream')
            self.send_header('Content-Length', str(len(body)))
            self._cors_headers()
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            self.send_error(500)

    def _cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _is_safe_file(self, path):
        safe_ext = {'.html', '.css', '.js', '.json', '.csv', '.ico', '.png', '.svg'}
        _, ext = os.path.splitext(path)
        return ext.lower() in safe_ext and '..' not in path

    def log_message(self, format, *args):
        if os.environ.get('RAILWAY_ENVIRONMENT') or 'api' in str(args):
            super().log_message(format, *args)
        elif '404' in str(args) or '500' in str(args):
            super().log_message(format, *args)


# ----- main -----

def main():
    port = int(os.environ.get('PORT', 8877))
    host = '0.0.0.0'

    print(f'C-Shark Dashboard Server')
    print(f'  URL: http://{"localhost" if not os.environ.get("RAILWAY_ENVIRONMENT") else host}:{port}')
    print(f'  KITE API: {KITE_API}')
    print(f'  Token: {KITE_TOKEN[:8]}...{KITE_TOKEN[-4:]}')
    print(f'  Strategies: {len(STRATEGY_HASHES)} ({sum(len(v) for v in STRATEGY_HASHES.values())} total hashes)')
    print()

    # Load from local JSON files on startup (fast)
    print('Loading from local JSON files...')
    _, meta, total = load_from_json_files()
    for name in STRATEGY_ORDER:
        m = meta.get(name, {})
        print(f'  {name}: {m.get("n", 0)} trades, Sharpe {m.get("sharpe", 0):.3f}')
    print(f'  Total: {total} trades')
    print(f'\nServer ready. Click "Refresh Data" in dashboard to pull fresh from KITE API.\n')

    server = HTTPServer((host, port), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServer stopped.')
        server.server_close()


if __name__ == '__main__':
    main()
