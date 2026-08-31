"""Minimal local dashboard for `cli.py portfolio-watch` — stdlib only, no
new dependency. Same shape as `trading_agent/dashboard.py`'s single-symbol
watch dashboard, adapted for a fixed multi-position portfolio: a total
value/PnL header, an equity curve, and a per-position table instead of a
decisions log (this loop never places a trade, so there's nothing to log
as a decision — see `portfolio/watch.py`'s docstring).

Runs a tiny HTTP server on 127.0.0.1 that polls `/api/state` every few
seconds and redraws. Reads only the in-process `PortfolioDashboardState`
the watch loop updates each tick — no outbound network calls of its own.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from trading_agent.portfolio.watch import PortfolioTick


@dataclass
class PortfolioDashboardState:
    data_source: str = "simulated"
    budget: float = 0.0
    benchmark_symbol: str = ""
    # Static context set once at startup (composite score / sector / consensus
    # per selected name) — this never changes tick to tick, unlike everything
    # else here; the watch loop re-prices, it never re-screens.
    selection_summary: list[dict] = field(default_factory=list)
    value_history: list[tuple[float, float]] = field(default_factory=list)
    positions: list[dict] = field(default_factory=list)
    cash: float = 0.0
    total_pnl_dollars: float = 0.0
    total_pnl_pct: float = 0.0
    tick_count: int = 0
    started_at: float = field(default_factory=time.time)
    last_errors: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "data_source": self.data_source,
                "budget": self.budget,
                "benchmark_symbol": self.benchmark_symbol,
                "selection_summary": self.selection_summary,
                "value_history": self.value_history[-500:],
                "positions": self.positions,
                "cash": self.cash,
                "total_pnl_dollars": self.total_pnl_dollars,
                "total_pnl_pct": self.total_pnl_pct,
                "tick_count": self.tick_count,
                "started_at": self.started_at,
                "last_errors": self.last_errors,
            }

    def record_tick(self, tick: PortfolioTick) -> None:
        with self._lock:
            self.value_history.append((tick.timestamp, tick.total_value))
            self.positions = [
                {
                    "symbol": p.symbol,
                    "shares": p.shares,
                    "cost_basis_price": p.cost_basis_price,
                    "current_price": p.current_price,
                    "current_value": p.current_value,
                    "pnl_dollars": p.pnl_dollars,
                    "pnl_pct": p.pnl_pct,
                    "stale": p.stale,
                }
                for p in tick.positions
            ]
            self.cash = tick.cash
            self.total_pnl_dollars = tick.total_pnl_dollars
            self.total_pnl_pct = tick.total_pnl_pct
            self.tick_count += 1
            self.last_errors = tick.errors


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Portfolio Watch — Live Dashboard</title>
<style>
  :root {
    --bg: #0b1220; --panel: #121b2e; --border: #223049;
    --text: #e6ecf5; --muted: #7e8ba3;
    --accent: #4fb3bf; --good: #4caf7d; --bad: #d9695f; --warn: #d1a24a;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  header {
    display: flex; align-items: baseline; gap: 12px; padding: 18px 24px;
    border-bottom: 1px solid var(--border); flex-wrap: wrap;
  }
  header h1 { font-size: 17px; margin: 0; font-weight: 600; }
  .badge {
    font-size: 11px; letter-spacing: .04em; text-transform: uppercase;
    color: var(--warn); border: 1px solid var(--warn); border-radius: 4px;
    padding: 2px 6px;
  }
  .badge.source { color: var(--accent); border-color: var(--accent); }
  main { padding: 20px 24px; display: flex; flex-direction: column; gap: 18px; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }
  .stat {
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
    padding: 12px 14px;
  }
  .stat .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
  .stat .value { font-size: 20px; font-variant-numeric: tabular-nums; margin-top: 4px; }
  .panel {
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 14px;
    overflow-x: auto;
  }
  .panel h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); margin: 0 0 10px; }
  canvas { width: 100%; height: 160px; display: block; }
  table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
  th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--border); white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; font-size: 12px; }
  .up { color: var(--good); } .down { color: var(--bad); }
  .stale { color: var(--warn); font-size: 11px; margin-left: 4px; }
  .empty { color: var(--muted); font-size: 13px; }
  .errors { color: var(--bad); font-size: 12px; margin-top: 8px; }
</style>
</head>
<body>
<header>
  <h1>Portfolio Watch — Live Dashboard</h1>
  <span class="badge">Read-only · No trades placed</span>
  <span class="badge source" id="s-source">—</span>
</header>
<main>
  <div class="stats">
    <div class="stat"><div class="label">Total Value</div><div class="value" id="s-value">—</div></div>
    <div class="stat"><div class="label">Total P&amp;L</div><div class="value" id="s-pnl">—</div></div>
    <div class="stat"><div class="label">Cash</div><div class="value" id="s-cash">—</div></div>
    <div class="stat"><div class="label">Ticks</div><div class="value" id="s-ticks">—</div></div>
    <div class="stat"><div class="label">Last update</div><div class="value" id="s-updated">—</div></div>
  </div>

  <div class="panel">
    <h2>Portfolio value over time</h2>
    <canvas id="chart" width="1000" height="160"></canvas>
  </div>

  <div class="panel">
    <h2>Positions</h2>
    <div id="positions-wrap"><div class="empty">Waiting for the first tick&hellip;</div></div>
    <div id="errors-wrap"></div>
  </div>

  <div class="panel" id="selection-panel" style="display:none">
    <h2>Why these — selection snapshot (fixed at startup)</h2>
    <div id="selection-wrap"></div>
  </div>
</main>

<script>
function fmt(n) { return Number(n).toLocaleString(undefined, {maximumFractionDigits: 2}); }
function fmtPct(n) { return (n * 100).toLocaleString(undefined, {maximumFractionDigits: 2}) + '%'; }

function drawChart(history) {
  const canvas = document.getElementById('chart');
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (history.length < 2) {
    ctx.fillStyle = '#7e8ba3';
    ctx.fillText('The chart fills in as ticks accumulate', 10, h / 2);
    return;
  }
  const values = history.map(p => p[1]);
  const min = Math.min(...values), max = Math.max(...values);
  const pad = (max - min) * 0.1 || 1;
  const lo = min - pad, hi = max + pad;

  ctx.strokeStyle = '#223049';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 3; i++) {
    const y = (h / 3) * i;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }

  ctx.beginPath();
  ctx.strokeStyle = '#4fb3bf';
  ctx.lineWidth = 2;
  history.forEach((p, i) => {
    const x = (i / (history.length - 1)) * (w - 4) + 2;
    const y = h - ((p[1] - lo) / (hi - lo)) * (h - 4) - 2;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();

  const last = history[history.length - 1];
  const lx = w - 2, ly = h - ((last[1] - lo) / (hi - lo)) * (h - 4) - 2;
  ctx.fillStyle = '#4fb3bf';
  ctx.beginPath(); ctx.arc(lx - 3, ly, 3, 0, Math.PI * 2); ctx.fill();
}

function renderPositions(positions, errors) {
  const el = document.getElementById('positions-wrap');
  if (!positions || positions.length === 0) { el.innerHTML = '<div class="empty">Waiting for the first tick&hellip;</div>'; return; }
  let rows = positions.map(p => `
    <tr>
      <td>${p.symbol}${p.stale ? '<span class="stale">stale</span>' : ''}</td>
      <td>${p.shares}</td>
      <td>$${fmt(p.cost_basis_price)}</td>
      <td>$${fmt(p.current_price)}</td>
      <td>$${fmt(p.current_value)}</td>
      <td class="${p.pnl_dollars >= 0 ? 'up' : 'down'}">${p.pnl_dollars >= 0 ? '+' : ''}$${fmt(p.pnl_dollars)}</td>
      <td class="${p.pnl_pct >= 0 ? 'up' : 'down'}">${p.pnl_pct >= 0 ? '+' : ''}${fmtPct(p.pnl_pct)}</td>
    </tr>`).join('');
  el.innerHTML = `<table><thead><tr><th>Symbol</th><th>Shares</th><th>Cost basis</th><th>Current price</th><th>Value</th><th>P&amp;L $</th><th>P&amp;L %</th></tr></thead><tbody>${rows}</tbody></table>`;

  const errEl = document.getElementById('errors-wrap');
  const errKeys = Object.keys(errors || {});
  errEl.innerHTML = errKeys.length
    ? '<div class="errors">Fetch errors this tick (showing last-known price instead): ' + errKeys.join(', ') + '</div>'
    : '';
}

function renderSelection(summary) {
  if (!summary || summary.length === 0) return;
  document.getElementById('selection-panel').style.display = '';
  let rows = summary.map(s => `
    <tr>
      <td>${s.symbol}</td>
      <td>${s.sector}</td>
      <td>${s.composite_score >= 0 ? '+' : ''}${s.composite_score.toFixed(2)}</td>
      <td>${s.signal}</td>
    </tr>`).join('');
  document.getElementById('selection-wrap').innerHTML =
    `<table><thead><tr><th>Symbol</th><th>Sector</th><th>Composite score</th><th>Consensus</th></tr></thead><tbody>${rows}</tbody></table>`;
}

let renderedSelection = false;

async function refresh() {
  try {
    const res = await fetch('/api/state');
    const state = await res.json();
    document.getElementById('s-source').textContent = state.data_source === 'live' ? 'LIVE DATA' : 'SIMULATED DATA';
    const value = state.value_history.length ? state.value_history[state.value_history.length - 1][1] : null;
    document.getElementById('s-value').textContent = value !== null ? '$' + fmt(value) : '—';
    const pnlEl = document.getElementById('s-pnl');
    pnlEl.textContent = (state.total_pnl_dollars >= 0 ? '+' : '') + '$' + fmt(state.total_pnl_dollars) + ' (' + fmtPct(state.total_pnl_pct) + ')';
    pnlEl.className = 'value ' + (state.total_pnl_dollars > 0 ? 'up' : state.total_pnl_dollars < 0 ? 'down' : '');
    document.getElementById('s-cash').textContent = '$' + fmt(state.cash);
    document.getElementById('s-ticks').textContent = state.tick_count;
    document.getElementById('s-updated').textContent = state.tick_count ? new Date().toLocaleTimeString() : '—';
    drawChart(state.value_history || []);
    renderPositions(state.positions, state.last_errors);
    if (!renderedSelection) { renderSelection(state.selection_summary); renderedSelection = true; }
  } catch (e) {
    // server not reachable yet (e.g. first paint before the loop starts) — retry silently
  }
}
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""


def _make_handler(state: PortfolioDashboardState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 - stdlib signature
            pass  # keep the terminal clean; the watch loop already prints each tick

        def do_GET(self):
            if self.path == "/api/state":
                body = json.dumps(state.snapshot()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path in ("/", ""):
                body = _PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

    return Handler


def start_dashboard_server(state: PortfolioDashboardState, port: int = 8788) -> ThreadingHTTPServer:
    """Starts the dashboard's HTTP server in a background thread and
    returns it (call `.shutdown()` to stop it). Binds to 127.0.0.1
    only — not reachable from outside the machine it runs on. Default
    port 8788 (not 8787) so it can run alongside the single-symbol
    `watch --dashboard` at the same time without a port clash."""
    server = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
