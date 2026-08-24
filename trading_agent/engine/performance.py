"""Performance metrics computed from an equity curve and closed-trade PnLs.

Purely descriptive statistics about what already happened in a run
(live `watch` session or `backtest` replay) — nothing here forecasts or
promises anything about the future. Sharpe/Sortino here are *per-tick*
ratios assuming a zero risk-free rate, not annualized figures comparable
to a fund's reported Sharpe ratio; they're a relative diagnostic for
"did this run's return look steady or lumpy," not a rigorous industry
metric.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class PerformanceReport:
    starting_equity: float
    ending_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    win_rate: float | None
    sharpe_ratio: float | None
    sortino_ratio: float | None
    num_closed_trades: int


def compute_performance(equity_curve: list[float], trade_pnls: list[float]) -> PerformanceReport:
    if not equity_curve:
        raise ValueError("equity_curve must have at least one point")

    starting = equity_curve[0]
    ending = equity_curve[-1]
    total_return_pct = (ending / starting - 1) if starting else 0.0

    peak = equity_curve[0]
    max_drawdown = 0.0
    for e in equity_curve:
        peak = max(peak, e)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - e) / peak)

    period_returns = [
        equity_curve[i] / equity_curve[i - 1] - 1
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] != 0
    ]

    win_rate = None
    if trade_pnls:
        win_rate = sum(1 for p in trade_pnls if p > 0) / len(trade_pnls)

    return PerformanceReport(
        starting_equity=starting,
        ending_equity=ending,
        total_return_pct=total_return_pct,
        max_drawdown_pct=max_drawdown,
        win_rate=win_rate,
        sharpe_ratio=_sharpe(period_returns),
        sortino_ratio=_sortino(period_returns),
        num_closed_trades=len(trade_pnls),
    )


def _stdev(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def _sharpe(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    stdev = _stdev(returns)
    if stdev == 0:
        return None
    mean = sum(returns) / len(returns)
    return (mean / stdev) * math.sqrt(len(returns))


def _sortino(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    downside = [min(0.0, r) for r in returns]
    downside_dev = math.sqrt(sum(d**2 for d in downside) / (len(downside) - 1))
    if downside_dev == 0:
        return None
    mean = sum(returns) / len(returns)
    return (mean / downside_dev) * math.sqrt(len(returns))
