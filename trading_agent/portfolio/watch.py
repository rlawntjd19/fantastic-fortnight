"""Continuous, read-only tracking of an already-selected portfolio's live
value — a companion to `pipeline.run_portfolio_research`'s one-shot
selection/allocation, not a replacement for it.

This never re-screens the universe, re-optimizes weights, or places any
order — it only re-fetches each held symbol's current price on an
interval and recomputes the portfolio's current value/PnL against the
cost basis fixed at selection time. Mirrors `engine/live_runner.run_loop`'s
loop-control shape, but for a fixed basket instead of one symbol with an
active trading decision each tick.

**Why a fetch failure here doesn't stop the loop**, unlike every other
live-data path in this project (`YFinanceFeed`/`AlphaVantageFeed` both
raise hard on a failed fetch, deliberately, so a bad fetch never turns
into a silent bad *trading decision*): this loop never decides or books
anything — it only displays a number. A transient rate limit or network
blip on one symbol during a long-running dashboard session should show
that one line as stale, not take down the whole monitoring session. The
failure is still surfaced (via `PortfolioTick.errors`), never masked —
this is the same "caught, but visibly noted" pattern `data/macro.py`
already uses for its optional fields, not a new kind of silence.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from trading_agent.data.providers import MarketDataProvider
from trading_agent.portfolio.schemas import AllocationLine


@dataclass
class PositionTick:
    symbol: str
    shares: int
    cost_basis_price: float
    cost_basis_dollars: float
    current_price: float
    current_value: float
    pnl_dollars: float
    pnl_pct: float
    stale: bool = False


@dataclass
class PortfolioTick:
    timestamp: float
    positions: list[PositionTick]
    cash: float
    total_value: float
    total_cost_basis: float
    total_pnl_dollars: float
    total_pnl_pct: float
    errors: dict[str, str] = field(default_factory=dict)


class PortfolioWatcher:
    """Holds the fixed cost basis (symbol -> shares, entry price) from a
    completed `portfolio` allocation and re-prices it against fresh
    snapshots on each `tick()` call."""

    def __init__(
        self,
        allocation: list[AllocationLine],
        leftover_cash: float,
        provider: MarketDataProvider,
    ) -> None:
        self._entries = [(a.symbol, a.shares, a.price) for a in allocation if a.shares > 0]
        self._cash = leftover_cash
        self._provider = provider

    def tick(self) -> PortfolioTick:
        positions: list[PositionTick] = []
        errors: dict[str, str] = {}
        total_value = self._cash
        total_cost = self._cash

        for symbol, shares, cost_basis_price in self._entries:
            cost_basis_dollars = shares * cost_basis_price
            stale = False
            try:
                current_price = self._provider.get_snapshot(symbol).last_price
            except Exception as exc:  # noqa: BLE001 - one symbol's fetch failing must not kill the tick
                errors[symbol] = str(exc)
                current_price = cost_basis_price
                stale = True

            current_value = shares * current_price
            pnl_dollars = current_value - cost_basis_dollars
            pnl_pct = (pnl_dollars / cost_basis_dollars) if cost_basis_dollars else 0.0
            positions.append(
                PositionTick(
                    symbol=symbol,
                    shares=shares,
                    cost_basis_price=cost_basis_price,
                    cost_basis_dollars=cost_basis_dollars,
                    current_price=current_price,
                    current_value=current_value,
                    pnl_dollars=pnl_dollars,
                    pnl_pct=pnl_pct,
                    stale=stale,
                )
            )
            total_value += current_value
            total_cost += cost_basis_dollars

        total_pnl_dollars = total_value - total_cost
        total_pnl_pct = (total_pnl_dollars / total_cost) if total_cost else 0.0
        return PortfolioTick(
            timestamp=time.time(),
            positions=positions,
            cash=self._cash,
            total_value=total_value,
            total_cost_basis=total_cost,
            total_pnl_dollars=total_pnl_dollars,
            total_pnl_pct=total_pnl_pct,
            errors=errors,
        )


def run_loop(
    watcher: PortfolioWatcher,
    interval_seconds: float,
    max_iterations: int | None,
    on_tick: Callable[[int, PortfolioTick], None],
) -> None:
    """Runs until `max_iterations` ticks have happened (or forever if
    None). Raises KeyboardInterrupt up to the caller on Ctrl+C rather
    than swallowing it, so the caller can print a final summary and
    exit cleanly — same contract as `engine/live_runner.run_loop`."""
    i = 0
    while max_iterations is None or i < max_iterations:
        tick = watcher.tick()
        on_tick(i, tick)
        i += 1
        if max_iterations is None or i < max_iterations:
            time.sleep(interval_seconds)
