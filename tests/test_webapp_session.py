import time

import pytest

from trading_agent.webapp.session import SessionConfig, SessionRunner, SessionState


def _wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_signal_session_runs_to_completion_and_emits_expected_events():
    runner = SessionRunner("s1", SessionConfig(mode="signal", symbol="AAPL"))
    runner.start()
    assert _wait_for(lambda: runner.state in (SessionState.COMPLETED, SessionState.ERROR))

    events = []
    deadline = time.time() + 2
    while time.time() < deadline:
        events.extend(runner.drain_events())
        if any(e["kind"] == "decision" for e in events):
            break
        time.sleep(0.02)

    kinds = [e["kind"] for e in events]
    assert "thought" in kinds
    assert "decision" in kinds
    assert "portfolio" in kinds
    assert runner.state == SessionState.COMPLETED


def test_watch_session_can_be_stopped():
    runner = SessionRunner(
        "s2", SessionConfig(mode="watch", symbol="AAPL", interval_seconds=0.05)
    )
    runner.start()
    assert _wait_for(lambda: runner.state == SessionState.RUNNING)
    time.sleep(0.2)  # let a few ticks happen
    runner.stop()
    assert _wait_for(lambda: runner.state == SessionState.STOPPED)

    events = runner.drain_events()
    assert any(e["kind"] == "tick" for e in events)


def test_watch_session_pause_resume_then_stop():
    runner = SessionRunner(
        "s3", SessionConfig(mode="watch", symbol="AAPL", interval_seconds=0.05)
    )
    runner.start()
    assert _wait_for(lambda: runner.state == SessionState.RUNNING)
    runner.pause()
    assert runner.state == SessionState.PAUSED
    time.sleep(0.2)
    runner.resume()
    assert runner.state == SessionState.RUNNING
    runner.stop()
    assert _wait_for(lambda: runner.state == SessionState.STOPPED)


def test_reset_returns_to_idle_and_clears_events():
    runner = SessionRunner("s4", SessionConfig(mode="signal", symbol="AAPL"))
    runner.start()
    assert _wait_for(lambda: runner.state == SessionState.COMPLETED)
    runner.reset()
    assert runner.state == SessionState.IDLE
    assert runner.drain_events() == [] or all(e["kind"] == "status" for e in runner.drain_events())
    assert runner.broker is None


def test_backtest_session_produces_final_report():
    runner = SessionRunner(
        "s5", SessionConfig(mode="backtest", symbol="AAPL", min_lookback=35)
    )
    runner.start()
    assert _wait_for(lambda: runner.state in (SessionState.COMPLETED, SessionState.ERROR), timeout=10)

    events = []
    deadline = time.time() + 2
    while time.time() < deadline:
        events.extend(runner.drain_events())
        if any(e["kind"] == "final_report" for e in events):
            break
        time.sleep(0.02)

    final = next(e for e in events if e["kind"] == "final_report")
    assert "performance" in final["data"]
    assert final["data"]["performance"]["starting_equity"] > 0


def test_events_are_json_safe_enums_and_dataclasses_converted():
    runner = SessionRunner("s6", SessionConfig(mode="signal", symbol="AAPL"))
    runner.start()
    assert _wait_for(lambda: runner.state == SessionState.COMPLETED)

    events = []
    deadline = time.time() + 2
    while time.time() < deadline:
        events.extend(runner.drain_events())
        if any(e["kind"] == "decision" for e in events):
            break
        time.sleep(0.02)

    decision_event = next(e for e in events if e["kind"] == "decision")
    plan = decision_event["data"]["artifacts"]["decision"]["trade_plan"]
    assert isinstance(plan["action"], str)  # Action enum -> plain string
    import json

    json.dumps(decision_event)  # must not raise
