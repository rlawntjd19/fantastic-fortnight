import pytest

from trading_agent.portfolio.allocation import allocate_capital


def test_allocation_never_exceeds_budget():
    weights = {"A": 0.6, "B": 0.4}
    prices = {"A": 137.0, "B": 289.0}
    lines, leftover = allocate_capital(weights, prices, budget=10_000.0)

    spent = sum(l.dollars for l in lines)
    assert spent + leftover == pytest.approx(10_000.0)
    assert leftover >= 0
    for l in lines:
        assert l.dollars <= weights[l.symbol] * 10_000.0 + prices[l.symbol]


def test_allocation_tops_up_with_leftover_cash():
    # $100 target each on a $1 stock leaves a lot of headroom to top up.
    weights = {"A": 0.5, "B": 0.5}
    prices = {"A": 1.0, "B": 1.0}
    lines, leftover = allocate_capital(weights, prices, budget=101.0)

    total_shares = sum(l.shares for l in lines)
    assert total_shares == 101  # every dollar fully deployed at $1/share
    assert leftover == pytest.approx(0.0)


def test_allocation_handles_unaffordable_name_gracefully():
    weights = {"cheap": 0.5, "expensive": 0.5}
    prices = {"cheap": 10.0, "expensive": 1_000_000.0}
    lines, leftover = allocate_capital(weights, prices, budget=1_000.0)

    expensive_line = next(l for l in lines if l.symbol == "expensive")
    assert expensive_line.shares == 0
    assert leftover >= 0


def test_allocation_returns_actual_weight_matching_dollars_over_budget():
    weights = {"A": 1.0}
    prices = {"A": 50.0}
    lines, leftover = allocate_capital(weights, prices, budget=1_000.0)
    line = lines[0]
    assert line.actual_weight == pytest.approx(line.dollars / 1_000.0)
