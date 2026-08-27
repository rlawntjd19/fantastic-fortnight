import pytest

from trading_agent.portfolio.backtest import run_portfolio_backtest


def test_backtest_equal_growth_matches_expected_total_return():
    # Both names grow 1%/day for 50 days; with no rebalance needed (already
    # balanced), the portfolio should also grow ~1%/day.
    closes = {
        "A": [100.0 * (1.01**i) for i in range(50)],
        "B": [50.0 * (1.01**i) for i in range(50)],
    }
    weights = {"A": 0.5, "B": 0.5}
    result = run_portfolio_backtest(closes, weights, budget=10_000.0, rebalance_every=0)

    assert result.starting_equity == pytest.approx(10_000.0)
    expected_total_return = 1.01**49 - 1
    assert result.total_return_pct == pytest.approx(expected_total_return, rel=1e-6)
    assert result.sharpe_ratio is not None
    assert result.sharpe_ratio > 0


def test_backtest_computes_beta_and_treynor_against_benchmark():
    # A varying (not near-constant) path so the covariance/variance ratio
    # is well-conditioned; identical to the benchmark path -> beta == 1.
    import random

    rng = random.Random(3)
    path = [100.0]
    for _ in range(59):
        path.append(path[-1] * (1 + rng.uniform(-0.02, 0.02)))
    closes = {"A": list(path)}
    benchmark = list(path)
    result = run_portfolio_backtest(closes, {"A": 1.0}, budget=25_000.0, benchmark_closes=benchmark)

    assert result.realized_beta == pytest.approx(1.0, abs=1e-6)
    assert result.treynor_ratio is not None


def test_backtest_max_drawdown_reflects_a_dip():
    closes = {"A": [100.0, 120.0, 90.0, 100.0]}
    result = run_portfolio_backtest(closes, {"A": 1.0}, budget=1_000.0, rebalance_every=0)
    assert result.max_drawdown_pct == pytest.approx(0.25)


def test_backtest_requires_at_least_two_bars():
    with pytest.raises(ValueError):
        run_portfolio_backtest({"A": [100.0]}, {"A": 1.0}, budget=1_000.0)
