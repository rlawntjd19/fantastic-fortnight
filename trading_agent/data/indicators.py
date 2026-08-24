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
