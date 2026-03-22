#!/usr/bin/env python3
"""
C-Shark Dashboard Server — serves the KITE backtest dashboard with live refresh.

Local:   python dashboard_server.py
Railway: Deployed via Procfile, uses $PORT env var.
"""

import json, os, time, mimetypes
import numpy as np
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

BASE = os.path.dirname(os.path.abspath(__file__))

STRATEGIES = {
    'V16': 'kite_v16_trades.json',
    'Champion': 'kite_champion_trades.json',
    'Grade10': 'kite_grade10_trades.json',
    'RangeOnly': 'kite_rangeonly_trades.json',
    'V9': 'kite_v9_trades.json',
    'V16b': 'kite_v16b_trades.json',
}

# ----- trade processing -----

def process_trades(raw):
    """Convert raw KITE trade dicts to dashboard format."""
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


def load_all_strategies():
    """Read all trade JSON files from disk and return processed data + meta."""
    all_data = {}
    strat_meta = {}
    total_trades = 0
    for name, fname in STRATEGIES.items():
        fpath = os.path.join(BASE, fname)
        if not os.path.exists(fpath):
            all_data[name] = []
            strat_meta[name] = compute_meta([])
            continue
        with open(fpath) as f:
            raw = json.load(f)
        trades = process_trades(raw)
        all_data[name] = trades
        strat_meta[name] = compute_meta(trades)
        total_trades += len(trades)
    return all_data, strat_meta, total_trades


# ----- HTTP handler -----

# Allowed static files (whitelist for security)
STATIC_FILES = {
    'kite_dashboard.html', 'kite_daily_features.csv', 'kite_all_trades.csv',
}

class DashboardHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.lstrip('/')

        # Root -> dashboard
        if path == '' or path == 'index.html':
            path = 'kite_dashboard.html'

        # API: return trade data as JSON
        if path == 'api/data':
            return self._json_response(*self._build_payload())

        # Serve static files
        fpath = os.path.join(BASE, path)
        if os.path.isfile(fpath) and (path in STATIC_FILES or path.endswith('.html') or path.endswith('.css') or path.endswith('.js') or path.endswith('.json') or path.endswith('.csv')):
            return self._serve_file(fpath)

        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/refresh':
            return self._json_response(*self._build_payload())
        self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def _build_payload(self):
        all_data, strat_meta, total = load_all_strategies()
        return 200, {
            'trades': all_data,
            'meta': strat_meta,
            'total_trades': total,
            'timestamp': time.strftime('%H:%M:%S'),
        }

    def _json_response(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
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

    def log_message(self, format, *args):
        # Log all requests on Railway, suppress noisy ones locally
        if os.environ.get('RAILWAY_ENVIRONMENT'):
            super().log_message(format, *args)
        elif '404' in str(args) or '500' in str(args) or 'api' in str(args):
            super().log_message(format, *args)


# ----- main -----

def main():
    port = int(os.environ.get('PORT', 8877))
    host = '0.0.0.0'  # Railway requires 0.0.0.0

    server = HTTPServer((host, port), DashboardHandler)
    print(f"C-Shark Dashboard Server")
    print(f"  URL: http://{'localhost' if host == '0.0.0.0' else host}:{port}")
    print(f"  Base: {BASE}")

    # Load and display stats on startup
    _, meta, total = load_all_strategies()
    for name in ['V16', 'Champion', 'Grade10', 'RangeOnly', 'V9', 'V16b']:
        m = meta[name]
        print(f"  {name}: {m['n']} trades, Sharpe {m['sharpe']:.3f}")
    print(f"  Total: {total} trades across {len(STRATEGIES)} strategies\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()


if __name__ == '__main__':
    main()
