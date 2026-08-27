from trading_agent.agents.schemas import AnalystReport, ResearchDebateResult, Signal
from trading_agent.portfolio.schemas import CandidateScore
from trading_agent.portfolio.selection import select_portfolio


def _candidate(symbol, sector, score):
    debate = ResearchDebateResult(
        bull_thesis="bull", bear_thesis="bear",
        consensus_signal=Signal.BULLISH if score > 0 else Signal.BEARISH,
        consensus_confidence=abs(score), rationale="r",
    )
    return CandidateScore(
        symbol=symbol, sector=sector, reports=[], debate=debate,
        composite_score=score, last_price=100.0, closes=[100.0, 101.0, 102.0],
    )


def test_round_one_picks_top_name_per_sector_when_diverse_enough():
    candidates = [
        _candidate("A", "Tech", 0.9),
        _candidate("B", "Tech", 0.8),  # same sector as A, should be capped out in round 1
        _candidate("C", "Financials", 0.7),
        _candidate("D", "Health Care", 0.6),
        _candidate("E", "Energy", 0.5),
    ]
    selected, rounds = select_portfolio(candidates, min_stocks=2, max_stocks=5)

    assert rounds[0].round_number == 1
    symbols = [c.symbol for c in selected]
    assert "A" in symbols  # best Tech name wins the slot
    assert "B" not in symbols  # second Tech name capped out in round 1
    assert 2 <= len(selected) <= 5


def test_falls_back_to_relaxed_rounds_when_round_one_is_too_thin():
    # Only two sectors represented -> round 1 (cap 1/sector) can supply at
    # most 2 names; if min_stocks needs 3, it must relax to round 2's cap of 2.
    candidates = [
        _candidate("A", "Tech", 0.9),
        _candidate("B", "Tech", 0.8),
        _candidate("C", "Financials", 0.7),
        _candidate("D", "Financials", 0.6),
    ]
    selected, rounds = select_portfolio(candidates, min_stocks=3, max_stocks=5)

    assert len(rounds) >= 2
    assert len(selected) >= 3


def test_fallback_round_engages_when_everything_is_bearish():
    candidates = [
        _candidate("A", "Tech", -0.5),
        _candidate("B", "Financials", -0.3),
        _candidate("C", "Energy", -0.1),
    ]
    selected, rounds = select_portfolio(candidates, min_stocks=2, max_stocks=5)

    assert len(selected) == 2
    assert "Fallback" in rounds[-1].notes
    # Least-bearish first: C (-0.1) then B (-0.3), both ahead of A (-0.5).
    assert selected[0].symbol == "C" and selected[1].symbol == "B"


def test_never_exceeds_max_stocks():
    candidates = [_candidate(f"S{i}", f"Sector{i}", 0.9 - i * 0.01) for i in range(10)]
    selected, _ = select_portfolio(candidates, min_stocks=2, max_stocks=4)
    assert len(selected) == 4


def test_invalid_bounds_raise():
    import pytest

    with pytest.raises(ValueError):
        select_portfolio([], min_stocks=5, max_stocks=2)
