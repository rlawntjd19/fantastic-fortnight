import pytest

from trading_agent.data.indicators import momentum, rsi, sma


def test_sma_basic():
    assert sma([1, 2, 3, 4, 5], 3) == (3 + 4 + 5) / 3


def test_sma_insufficient_data_returns_none():
    assert sma([1, 2], 5) is None


def test_rsi_all_gains_is_100():
    values = [float(i) for i in range(1, 20)]  # strictly increasing
    assert rsi(values, 14) == 100.0


def test_rsi_insufficient_data_returns_none():
    assert rsi([1, 2, 3], 14) is None


def test_momentum_positive():
    values = [100.0] * 5 + [110.0]
    assert momentum(values, 5) == pytest.approx(0.10)
