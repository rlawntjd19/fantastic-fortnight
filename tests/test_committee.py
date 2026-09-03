import datetime as dt

from trading_agent.committee.daily_report import RESEARCH_WINDOW_END, run_daily_cycle
from trading_agent.committee.schemas import PortfolioState
from trading_agent.committee.universe import MIN_MARKET_CAP_USD, screen_ineligible, UniverseEntry
from trading_agent.config import DEFAULT_CONFIG
from trading_agent.data.macro import StaticMacroProvider
from trading_agent.data.providers import SimulatedFeed
from trading_agent.forecast.heuristic_forecaster import HeuristicForecaster
from trading_agent.llm.client import DummyLLMClient


def _run(run_date=dt.date(2026, 8, 31), state=None, seed=7):
    return run_daily_cycle(
        DEFAULT_CONFIG,
        DummyLLMClient(),
        SimulatedFeed(seed=seed),
        StaticMacroProvider(),
        HeuristicForecaster(),
        state or PortfolioState(),
        run_date=run_date,
    )


def test_daily_cycle_produces_the_fixed_three_name_basket():
    report = _run()
    assert len(report.open_positions) == 3
    assert len(report.entries) == len(report.open_positions)


def test_daily_cycle_is_idempotent_on_a_full_basket():
    state = PortfolioState()
    first = _run(state=state)
    assert len(state.open_positions) == len(first.open_positions)

    second = _run(run_date=dt.date(2026, 9, 1), state=state)
    # A full basket with no thesis break should see no new entries.
    assert second.entries == [] or len(state.open_positions) <= 3
    assert len(state.open_positions) <= 3


def test_window_closed_holds_basket_without_new_screening():
    state = PortfolioState()
    _run(state=state)
    held_before = {p.symbol for p in state.open_positions}

    past_cutoff = RESEARCH_WINDOW_END + dt.timedelta(days=3)
    report = _run(run_date=past_cutoff, state=state)

    assert report.entries == []
    assert report.candidates == []
    assert {p.symbol for p in state.open_positions} == held_before


def test_screen_ineligible_rejects_mutual_fund_pattern_and_penny_price():
    mutual_fund = UniverseEntry("VFIAX", "stock", "Broad Market")
    assert screen_ineligible(mutual_fund, {}, 100.0) is not None

    index_ticker = UniverseEntry("^GSPC", "index_etf", "Broad Market")
    assert screen_ineligible(index_ticker, {}, 5000.0) is not None

    penny = UniverseEntry("AAPL", "stock", "Technology")
    assert screen_ineligible(penny, {}, 1.00) is not None

    small_cap = UniverseEntry("AAPL", "stock", "Technology")
    assert screen_ineligible(small_cap, {"market_cap": MIN_MARKET_CAP_USD - 1}, 50.0) is not None

    eligible = UniverseEntry("AAPL", "stock", "Technology")
    assert screen_ineligible(eligible, {"market_cap": MIN_MARKET_CAP_USD + 1}, 50.0) is None


def test_offline_run_never_crashes_with_no_llm_or_network():
    # SimulatedFeed + DummyLLMClient + StaticMacroProvider + HeuristicForecaster
    # is the fully offline path every other test in this repo also exercises.
    report = _run()
    assert report.run_date == "2026-08-31"
    assert report.universe_size > 0


def test_one_symbols_analysis_crashing_does_not_kill_the_whole_run(monkeypatch):
    # A real crash happened in production from a bad data point deep inside
    # one symbol's analysis (a NaN close reaching statistics.pstdev) taking
    # down an entire live run. That specific bug is fixed at its source
    # (forecast/heuristic_forecaster.py, data/indicators.py), but this is
    # the "one bad symbol must not kill the whole run" guarantee itself,
    # independent of any one root cause.
    import trading_agent.committee.daily_report as daily_report_module

    real_assess = daily_report_module.assess_symbol

    def _flaky_assess(entry, snapshot, spy_momentum, analysts, research_manager):
        if entry.symbol == "AAPL":
            raise ValueError("synthetic failure for this test")
        return real_assess(entry, snapshot, spy_momentum, analysts, research_manager)

    monkeypatch.setattr(daily_report_module, "assess_symbol", _flaky_assess)

    report = _run()
    assert any("AAPL" in note and "failed" in note for note in report.screened_out)
    assert len(report.open_positions) == 3  # basket still fills from the rest of the universe
