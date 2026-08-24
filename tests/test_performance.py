import pytest

from trading_agent.engine.performance import compute_performance


def test_total_return_and_ending_equity():
    report = compute_performance([100.0, 110.0, 121.0], [])
    assert report.starting_equity == 100.0
    assert report.ending_equity == 121.0
    assert report.total_return_pct == pytest.approx(0.21)


def test_max_drawdown_from_peak():
    # up to 120, down to 90 (25% drawdown from peak), back up to 100
    report = compute_performance([100.0, 120.0, 90.0, 100.0], [])
    assert report.max_drawdown_pct == pytest.approx(0.25)


def test_win_rate_from_trade_pnls():
    report = compute_performance([100.0, 105.0], [10.0, -5.0, 3.0])
    assert report.win_rate == pytest.approx(2 / 3)


def test_win_rate_is_none_without_closed_trades():
    report = compute_performance([100.0, 105.0], [])
    assert report.win_rate is None
    assert report.num_closed_trades == 0


def test_sharpe_and_sortino_none_for_single_point():
    report = compute_performance([100.0], [])
    assert report.sharpe_ratio is None
    assert report.sortino_ratio is None


def test_sharpe_positive_for_steady_uptrend():
    curve = [100.0 * (1.01**i) for i in range(20)]
    report = compute_performance(curve, [])
    assert report.sharpe_ratio is not None
    assert report.sharpe_ratio > 0


def test_empty_equity_curve_raises():
    with pytest.raises(ValueError):
        compute_performance([], [])
