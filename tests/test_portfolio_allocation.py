"""Regression coverage for performance_tracker.build_scoreboard's position
sizing: capital is weighted by conviction / realized volatility across
whichever positions are actually open (2-5, per the mandate) — not a fixed
1/5 per slot, and not a flat equal split within the basket either. A
higher-conviction and/or lower-volatility name should get more dollars
than a lower-conviction and/or higher-volatility one; agents' analysis
should actually move the sizing, not just which names get picked."""
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


def test_no_signal_falls_back_to_equal_weight():
    """With no conviction/volatility data at all (the historical/simplest
    case), sizing degrades gracefully to a flat equal split rather than
    crashing or producing a nonsensical allocation."""
    state = PortfolioState(positions=[_position(s, 100.0) for s in ["A", "B", "C", "D", "E"]])
    prices = {s: 100.0 for s in ["A", "B", "C", "D", "E"]}

    rows = build_scoreboard(state, prices, spy_current=500.0)

    assert len(rows) == 5
    for row in rows:
        assert row["weight_pct"] == 0.2

    total_invested = sum(r["allocated_value"] for r in rows)
    assert total_invested <= PORTFOLIO_CAPITAL_USD
    assert total_invested > PORTFOLIO_CAPITAL_USD * 0.9  # rounding loses only a sliver


def test_higher_conviction_gets_more_capital_at_equal_volatility():
    state = PortfolioState(positions=[_position("HIGH", 100.0), _position("LOW", 100.0)])
    prices = {"HIGH": 100.0, "LOW": 100.0}
    conviction = {"HIGH": 0.9, "LOW": 0.3}
    vol = {"HIGH": 0.20, "LOW": 0.20}

    rows = build_scoreboard(state, prices, spy_current=500.0, conviction_by_symbol=conviction, volatility_by_symbol=vol)
    by_symbol = {r["symbol"]: r for r in rows}

    assert by_symbol["HIGH"]["weight_pct"] > by_symbol["LOW"]["weight_pct"]
    # 0.9 vs 0.3 conviction at equal vol -> exactly a 3:1 weight split
    assert round(by_symbol["HIGH"]["weight_pct"], 4) == 0.75
    assert round(by_symbol["LOW"]["weight_pct"], 4) == 0.25


def test_lower_volatility_gets_more_capital_at_equal_conviction():
    state = PortfolioState(positions=[_position("CALM", 100.0), _position("WILD", 100.0)])
    prices = {"CALM": 100.0, "WILD": 100.0}
    conviction = {"CALM": 0.6, "WILD": 0.6}
    vol = {"CALM": 0.10, "WILD": 0.40}

    rows = build_scoreboard(state, prices, spy_current=500.0, conviction_by_symbol=conviction, volatility_by_symbol=vol)
    by_symbol = {r["symbol"]: r for r in rows}

    assert by_symbol["CALM"]["weight_pct"] > by_symbol["WILD"]["weight_pct"]
    # inverse-vol weighting: 1/0.10 : 1/0.40 = 4:1
    assert round(by_symbol["CALM"]["weight_pct"], 2) == 0.80
    assert round(by_symbol["WILD"]["weight_pct"], 2) == 0.20


def test_smaller_basket_still_concentrates_more_capital_per_name():
    """Two held names with typical signal should each get roughly 2.5x the
    dollars a 5-name basket with the same per-name signal would give them
    — capital isn't left idle just because the committee found fewer
    qualifying names."""
    state_5 = PortfolioState(positions=[_position(s, 100.0) for s in ["A", "B", "C", "D", "E"]])
    state_2 = PortfolioState(positions=[_position(s, 100.0) for s in ["A", "B"]])
    prices = {s: 100.0 for s in ["A", "B", "C", "D", "E"]}
    conviction = {s: 0.5 for s in ["A", "B", "C", "D", "E"]}
    vol = {s: 0.20 for s in ["A", "B", "C", "D", "E"]}

    rows_5 = build_scoreboard(state_5, prices, spy_current=500.0, conviction_by_symbol=conviction, volatility_by_symbol=vol)
    rows_2 = build_scoreboard(state_2, prices, spy_current=500.0, conviction_by_symbol=conviction, volatility_by_symbol=vol)

    assert rows_2[0]["weight_pct"] == 0.5
    assert rows_5[0]["weight_pct"] == 0.2
    assert rows_2[0]["allocated_value"] > rows_5[0]["allocated_value"] * 2


def test_missing_signal_for_one_name_falls_back_to_floor_and_default():
    """A held name build_scoreboard has no conviction/volatility data for
    this run (e.g. its price fetch failed) still gets a small, non-zero
    allocation via the floor/default constants, rather than crashing or
    getting sized to zero."""
    state = PortfolioState(positions=[_position("KNOWN", 100.0), _position("UNKNOWN", 100.0)])
    prices = {"KNOWN": 100.0, "UNKNOWN": 100.0}
    conviction = {"KNOWN": 0.8}  # UNKNOWN deliberately absent
    vol = {"KNOWN": 0.20}

    rows = build_scoreboard(state, prices, spy_current=500.0, conviction_by_symbol=conviction, volatility_by_symbol=vol)
    by_symbol = {r["symbol"]: r for r in rows}

    assert by_symbol["UNKNOWN"]["weight_pct"] > 0
    assert by_symbol["KNOWN"]["weight_pct"] > by_symbol["UNKNOWN"]["weight_pct"]


def test_empty_basket_has_no_scoreboard_rows():
    assert build_scoreboard(PortfolioState(), {}, spy_current=500.0) == []
