import time

import pytest

pytest.importorskip("fastapi", reason="fastapi/uvicorn not installed (requirements-web.txt)")
pytest.importorskip("httpx", reason="httpx not installed (needed by fastapi.testclient.TestClient)")

from fastapi.testclient import TestClient  # noqa: E402

from trading_agent.webapp.server import _sessions, app  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_sessions():
    _sessions.clear()
    yield
    _sessions.clear()


def test_index_serves_html():
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200
    assert "Trading Agent" in res.text


def test_create_session_returns_id():
    client = TestClient(app)
    res = client.post("/api/sessions", json={"mode": "signal", "symbol": "AAPL"})
    assert res.status_code == 200
    assert "session_id" in res.json()


def test_control_endpoints_start_and_reset():
    client = TestClient(app)
    session_id = client.post("/api/sessions", json={"mode": "signal", "symbol": "AAPL"}).json()["session_id"]

    res = client.post(f"/api/sessions/{session_id}/start")
    assert res.status_code == 200

    deadline = time.time() + 5
    while time.time() < deadline:
        runner = _sessions[session_id]
        if runner.state in ("completed", "error"):
            break
        time.sleep(0.02)

    res = client.post(f"/api/sessions/{session_id}/reset")
    assert res.status_code == 200
    assert _sessions[session_id].state == "idle"


def test_unknown_session_control_returns_404():
    client = TestClient(app)
    res = client.post("/api/sessions/does-not-exist/start")
    assert res.status_code == 404


def test_export_endpoints_return_expected_media_types():
    client = TestClient(app)
    session_id = client.post("/api/sessions", json={"mode": "signal", "symbol": "AAPL"}).json()["session_id"]
    client.post(f"/api/sessions/{session_id}/start")

    deadline = time.time() + 5
    while time.time() < deadline:
        if _sessions[session_id].state in ("completed", "error"):
            break
        time.sleep(0.02)

    assert client.get(f"/api/sessions/{session_id}/export.json").headers["content-type"].startswith("application/json")
    assert client.get(f"/api/sessions/{session_id}/export.csv").headers["content-type"].startswith("text/csv")
    md_res = client.get(f"/api/sessions/{session_id}/export.md")
    assert md_res.headers["content-type"].startswith("text/markdown")
    assert "Not investment advice" in md_res.text


def test_websocket_relays_events_and_accepts_control_messages():
    client = TestClient(app)
    session_id = client.post("/api/sessions", json={"mode": "signal", "symbol": "AAPL"}).json()["session_id"]

    with client.websocket_connect(f"/ws/{session_id}") as websocket:
        websocket.send_json({"action": "start"})
        kinds = set()
        deadline = time.time() + 5
        while time.time() < deadline and "decision" not in kinds:
            event = websocket.receive_json()
            kinds.add(event["kind"])
        assert "decision" in kinds
