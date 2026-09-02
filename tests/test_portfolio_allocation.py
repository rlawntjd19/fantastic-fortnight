"""Regression coverage for performance_tracker.build_scoreboard's
equal-weight allocation: capital is split across whichever positions are
actually open (2-5, per the mandate), not a fixed 1/5 per slot — so a
smaller basket puts more capital into each name rather than leaving cash
idle."""
from trading_agent.committee.performance_tracker import PORTFOLIO_CAPITAL_USD, build_scoreboard
from trading_agent.committee.schemas import PortfolioState, Position


def _position(symbol: str, entry_price: float) -> Position:
    return Position(
        symbol=symbol,
        security_type="stock",
        entry_date="2026-09-01",
        entry_price=entry_price,
        benchmark_entry_price=500.0,
        thesis="test",
    )


def test_full_basket_splits_capital_five_ways():
    state = PortfolioState(positions=[_position(s, 100.0) for s in ["A", "B", "C", "D", "E"]])
    prices = {s: 100.0 for s in ["A", "B", "C", "D", "E"]}

    rows = build_scoreboard(state, prices, spy_current=500.0)

    assert len(rows) == 5
    for row in rows:
        assert row["weight_pct"] == 0.2
        assert row["shares"] == PORTFOLIO_CAPITAL_USD / 5 // 100.0

    total_invested = sum(r["allocated_value"] for r in rows)
    assert total_invested <= PORTFOLIO_CAPITAL_USD
    assert total_invested > PORTFOLIO_CAPITAL_USD * 0.9  # rounding loses only a sliver


def test_smaller_basket_concentrates_more_capital_per_name():
    """Two held names should each get roughly 2.5x the dollars a 5-name
    basket would give them — capital isn't left idle just because the
    committee found fewer qualifying names."""
    state_5 = PortfolioState(positions=[_position(s, 100.0) for s in ["A", "B", "C", "D", "E"]])
    state_2 = PortfolioState(positions=[_position(s, 100.0) for s in ["A", "B"]])
    prices = {s: 100.0 for s in ["A", "B", "C", "D", "E"]}

    rows_5 = build_scoreboard(state_5, prices, spy_current=500.0)
    rows_2 = build_scoreboard(state_2, prices, spy_current=500.0)

    assert rows_2[0]["weight_pct"] == 0.5
    assert rows_5[0]["weight_pct"] == 0.2
    assert rows_2[0]["allocated_value"] > rows_5[0]["allocated_value"] * 2


def test_empty_basket_has_no_scoreboard_rows():
    assert build_scoreboard(PortfolioState(), {}, spy_current=500.0) == []
