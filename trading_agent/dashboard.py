"""Minimal local dashboard for `cli.py watch` — stdlib only, no new dependency.

Runs a tiny HTTP server on 127.0.0.1 that serves one page. The page polls
`/api/state` every few seconds and redraws an equity curve, the open
paper positions, and a log of recent decisions. It only ever reads the
in-process `DashboardState` the watch loop updates each tick — it does
not talk to the internet, a brokerage, or anything outside this process.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class DashboardState:
    symbol: str = ""
    equity_history: list[tuple[float, float]] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    positions: dict = field(default_factory=dict)
    realized_pnl: float = 0.0
    tick_count: int = 0
    started_at: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "symbol": self.symbol,
                "equity_history": self.equity_history[-500:],
                "decisions": list(reversed(self.decisions[-50:])),
                "positions": self.positions,
                "realized_pnl": self.realized_pnl,
                "tick_count": self.tick_count,
                "started_at": self.started_at,
            }

    def record_tick(
        self,
        *,
        symbol: str,
        equity: float,
        decision_summary: dict,
        positions: dict,
        realized_pnl: float,
    ) -> None:
        with self._lock:
            self.symbol = symbol
            self.equity_history.append((time.time(), equity))
            self.decisions.append(decision_summary)
            self.positions = positions
            self.realized_pnl = realized_pnl
            self.tick_count += 1


_PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Trading Agent — Live Dashboard</title>
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
    border-bottom: 1px solid var(--border);
  }
  header h1 { font-size: 17px; margin: 0; font-weight: 600; }
  .badge {
    font-size: 11px; letter-spacing: .04em; text-transform: uppercase;
    color: var(--warn); border: 1px solid var(--warn); border-radius: 4px;
    padding: 2px 6px;
  }
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
  .pill {
    display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 11px;
  }
  .pill.pending_approval { background: rgba(76,175,125,.15); color: var(--good); }
  .pill.blocked { background: rgba(217,105,95,.15); color: var(--bad); }
  .empty { color: var(--muted); font-size: 13px; }
</style>
</head>
<body>
<header>
  <h1>Trading Agent — Live Dashboard</h1>
  <span class="badge">Paper · Not Real Money</span>
</header>
<main>
  <div class="stats">
    <div class="stat"><div class="label">Symbol</div><div class="value" id="s-symbol">—</div></div>
    <div class="stat"><div class="label">Paper Equity</div><div class="value" id="s-equity">—</div></div>
    <div class="stat"><div class="label">Realized PnL</div><div class="value" id="s-pnl">—</div></div>
    <div class="stat"><div class="label">Open Positions</div><div class="value" id="s-positions">—</div></div>
    <div class="stat"><div class="label">Ticks</div><div class="value" id="s-ticks">—</div></div>
  </div>

  <div class="panel">
    <h2>Equity curve</h2>
    <canvas id="chart" width="1000" height="160"></canvas>
  </div>

  <div class="panel">
    <h2>Open positions</h2>
    <div id="positions-wrap"><div class="empty">아직 없음</div></div>
  </div>

  <div class="panel">
    <h2>Recent decisions</h2>
    <div id="decisions-wrap"><div class="empty">아직 없음</div></div>
  </div>
</main>

<script>
function fmt(n) { return Number(n).toLocaleString(undefined, {maximumFractionDigits: 0}); }

function drawChart(history) {
  const canvas = document.getElementById('chart');
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (history.length < 2) {
    ctx.fillStyle = '#7e8ba3';
    ctx.fillText('데이터가 쌓이면 여기에 그래프가 나타납니다', 10, h / 2);
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

function renderPositions(positions) {
  const entries = Object.entries(positions || {});
  const el = document.getElementById('positions-wrap');
  if (entries.length === 0) { el.innerHTML = '<div class="empty">아직 없음</div>'; return; }
  let rows = entries.map(([sym, p]) => `
    <tr>
      <td>${sym}</td>
      <td class="${p.quantity >= 0 ? 'up' : 'down'}">${p.quantity >= 0 ? 'LONG' : 'SHORT'}</td>
      <td>${fmt(Math.abs(p.quantity))}</td>
      <td>${fmt(p.avg_entry_price)}</td>
      <td>${p.leverage}x</td>
      <td>${fmt(p.stop_loss_price)}</td>
    </tr>`).join('');
  el.innerHTML = `<table><thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Avg entry</th><th>Leverage</th><th>Stop</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderDecisions(decisions) {
  const el = document.getElementById('decisions-wrap');
  if (!decisions || decisions.length === 0) { el.innerHTML = '<div class="empty">아직 없음</div>'; return; }
  let rows = decisions.map(d => `
    <tr>
      <td>${new Date(d.ts * 1000).toLocaleTimeString()}</td>
      <td>${d.action}</td>
      <td>${fmt(d.entry_price)}</td>
      <td>${d.leverage}x</td>
      <td><span class="pill ${d.status}">${d.status}</span></td>
      <td>${d.booked ? '✅ booked' : ''}${(d.stopped_out || []).length ? ' 🛑 stopped out' : ''}</td>
    </tr>`).join('');
  el.innerHTML = `<table><thead><tr><th>Time</th><th>Action</th><th>Price</th><th>Leverage</th><th>Status</th><th>Note</th></tr></thead><tbody>${rows}</tbody></table>`;
}

async function refresh() {
  try {
    const res = await fetch('/api/state');
    const state = await res.json();
    document.getElementById('s-symbol').textContent = state.symbol || '—';
    const eq = state.equity_history.length ? state.equity_history[state.equity_history.length - 1][1] : null;
    document.getElementById('s-equity').textContent = eq !== null ? fmt(eq) : '—';
    const pnl = state.realized_pnl || 0;
    const pnlEl = document.getElementById('s-pnl');
    pnlEl.textContent = fmt(pnl);
    pnlEl.className = 'value ' + (pnl > 0 ? 'up' : pnl < 0 ? 'down' : '');
    document.getElementById('s-positions').textContent = Object.keys(state.positions || {}).length;
    document.getElementById('s-ticks').textContent = state.tick_count;
    drawChart(state.equity_history || []);
    renderPositions(state.positions);
    renderDecisions(state.decisions);
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


def _make_handler(state: DashboardState):
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


def start_dashboard_server(state: DashboardState, port: int = 8787) -> ThreadingHTTPServer:
    """Starts the dashboard's HTTP server in a background thread and returns it
    (call `.shutdown()` to stop it). Binds to 127.0.0.1 only — not reachable
    from outside the machine it runs on."""
    server = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
