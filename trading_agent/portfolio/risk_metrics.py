"""Portfolio-theory statistics: annualized return/vol, covariance/
correlation, CAPM beta, Sharpe, Treynor, max drawdown.

Pure Python (no numpy/pandas), matching the zero-dependency style of
`trading_agent/data/indicators.py` — the asset counts here (2-14 symbols,
a few hundred daily bars) make that entirely fast enough, and it keeps
this module runnable in every environment the rest of the package runs in.
"""
from __future__ import annotations

import math

TRADING_DAYS_PER_YEAR = 252


def daily_returns(closes: list[float]) -> list[float]:
    """Simple (not log) daily returns, skipping any zero-price bar."""
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1] != 0]


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def annualize_return(daily_mean: float) -> float:
    return (1 + daily_mean) ** TRADING_DAYS_PER_YEAR - 1


def annualize_vol(daily_std: float) -> float:
    return daily_std * math.sqrt(TRADING_DAYS_PER_YEAR)


def covariance(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    a, b = a[:n], b[:n]
    ma, mb = mean(a), mean(b)
    return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / (n - 1)


def correlation(a: list[float], b: list[float]) -> float:
    sa, sb = stdev(a), stdev(b)
    if sa == 0 or sb == 0:
        return 0.0
    return covariance(a, b) / (sa * sb)


def covariance_matrix(returns_by_symbol: dict[str, list[float]]) -> tuple[list[str], list[list[float]]]:
    symbols = list(returns_by_symbol)
    n = len(symbols)
    matrix = [
        [covariance(returns_by_symbol[symbols[i]], returns_by_symbol[symbols[j]]) for j in range(n)]
        for i in range(n)
    ]
    return symbols, matrix


def beta(asset_returns: list[float], market_returns: list[float]) -> float | None:
    """CAPM beta of `asset_returns` against `market_returns` (aligned by
    truncating to the shorter series' length, most-recent-aligned)."""
    n = min(len(asset_returns), len(market_returns))
    if n < 2:
        return None
    a, m = asset_returns[-n:], market_returns[-n:]
    var_m = covariance(m, m)
    if var_m == 0:
        return None
    return covariance(a, m) / var_m


def sharpe_ratio(annual_return: float, annual_vol: float, risk_free_rate: float) -> float | None:
    if annual_vol == 0:
        return None
    return (annual_return - risk_free_rate) / annual_vol


def treynor_ratio(annual_return: float, portfolio_beta: float | None, risk_free_rate: float) -> float | None:
    if not portfolio_beta:
        return None
    return (annual_return - risk_free_rate) / portfolio_beta


def max_drawdown(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    mdd = 0.0
    for e in equity_curve:
        peak = max(peak, e)
        if peak > 0:
            mdd = max(mdd, (peak - e) / peak)
    return mdd
