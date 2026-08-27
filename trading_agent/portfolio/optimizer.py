"""Long-only mean-variance (max-Sharpe) allocator across the selected names.

**Expected returns come from CAPM, not the historical sample mean.**
Historical mean daily return is a famously noisy estimator of *future*
expected return — a handful of good or bad days swings it enormously,
which is the standard critique of plugging naive historical means
straight into Markowitz optimization (it tends to load up on whatever
had a lucky recent run). Historical *covariance*, by contrast, is far
more stable out-of-sample. So, in the spirit of Black-Litterman (replace
the noisy return input with a model-implied prior; keep the empirical
risk model): each asset's expected return here is
`risk_free_rate + beta * market_risk_premium` (CAPM), while volatility
and correlation still come straight from realized daily closes.

No external solver (no scipy) is available/assumed, and the whole
package stays dependency-light on purpose (see `data/indicators.py`), so
the "optimization" is an exhaustive grid search over the weight simplex
{w >= 0, sum(w) = 1} at a fixed step size — exact for the 2-5 assets this
runs over, not an approximation of a smooth solver.
"""
from __future__ import annotations

import math
from typing import Iterator

from trading_agent.portfolio import risk_metrics
from trading_agent.portfolio.schemas import OptimizationResult

TRADING_DAYS_PER_YEAR = risk_metrics.TRADING_DAYS_PER_YEAR


def capm_expected_return(beta: float | None, risk_free_rate: float, market_risk_premium: float) -> float:
    """CAPM expected annual return. A missing/undefined beta (e.g. too
    little history) falls back to beta=1 (market-like risk) rather than 0,
    since assuming zero systematic risk for an unknown equity would be the
    more misleading of the two guesses."""
    b = beta if beta is not None else 1.0
    return risk_free_rate + b * market_risk_premium


def _simplex_grid(n_assets: int, steps: int) -> Iterator[tuple[float, ...]]:
    """Every weight vector of length `n_assets` whose entries are
    multiples of 1/steps and sum to exactly 1 (long-only, fully invested)."""

    def helper(remaining: int, slots: int) -> Iterator[tuple[int, ...]]:
        if slots == 1:
            yield (remaining,)
            return
        for i in range(remaining + 1):
            for rest in helper(remaining - i, slots - 1):
                yield (i,) + rest

    for combo in helper(steps, n_assets):
        yield tuple(c / steps for c in combo)


def _annualized_covariance(symbols: list[str], daily_returns_by_symbol: dict[str, list[float]]) -> list[list[float]]:
    _, cov_daily = risk_metrics.covariance_matrix({s: daily_returns_by_symbol[s] for s in symbols})
    return [[c * TRADING_DAYS_PER_YEAR for c in row] for row in cov_daily]


def evaluate_weights(
    symbols: list[str],
    weights: dict[str, float],
    expected_annual_returns: dict[str, float],
    daily_returns_by_symbol: dict[str, list[float]],
    betas: dict[str, float | None],
    risk_free_rate: float,
) -> OptimizationResult:
    """Score one fixed weight vector (e.g. equal-weight) with the same
    return/risk/Sharpe math the optimizer maximizes over."""
    cov_annual = _annualized_covariance(symbols, daily_returns_by_symbol)
    w = [weights[s] for s in symbols]
    mu = [expected_annual_returns[s] for s in symbols]
    port_return = sum(wi * mi for wi, mi in zip(w, mu))
    port_var = sum(w[i] * w[j] * cov_annual[i][j] for i in range(len(w)) for j in range(len(w)))
    port_vol = math.sqrt(max(port_var, 0.0))
    sharpe = risk_metrics.sharpe_ratio(port_return, port_vol, risk_free_rate)
    port_beta = sum(weights[s] * (betas[s] if betas[s] is not None else 1.0) for s in symbols)
    return OptimizationResult(dict(weights), port_return, port_vol, sharpe, port_beta)


def max_sharpe_weights(
    symbols: list[str],
    expected_annual_returns: dict[str, float],
    daily_returns_by_symbol: dict[str, list[float]],
    betas: dict[str, float | None],
    risk_free_rate: float,
    weight_cap: float = 0.60,
    min_weight: float = 0.05,
    steps: int = 25,
) -> OptimizationResult:
    """Long-only max-Sharpe weights via exhaustive grid search.

    `weight_cap` bounds any single name's weight (a standard
    concentration guardrail on top of plain long-only/fully-invested,
    since an unconstrained max-Sharpe solution over a handful of assets
    can otherwise pile almost everything into the single best Sharpe
    contributor). `min_weight` is the mirror-image guardrail: plain
    Markowitz optimization is notorious for producing brittle, all-or-
    nothing corner solutions when candidates have similar estimated
    returns (small input changes flip an asset between 0% and a large
    weight) — requiring every selected name to receive at least
    `min_weight` keeps the names the Portfolio Manager already
    conviction-screened from being zeroed out by noise in the return
    estimate. `steps` sets the grid's resolution over the *remaining*
    budget after the floor (1/steps increments); the default balances
    resolution against runtime for up to 5 assets.
    """
    if not symbols:
        raise ValueError("need at least one symbol to optimize")
    n = len(symbols)
    if min_weight * n > 1.0 + 1e-9:
        raise ValueError("min_weight * number of symbols exceeds 1.0")
    if min_weight > weight_cap:
        raise ValueError("min_weight cannot exceed weight_cap")
    remaining_budget = 1.0 - min_weight * n
    cov_annual = _annualized_covariance(symbols, daily_returns_by_symbol)
    mu = [expected_annual_returns[s] for s in symbols]

    best: tuple[float, tuple[float, ...], float, float] | None = None
    for excess in _simplex_grid(n, steps):
        w = tuple(min_weight + e * remaining_budget for e in excess)
        if any(wi > weight_cap + 1e-9 for wi in w):
            continue
        port_return = sum(wi * mi for wi, mi in zip(w, mu))
        port_var = sum(w[i] * w[j] * cov_annual[i][j] for i in range(len(w)) for j in range(len(w)))
        port_vol = math.sqrt(max(port_var, 0.0))
        if port_vol == 0:
            continue
        sharpe = (port_return - risk_free_rate) / port_vol
        if best is None or sharpe > best[0]:
            best = (sharpe, w, port_return, port_vol)

    if best is None:
        # Every grid point had zero volatility (degenerate/constant price
        # history, e.g. very short synthetic test fixtures) — fall back to
        # equal weight rather than raising out of a research pipeline.
        equal = {s: 1.0 / len(symbols) for s in symbols}
        return evaluate_weights(symbols, equal, expected_annual_returns, daily_returns_by_symbol, betas, risk_free_rate)

    sharpe, w, port_return, port_vol = best
    weights = dict(zip(symbols, w))
    port_beta = sum(weights[s] * (betas[s] if betas[s] is not None else 1.0) for s in symbols)
    return OptimizationResult(weights, port_return, port_vol, sharpe, port_beta)
