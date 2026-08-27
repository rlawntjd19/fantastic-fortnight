"""Forward-looking 3-month projection via Monte Carlo.

This is deliberately kept separate from `backtest.py`: a backtest can
only replay days that already happened, so it can never be "the next 3
months" — this module is the piece that actually answers that question,
by simulating many possible future paths rather than asserting one.

Each simulated day draws a correlated shock per asset (via a Cholesky
factorization of the historical daily covariance matrix, so simulated
assets move together the way the real ones have been) on top of a CAPM-
implied daily drift (see `optimizer.py`'s module docstring for why CAPM
rather than the historical sample mean). Aggregating thousands of such
paths into a distribution, rather than reporting one point forecast, is
what lets the report state a probability of gain and a percentile range
instead of a single misleadingly precise number.
"""
from __future__ import annotations

import math
import random

from trading_agent.portfolio import risk_metrics
from trading_agent.portfolio.schemas import ForwardSimulationResult

TRADING_DAYS_PER_QUARTER = 63  # ~3 months of trading days


def _cholesky(matrix: list[list[float]]) -> list[list[float]]:
    n = len(matrix)
    lower = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            partial = sum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                lower[i][j] = math.sqrt(max(matrix[i][i] - partial, 0.0))
            else:
                lower[i][j] = (matrix[i][j] - partial) / lower[j][j] if lower[j][j] != 0 else 0.0
    return lower


def monte_carlo_forward(
    symbols: list[str],
    weights: dict[str, float],
    daily_drift: dict[str, float],
    daily_returns_by_symbol: dict[str, list[float]],
    starting_value: float,
    horizon_days: int = TRADING_DAYS_PER_QUARTER,
    num_paths: int = 2000,
    seed: int = 42,
) -> ForwardSimulationResult:
    n = len(symbols)
    _, cov = risk_metrics.covariance_matrix({s: daily_returns_by_symbol[s] for s in symbols})
    lower = _cholesky(cov)
    rng = random.Random(seed)
    mu = [daily_drift[s] for s in symbols]
    start_dollars = [weights[s] * starting_value for s in symbols]

    finals: list[float] = []
    for _ in range(num_paths):
        holdings = list(start_dollars)
        for _day in range(horizon_days):
            z = [rng.gauss(0.0, 1.0) for _ in range(n)]
            shocks = [sum(lower[i][k] * z[k] for k in range(i + 1)) for i in range(n)]
            for i in range(n):
                holdings[i] *= 1 + mu[i] + shocks[i]
        finals.append(sum(holdings))

    finals.sort()
    returns = [f / starting_value - 1 for f in finals] if starting_value else [0.0] * len(finals)
    m = len(returns)
    expected = sum(returns) / m
    median = returns[m // 2]
    p5 = returns[max(0, int(0.05 * m))]
    p95 = returns[min(m - 1, int(0.95 * m))]
    prob_positive = sum(1 for r in returns if r > 0) / m

    return ForwardSimulationResult(
        horizon_days=horizon_days,
        num_paths=num_paths,
        expected_return_pct=expected,
        median_return_pct=median,
        p5_return_pct=p5,
        p95_return_pct=p95,
        prob_positive=prob_positive,
        expected_ending_value=starting_value * (1 + expected),
        starting_value=starting_value,
    )
