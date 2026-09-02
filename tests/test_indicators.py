import pytest

from trading_agent.data.indicators import momentum, rsi, sma, volatility


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


def test_volatility_flat_prices_is_zero():
    assert volatility([100.0] * 25, 20) == pytest.approx(0.0)


def test_volatility_more_dispersed_returns_is_higher():
    calm = [100.0, 101.0, 100.0, 101.0] * 6
    wild = [100.0, 120.0, 100.0, 120.0] * 6
    assert volatility(wild, 20) > volatility(calm, 20)


def test_volatility_insufficient_data_returns_none():
    assert volatility([1.0, 2.0, 3.0], 20) is None
