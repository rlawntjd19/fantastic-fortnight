import random

import pytest

from trading_agent.portfolio.optimizer import capm_expected_return, evaluate_weights, max_sharpe_weights


def _synthetic_returns(symbols, n=120, seed=1):
    rng = random.Random(seed)
    return {s: [rng.gauss(0.0005, 0.01) for _ in range(n)] for s in symbols}


def test_capm_expected_return_uses_beta_and_premium():
    r = capm_expected_return(beta=1.5, risk_free_rate=0.04, market_risk_premium=0.05)
    assert r == pytest.approx(0.04 + 1.5 * 0.05)


def test_capm_expected_return_defaults_missing_beta_to_one():
    assert capm_expected_return(None, 0.04, 0.05) == pytest.approx(0.09)


def test_max_sharpe_weights_sum_to_one_and_respect_bounds():
    symbols = ["A", "B", "C"]
    returns = _synthetic_returns(symbols)
    betas = {"A": 1.2, "B": 0.8, "C": 1.0}
    mu = {s: capm_expected_return(betas[s], 0.045, 0.05) for s in symbols}

    result = max_sharpe_weights(
        symbols, mu, returns, betas, risk_free_rate=0.045, weight_cap=0.6, min_weight=0.05, steps=20
    )

    assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-6)
    for w in result.weights.values():
        assert 0.05 - 1e-6 <= w <= 0.6 + 1e-6
    assert set(result.weights) == set(symbols)
    assert result.sharpe_ratio is not None


def test_max_sharpe_weights_min_weight_floor_is_enforced():
    symbols = ["A", "B", "C", "D"]
    returns = _synthetic_returns(symbols)
    betas = {s: 1.0 for s in symbols}
    mu = {s: 0.08 for s in symbols}

    result = max_sharpe_weights(
        symbols, mu, returns, betas, risk_free_rate=0.045, weight_cap=0.9, min_weight=0.10, steps=20
    )
    for w in result.weights.values():
        assert w >= 0.10 - 1e-6


def test_max_sharpe_weights_rejects_infeasible_min_weight():
    symbols = ["A", "B", "C"]
    returns = _synthetic_returns(symbols)
    betas = {s: 1.0 for s in symbols}
    mu = {s: 0.08 for s in symbols}
    with pytest.raises(ValueError):
        max_sharpe_weights(symbols, mu, returns, betas, risk_free_rate=0.045, min_weight=0.5, steps=10)


def test_evaluate_weights_matches_manual_equal_weight_math():
    symbols = ["A", "B"]
    returns = _synthetic_returns(symbols)
    betas = {"A": 1.0, "B": 1.0}
    mu = {"A": 0.09, "B": 0.09}
    weights = {"A": 0.5, "B": 0.5}

    result = evaluate_weights(symbols, weights, mu, returns, betas, risk_free_rate=0.045)
    assert result.expected_annual_return == pytest.approx(0.09)
    assert result.portfolio_beta == pytest.approx(1.0)
