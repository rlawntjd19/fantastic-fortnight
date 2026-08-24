"""Backtest runner: replays historical bars through `TradingCycle` bar-by-bar.

`ReplayFeed` only ever hands back bars up to its current cursor — it
cannot serve a future bar even by mistake, which is what gives this the
same "no look-ahead" property purpose-built backtesting frameworks
enforce, structurally rather than via a separate guard.

Because a backtest replays data that has already happened, entirely
inside the local `PaperBroker`, running `backtest` at all is itself the
one human decision needed for every decision in the replay to book
automatically — there's no live market to protect against here, and a
per-tick prompt wouldn't tell a human anything they can't already see in
the final report.

Past performance in the report this produces does not indicate or
guarantee future results.
"""
from __future__ import annotations

from dataclasses import dataclass

from trading_agent.data.providers import MarketSnapshot
from trading_agent.engine.orchestrator import TradingCycle
from trading_agent.engine.paper_broker import PaperBroker
from trading_agent.engine.performance import PerformanceReport, compute_performance
from trading_agent.engine.risk_controls import DailyCircuitBreaker


class ReplayFeed:
    def __init__(self, full_snapshot: MarketSnapshot, min_lookback: int) -> None:
        if min_lookback < 2:
            raise ValueError("min_lookback must be at least 2")
        self._full = full_snapshot
        self._cursor = min(min_lookback, len(full_snapshot.bars))

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        return MarketSnapshot(
            symbol=symbol,
            bars=self._full.bars[: self._cursor],
            fundamentals=self._full.fundamentals,
            news_headlines=self._full.news_headlines,
        )

    def advance(self) -> None:
        self._cursor += 1

    @property
    def done(self) -> bool:
        return self._cursor >= len(self._full.bars)


@dataclass
class BacktestResult:
    performance: PerformanceReport
    equity_curve: list[tuple[int, float]]  # (bar timestamp, equity)
    num_ticks: int


def run_backtest(
    cycle: TradingCycle,
    replay: ReplayFeed,
    broker: PaperBroker,
    symbol: str,
    breaker: DailyCircuitBreaker | None = None,
) -> BacktestResult:
    equity_curve: list[tuple[int, float]] = []

    while not replay.done:
        snapshot = replay.get_snapshot(symbol)
        current_price = snapshot.last_price

        broker.check_stop_losses({symbol: current_price})
        if cycle.config.risk.trailing_stop_pct:
            broker.apply_trailing_stops({symbol: current_price}, cycle.config.risk.trailing_stop_pct)

        artifacts = cycle.run_cycle_with_snapshot(
            snapshot, account_equity=broker.equity({symbol: current_price}), circuit_breaker=breaker
        )
        if artifacts.decision.status == "pending_approval":
            broker.execute(artifacts.decision, human_approved=True)

        equity_curve.append((snapshot.bars[-1].timestamp, broker.equity({symbol: current_price})))
        replay.advance()

    trade_pnls = [t["pnl"] for t in broker.trade_log if t.get("pnl") is not None]
    performance = compute_performance([e for _, e in equity_curve], trade_pnls)
    return BacktestResult(performance=performance, equity_curve=equity_curve, num_ticks=len(equity_curve))
