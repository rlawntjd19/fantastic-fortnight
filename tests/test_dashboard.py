import json
import urllib.request

from trading_agent.dashboard import DashboardState, start_dashboard_server


def test_dashboard_state_records_and_snapshots_ticks():
    state = DashboardState()
    state.record_tick(
        symbol="AAPL",
        equity=1_000_000.0,
        decision_summary={"ts": 1.0, "action": "buy"},
        positions={"AAPL": {"quantity": 10}},
        realized_pnl=500.0,
    )
    snap = state.snapshot()
    assert snap["symbol"] == "AAPL"
    assert snap["tick_count"] == 1
    assert snap["realized_pnl"] == 500.0
    assert snap["positions"] == {"AAPL": {"quantity": 10}}
    assert snap["decisions"] == [{"ts": 1.0, "action": "buy"}]


def test_dashboard_snapshot_caps_history_length():
    state = DashboardState()
    for i in range(600):
        state.record_tick(
            symbol="AAPL", equity=float(i), decision_summary={"ts": float(i)}, positions={}, realized_pnl=0.0
        )
    snap = state.snapshot()
    assert len(snap["equity_history"]) == 500
    assert len(snap["decisions"]) == 50
    # most recent decision first
    assert snap["decisions"][0]["ts"] == 599.0


def test_dashboard_http_server_serves_page_and_api():
    state = DashboardState()
    state.record_tick(symbol="AAPL", equity=1.0, decision_summary={"ts": 1.0}, positions={}, realized_pnl=0.0)
    server = start_dashboard_server(state, port=0)
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            assert resp.status == 200
            assert b"Trading Agent" in resp.read()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5) as resp:
            assert resp.status == 200
            body = json.loads(resp.read())
            assert body["symbol"] == "AAPL"
    finally:
        server.shutdown()
