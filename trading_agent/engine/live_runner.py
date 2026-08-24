"""Continuous paper-trading loop: runs `TradingCycle` on an interval.

This cannot and does not promise profit — no system can guarantee that,
and this project explicitly refuses to (see `agents/risk.py`'s framing
and the guardrails discussion in README.md). What it does provide: a
fixed multi-agent decision process (see `engine/orchestrator.py`) run
repeatedly, marking positions to market and checking stop-losses each
tick, with results only ever booked into the local `PaperBroker` — never
a real order.

`auto_approve` is the one deliberate relaxation of "a human approves
every booking": passing it is a one-time, explicit opt-in (typed once,
at the start of a `watch` session) to auto-book every decision that
clears risk checks for the rest of that session, instead of prompting
per tick. Nothing changes about `PaperBroker.execute` itself — it still
raises without `human_approved=True`; this module is just the one caller
allowed to pass that flag on a loop's behalf, because the human already
decided by passing the flag.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from trading_agent.engine.orchestrator import CycleArtifacts, TradingCycle
from trading_agent.engine.paper_broker import PaperBroker
from trading_agent.engine.risk_controls import DailyCircuitBreaker


@dataclass
class TickResult:
    artifacts: CycleArtifacts
    stopped_out: list[str]
    booked: bool
    equity: float


def run_tick(
    cycle: TradingCycle,
    broker: PaperBroker,
    symbol: str,
    breaker: DailyCircuitBreaker | None,
    auto_approve: bool,
) -> TickResult:
    snapshot = cycle.fetch_snapshot(symbol)
    stopped_out = broker.check_stop_losses({symbol: snapshot.last_price})
    if cycle.config.risk.trailing_stop_pct:
        broker.apply_trailing_stops({symbol: snapshot.last_price}, cycle.config.risk.trailing_stop_pct)

    equity = broker.equity({symbol: snapshot.last_price})
    artifacts = cycle.run_cycle_with_snapshot(snapshot, account_equity=equity, circuit_breaker=breaker)

    booked = False
    if auto_approve and artifacts.decision.status == "pending_approval":
        broker.execute(artifacts.decision, human_approved=True)
        booked = True

    return TickResult(
        artifacts=artifacts,
        stopped_out=stopped_out,
        booked=booked,
        equity=broker.equity({symbol: snapshot.last_price}),
    )


def run_loop(
    cycle: TradingCycle,
    broker: PaperBroker,
    symbol: str,
    breaker: DailyCircuitBreaker | None,
    auto_approve: bool,
    interval_seconds: float,
    max_iterations: int | None,
    on_tick: Callable[[int, TickResult], None],
) -> None:
    """Runs until `max_iterations` ticks have happened (or forever if None).
    Raises KeyboardInterrupt up to the caller on Ctrl+C rather than
    swallowing it, so the caller can print a final summary and exit cleanly."""
    i = 0
    while max_iterations is None or i < max_iterations:
        result = run_tick(cycle, broker, symbol, breaker, auto_approve)
        on_tick(i, result)
        i += 1
        if max_iterations is None or i < max_iterations:
            time.sleep(interval_seconds)
