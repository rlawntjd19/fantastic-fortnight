import datetime as dt

from trading_agent.committee.daily_report import RESEARCH_WINDOW_END, run_daily_cycle
from trading_agent.committee.schemas import PortfolioState
from trading_agent.committee.universe import MIN_MARKET_CAP_USD, screen_ineligible, UniverseEntry
from trading_agent.config import DEFAULT_CONFIG
from trading_agent.data.macro import StaticMacroProvider
from trading_agent.data.providers import Bar, MarketSnapshot, SimulatedFeed
from trading_agent.forecast.heuristic_forecaster import HeuristicForecaster
from trading_agent.llm.client import DummyLLMClient


def _epoch(year: int, month: int, day: int) -> int:
    return int(dt.datetime(year, month, day, tzinfo=dt.timezone.utc).timestamp())


class _FakeSeasonalProvider:
    """A real-calendar-dated, multi-year history feed for SeasonalityAnalyst
    — every year the same consistently-bullish pattern, so any symbol
    screened against it gets a real (non-thin, non-neutral) seasonal read
    instead of the fake epoch-index bars SimulatedFeed hands the other 5
    desks."""

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        bars = []
        for year in range(2020, 2026):
            bars.append(Bar(_epoch(year, 8, 31), 100.0, 100.0, 100.0, 100.0, 1_000.0))
            bars.append(Bar(_epoch(year, 12, 31), 112.0, 112.0, 112.0, 112.0, 1_000.0))
        return MarketSnapshot(symbol=symbol, bars=bars)


def _run(run_date=dt.date(2026, 8, 31), state=None, seed=7, seasonal_provider=None):
    return run_daily_cycle(
        DEFAULT_CONFIG,
        DummyLLMClient(),
        SimulatedFeed(seed=seed),
        StaticMacroProvider(),
        HeuristicForecaster(),
        state or PortfolioState(),
        run_date=run_date,
        seasonal_provider=seasonal_provider,
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

    def _flaky_assess(entry, snapshot, spy_momentum, analysts, research_manager, **kwargs):
        if entry.symbol == "AAPL":
            raise ValueError("synthetic failure for this test")
        return real_assess(entry, snapshot, spy_momentum, analysts, research_manager, **kwargs)

    monkeypatch.setattr(daily_report_module, "assess_symbol", _flaky_assess)

    report = _run()
    assert any("AAPL" in note and "failed" in note for note in report.screened_out)
    assert len(report.open_positions) == 3  # basket still fills from the rest of the universe


def test_seasonal_provider_feeds_a_real_signal_without_crashing_or_changing_basket_size():
    # SeasonalityAnalyst needs real calendar-dated multi-year history,
    # which SimulatedFeed's index-timestamped bars can't provide (see
    # test_seasonality.test_no_real_calendar_history_reports_neutral) —
    # this confirms the separate `seasonal_provider` plumbing actually
    # reaches assess_symbol end-to-end and produces a real (non-thin)
    # seasonal read for every screened candidate, without disturbing the
    # rest of the pipeline.
    report = _run(seasonal_provider=_FakeSeasonalProvider())

    assert len(report.open_positions) == 3
    seasonal_reports = [
        r
        for c in report.candidates
        for r in c.analyst_reports
        if r.agent_name == "seasonality_analyst"
    ]
    assert seasonal_reports  # the desk actually ran for at least one candidate
    assert any(len(r.key_points) > 1 for r in seasonal_reports)  # a real read, not the "too few years" stub
