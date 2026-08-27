import pytest

from trading_agent.portfolio.forward_simulation import monte_carlo_forward


def _flat_returns(symbols, n=100):
    return {s: [0.0] * n for s in symbols}


def test_forward_simulation_is_deterministic_for_a_fixed_seed():
    symbols = ["A", "B"]
    weights = {"A": 0.5, "B": 0.5}
    drift = {"A": 0.0005, "B": 0.0003}
    returns = _flat_returns(symbols)

    r1 = monte_carlo_forward(symbols, weights, drift, returns, 25_000.0, horizon_days=21, num_paths=200, seed=7)
    r2 = monte_carlo_forward(symbols, weights, drift, returns, 25_000.0, horizon_days=21, num_paths=200, seed=7)

    assert r1.expected_return_pct == pytest.approx(r2.expected_return_pct)
    assert r1.p5_return_pct == pytest.approx(r2.p5_return_pct)


def test_forward_simulation_zero_vol_zero_drift_stays_flat():
    symbols = ["A"]
    weights = {"A": 1.0}
    drift = {"A": 0.0}
    returns = _flat_returns(symbols)

    result = monte_carlo_forward(symbols, weights, drift, returns, 10_000.0, horizon_days=30, num_paths=50, seed=1)

    assert result.expected_return_pct == pytest.approx(0.0, abs=1e-9)
    assert result.prob_positive == pytest.approx(0.0)
    assert result.expected_ending_value == pytest.approx(10_000.0)


def test_forward_simulation_probability_between_zero_and_one():
    symbols = ["A", "B", "C"]
    weights = {"A": 0.4, "B": 0.3, "C": 0.3}
    drift = {"A": 0.001, "B": 0.0005, "C": -0.0002}
    returns = {
        "A": [0.01, -0.005, 0.008, 0.002] * 20,
        "B": [0.005, 0.001, -0.003, 0.004] * 20,
        "C": [-0.002, 0.003, 0.001, -0.001] * 20,
    }
    result = monte_carlo_forward(symbols, weights, drift, returns, 25_000.0, horizon_days=63, num_paths=300, seed=3)

    assert 0.0 <= result.prob_positive <= 1.0
    assert result.p5_return_pct <= result.median_return_pct <= result.p95_return_pct
    assert result.horizon_days == 63
    assert result.num_paths == 300
