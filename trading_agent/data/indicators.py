"""Small, dependency-light technical indicator helpers.

Deliberately implemented without pandas/numpy so the whole package has
zero hard runtime dependencies beyond the optional `anthropic` client.
"""
from __future__ import annotations


def sma(values: list[float], window: int) -> float | None:
    """Simple moving average of the last `window` values."""
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def rsi(values: list[float], window: int = 14) -> float | None:
    """Wilder-style relative strength index over the last `window` changes."""
    if len(values) < window + 1:
        return None
    changes = [values[i] - values[i - 1] for i in range(len(values) - window, len(values))]
    gains = [c for c in changes if c > 0]
    losses = [-c for c in changes if c < 0]
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def momentum(values: list[float], window: int) -> float | None:
    """Percent change over the last `window` bars."""
    if len(values) < window + 1:
        return None
    base = values[-window - 1]
    if base == 0:
        return None
    return (values[-1] - base) / base


def volatility(values: list[float], window: int = 20) -> float | None:
    """Annualized standard deviation of daily returns over the last
    `window` bars — a simple realized-volatility estimate. This is the
    risk term in the committee's conviction/risk position sizing
    (`committee/performance_tracker.build_scoreboard`): a name with more
    conviction *and* less realized volatility gets more capital per the
    same idea real risk-parity/vol-targeting position sizing uses, not
    equal-weight regardless of how risky each name actually is.
    """
    if len(values) < window + 1:
        return None
    changes = [
        (values[i] - values[i - 1]) / values[i - 1]
        for i in range(len(values) - window, len(values))
        if values[i - 1] != 0
    ]
    if len(changes) < 2:
        return None
    mean = sum(changes) / len(changes)
    variance = sum((c - mean) ** 2 for c in changes) / (len(changes) - 1)
    return variance**0.5 * 252**0.5
