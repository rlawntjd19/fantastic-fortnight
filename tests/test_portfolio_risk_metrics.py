import pytest

from trading_agent.portfolio import risk_metrics


def test_daily_returns_basic():
    assert risk_metrics.daily_returns([100.0, 110.0, 99.0]) == pytest.approx([0.10, -0.10])


def test_stdev_zero_for_constant_series():
    assert risk_metrics.stdev([1.0, 1.0, 1.0]) == 0.0


def test_covariance_symmetric():
    a = [0.01, -0.02, 0.03, 0.0]
    b = [0.02, -0.01, 0.02, 0.01]
    assert risk_metrics.covariance(a, b) == pytest.approx(risk_metrics.covariance(b, a))


def test_correlation_of_series_with_itself_is_one():
    a = [0.01, -0.02, 0.03, 0.04, -0.01]
    assert risk_metrics.correlation(a, a) == pytest.approx(1.0)


def test_beta_of_market_with_itself_is_one():
    market = [0.01, -0.02, 0.03, 0.04, -0.01, 0.02]
    assert risk_metrics.beta(market, market) == pytest.approx(1.0)


def test_beta_scales_linearly():
    market = [0.01, -0.02, 0.03, 0.04, -0.01, 0.02]
    double = [2 * r for r in market]
    assert risk_metrics.beta(double, market) == pytest.approx(2.0)


def test_beta_none_when_market_has_no_variance():
    assert risk_metrics.beta([0.01, 0.02], [0.0, 0.0]) is None


def test_sharpe_ratio_none_for_zero_vol():
    assert risk_metrics.sharpe_ratio(0.10, 0.0, 0.02) is None


def test_sharpe_ratio_basic():
    assert risk_metrics.sharpe_ratio(0.10, 0.20, 0.02) == pytest.approx(0.4)


def test_treynor_ratio_none_for_zero_beta():
    assert risk_metrics.treynor_ratio(0.10, 0.0, 0.02) is None
    assert risk_metrics.treynor_ratio(0.10, None, 0.02) is None


def test_treynor_ratio_basic():
    assert risk_metrics.treynor_ratio(0.10, 2.0, 0.02) == pytest.approx(0.04)


def test_max_drawdown_from_peak():
    assert risk_metrics.max_drawdown([100.0, 120.0, 90.0, 100.0]) == pytest.approx(0.25)


def test_max_drawdown_empty_curve():
    assert risk_metrics.max_drawdown([]) == 0.0


def test_covariance_matrix_shape_and_diagonal():
    returns = {"A": [0.01, 0.02, -0.01, 0.03], "B": [0.02, 0.01, 0.00, 0.01]}
    symbols, matrix = risk_metrics.covariance_matrix(returns)
    assert symbols == ["A", "B"]
    assert len(matrix) == 2 and len(matrix[0]) == 2
    assert matrix[0][0] == pytest.approx(risk_metrics.covariance(returns["A"], returns["A"]))
    assert matrix[0][1] == pytest.approx(matrix[1][0])
