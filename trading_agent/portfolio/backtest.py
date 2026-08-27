"""Replay the trailing historical window with fixed target weights and a
periodic rebalance, the standard way to sanity-check a proposed static
allocation against what already happened — never a promise about what
happens next (see `forward_simulation.py` for the actual forward-looking
piece). Distinct from `engine/backtest.py`, which replays the single-
symbol leveraged-trading pipeline bar by bar; this is a buy/hold-with-
rebalance replay of a fixed weight vector across several symbols.
"""
from __future__ import annotations

from trading_agent.portfolio import risk_metrics
from trading_agent.portfolio.schemas import PortfolioBacktestResult


def run_portfolio_backtest(
    closes_by_symbol: dict[str, list[float]],
    weights: dict[str, float],
    budget: float,
    benchmark_closes: list[float] | None = None,
    rebalance_every: int = 21,
    risk_free_rate: float = 0.045,
) -> PortfolioBacktestResult:
    symbols = list(weights)
    n = min(len(closes_by_symbol[s]) for s in symbols)
    if n < 2:
        raise ValueError("need at least 2 aligned bars to backtest")
    closes = {s: closes_by_symbol[s][-n:] for s in symbols}

    shares = {s: (weights[s] * budget) / closes[s][0] for s in symbols}
    equity_curve: list[float] = []
    for t in range(n):
        if t > 0 and rebalance_every and t % rebalance_every == 0:
            equity_t = sum(shares[s] * closes[s][t] for s in symbols)
            shares = {s: (weights[s] * equity_t) / closes[s][t] for s in symbols}
        equity_curve.append(sum(shares[s] * closes[s][t] for s in symbols))

    port_returns = [equity_curve[i] / equity_curve[i - 1] - 1 for i in range(1, n) if equity_curve[i - 1] != 0]
    total_return = equity_curve[-1] / equity_curve[0] - 1 if equity_curve[0] else 0.0
    ann_return = risk_metrics.annualize_return(risk_metrics.mean(port_returns))
    ann_vol = risk_metrics.annualize_vol(risk_metrics.stdev(port_returns))
    sharpe = risk_metrics.sharpe_ratio(ann_return, ann_vol, risk_free_rate)

    realized_beta = None
    treynor = None
    bench_curve = None
    if benchmark_closes and len(benchmark_closes) >= n:
        bench = benchmark_closes[-n:]
        bench_curve = [budget * (b / bench[0]) for b in bench] if bench[0] else None
        bench_returns = [bench[i] / bench[i - 1] - 1 for i in range(1, n) if bench[i - 1] != 0]
        realized_beta = risk_metrics.beta(port_returns, bench_returns)
        treynor = risk_metrics.treynor_ratio(ann_return, realized_beta, risk_free_rate)

    return PortfolioBacktestResult(
        starting_equity=equity_curve[0],
        ending_equity=equity_curve[-1],
        total_return_pct=total_return,
        annualized_return_pct=ann_return,
        annualized_vol_pct=ann_vol,
        max_drawdown_pct=risk_metrics.max_drawdown(equity_curve),
        sharpe_ratio=sharpe,
        realized_beta=realized_beta,
        treynor_ratio=treynor,
        equity_curve=equity_curve,
        benchmark_equity_curve=bench_curve,
        num_bars=n,
    )
