"""FastAPI + WebSocket server driving `SessionRunner` from a browser.

Optional dependency (`requirements-web.txt`) — not needed for the CLI or
anything else in this project. Run with:

    pip install -r requirements-web.txt
    python -m trading_agent.webapp
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse

from trading_agent.webapp.session import SessionConfig, SessionRunner

app = FastAPI(title="Trading Agent Web UI")

_sessions: dict[str, SessionRunner] = {}
_STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
def index():
    return FileResponse(_STATIC_DIR / "index.html")


def _get_session(session_id: str) -> SessionRunner:
    runner = _sessions.get(session_id)
    if runner is None:
        raise KeyError(session_id)
    return runner


@app.post("/api/sessions")
def create_session(payload: dict):
    session_id = str(uuid.uuid4())
    config = SessionConfig(
        mode=payload.get("mode", "signal"),
        symbol=payload["symbol"],
        leverage=float(payload.get("leverage", 1.0)),
        tranches=int(payload.get("tranches", 2)),
        use_live=bool(payload.get("use_live", False)),
        use_kronos=bool(payload.get("use_kronos", False)),
        interval_seconds=float(payload.get("interval_seconds", 15.0)),
        period=payload.get("period", "6mo"),
        start_date=payload.get("start_date") or None,
        end_date=payload.get("end_date") or None,
        min_lookback=int(payload.get("min_lookback", 35)),
        anthropic_api_key=payload.get("anthropic_api_key") or None,
    )
    _sessions[session_id] = SessionRunner(session_id, config)
    return {"session_id": session_id}


@app.post("/api/sessions/{session_id}/{action}")
def control_session(session_id: str, action: str):
    try:
        runner = _get_session(session_id)
    except KeyError:
        return PlainTextResponse("unknown session", status_code=404)

    method = getattr(runner, action, None)
    if action not in ("start", "pause", "resume", "stop", "reset") or method is None:
        return PlainTextResponse("unknown action", status_code=400)
    method()
    return {"ok": True, "state": runner.state}


@app.get("/api/sessions/{session_id}/export.json")
def export_json(session_id: str):
    runner = _get_session(session_id)
    trade_log = runner.broker.trade_log if runner.broker else []
    body = json.dumps(
        {"session_id": session_id, "state": runner.state, "trade_log": trade_log},
        ensure_ascii=False,
        default=str,
    )
    return PlainTextResponse(body, media_type="application/json")


@app.get("/api/sessions/{session_id}/export.csv")
def export_csv(session_id: str):
    runner = _get_session(session_id)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["symbol", "action", "quantity", "price", "pnl"])
    writer.writeheader()
    for row in runner.broker.trade_log if runner.broker else []:
        writer.writerow(row)
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")


@app.get("/api/sessions/{session_id}/export.md")
def export_markdown(session_id: str):
    runner = _get_session(session_id)
    lines = [f"# Trading session {session_id}", "", f"State: {runner.state}", ""]
    if runner.broker is not None:
        lines.append(f"- Equity: {runner.broker.equity({}):,.0f}")
        lines.append(f"- Realized PnL: {runner.broker.realized_pnl:,.0f}")
        lines.append("")
        lines.append("| Symbol | Action | Quantity | Price | PnL |")
        lines.append("|---|---|---|---|---|")
        for row in runner.broker.trade_log:
            pnl = f"{row['pnl']:.2f}" if row["pnl"] is not None else ""
            lines.append(f"| {row['symbol']} | {row['action']} | {row['quantity']:.4f} | {row['price']:.2f} | {pnl} |")
    lines.append("")
    lines.append("_Research/education tool. Not investment advice. Paper trading only — no real order was placed._")
    return PlainTextResponse("\n".join(lines), media_type="text/markdown")


@app.websocket("/ws/{session_id}")
async def session_socket(websocket: WebSocket, session_id: str):
    await websocket.accept()
    try:
        runner = _get_session(session_id)
    except KeyError:
        await websocket.send_json({"kind": "error", "data": {"message": "unknown session"}})
        await websocket.close()
        return

    try:
        while True:
            for event in runner.drain_events():
                await websocket.send_json(event)
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.3)
            except asyncio.TimeoutError:
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            action = message.get("action")
            if action == "start":
                runner.start()
            elif action == "pause":
                runner.pause()
            elif action == "resume":
                runner.resume()
            elif action == "stop":
                runner.stop()
            elif action == "reset":
                runner.reset()
    except WebSocketDisconnect:
        pass
