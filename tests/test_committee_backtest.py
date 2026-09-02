"""Regression coverage for trading_agent/committee/backtest.py, entirely
offline (synthetic price/macro series, DummyLLMClient, HeuristicForecaster)
— the only part of this module that needs real network is
fetch_backtest_data(), which isn't exercised here."""
import datetime as dt

import pytest

from trading_agent.committee.backtest import (
    BacktestData,
    BacktestReport,
    MacroHistory,
    SymbolHistory,
    TimeSeries,
    TrialResult,
    HistoricalMacroProvider,
    _weighted_alpha,
    run_backtest,
    summarize,
    to_markdown,
)
from trading_agent.committee.daily_report import OKR_TARGET_LOW_PP
from trading_agent.committee.universe import BENCHMARK_SYMBOL, UNIVERSE
from trading_agent.data.providers import Bar
from trading_agent.forecast.heuristic_forecaster import HeuristicForecaster
from trading_agent.llm.client import DummyLLMClient

_DAY = 86400
_BASE_TS = int(dt.datetime(2023, 1, 2, tzinfo=dt.timezone.utc).timestamp())


def _bars(n: int, prices: list[float]) -> list[Bar]:
    assert len(prices) == n
    return [
        Bar(timestamp=_BASE_TS + i * _DAY, open=p, high=p * 1.01, low=p * 0.99, close=p, volume=1000.0)
        for i, p in enumerate(prices)
    ]


def _flat(n: int, level: float = 100.0) -> list[float]:
    return [level] * n


def _trending(n: int, start: float, daily_drift: float) -> list[float]:
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + daily_drift))
    return prices


class TestTimeSeries:
    def test_as_of_returns_most_recent_value_not_after_cutoff(self):
        ts = TimeSeries(dates=[100, 200, 300], values=[1.0, 2.0, 3.0])
        assert ts.as_of(250) == 2.0
        assert ts.as_of(300) == 3.0
        assert ts.as_of(50) is None  # before any data

    def test_as_of_never_leaks_a_future_value(self):
        ts = TimeSeries(dates=[100, 200, 300], values=[1.0, 2.0, 3.0])
        assert ts.as_of(150) == 1.0  # not 2.0, which is in the future relative to 150

    def test_change_over_computes_pct_change_over_lookback(self):
        ts = TimeSeries(dates=list(range(0, 2500, 100)), values=[100.0 + i for i in range(25)])
        # 21 bars back from index 24 is index 3 (value 103.0); index 24 = 124.0
        result = ts.change_over(2400, lookback_bars=21)
        assert result == pytest.approx(124.0 / 103.0 - 1.0)

    def test_change_over_insufficient_history_returns_none(self):
        ts = TimeSeries(dates=[0, 100, 200], values=[1.0, 2.0, 3.0])
        assert ts.change_over(200, lookback_bars=21) is None


class TestSymbolHistory:
    def test_bars_as_of_excludes_future_bars(self):
        bars = _bars(5, [10.0, 11.0, 12.0, 13.0, 14.0])
        history = SymbolHistory("TEST", "stock", "Technology", bars)
        as_of = history.bars_as_of(bars[2].timestamp)
        assert len(as_of) == 3
        assert as_of[-1].close == 12.0

    def test_price_at_or_after_finds_next_available_bar(self):
        bars = _bars(5, [10.0, 11.0, 12.0, 13.0, 14.0])
        history = SymbolHistory("TEST", "stock", "Technology", bars)
        # ask for a timestamp between bar 1 and bar 2 -> should land on bar 2
        assert history.price_at_or_after(bars[1].timestamp + 1) == 12.0

    def test_price_at_or_after_past_end_of_history_returns_none(self):
        bars = _bars(3, [10.0, 11.0, 12.0])
        history = SymbolHistory("TEST", "stock", "Technology", bars)
        assert history.price_at_or_after(bars[-1].timestamp + 100 * _DAY) is None


class TestHistoricalMacroProvider:
    def test_only_sees_data_at_or_before_the_as_of_date(self):
        macro = MacroHistory(
            ten_year=TimeSeries(dates=[0, 100, 200], values=[4.0, 4.5, 5.0]),
            vix=TimeSeries(dates=[0, 100, 200], values=[15.0, 20.0, 25.0]),
            dollar=TimeSeries(dates=[0, 100, 200], values=[100.0, 101.0, 102.0]),
        )
        provider = HistoricalMacroProvider(macro, as_of_ts=150)
        snapshot = provider.get_macro_snapshot()
        assert snapshot.vix_level == 20.0  # not 25.0, which is after the as-of date
        assert snapshot.ten_year_yield_pct == 4.5


class TestWeightedAlpha:
    def test_basket_return_is_weight_dot_return(self):
        basket_return, alpha = _weighted_alpha([(0.6, 0.10), (0.4, 0.20)], spy_return=0.05)
        assert basket_return == pytest.approx(0.6 * 0.10 + 0.4 * 0.20)
        assert alpha == pytest.approx(basket_return - 0.05)

    def test_alpha_is_zero_when_basket_matches_benchmark(self):
        basket_return, alpha = _weighted_alpha([(1.0, 0.08)], spy_return=0.08)
        assert alpha == pytest.approx(0.0)


class TestSummarize:
    def _report(self, alphas: list[float]) -> BacktestReport:
        trials = [
            TrialResult(
                entry_date="2023-01-01",
                exit_date="2023-04-01",
                picks=[],
                basket_return_pct=a + 0.05,
                spy_return_pct=0.05,
                alpha_pct=a,
                universe_screened=10,
            )
            for a in alphas
        ]
        return BacktestReport(hold_bars=63, step_bars=63, trials=trials)

    def test_empty_report_has_zero_trials(self):
        assert summarize(BacktestReport(hold_bars=63, step_bars=63)) == {"n_trials": 0}

    def test_mean_median_stdev_are_exact(self):
        summary = summarize(self._report([0.10, 0.20, -0.05]))
        assert summary["n_trials"] == 3
        assert summary["mean_alpha_pct"] == pytest.approx((0.10 + 0.20 - 0.05) / 3)
        assert summary["median_alpha_pct"] == pytest.approx(0.10)
        assert summary["best_alpha_pct"] == pytest.approx(0.20)
        assert summary["worst_alpha_pct"] == pytest.approx(-0.05)

    def test_win_rate_counts_strictly_positive_alpha(self):
        summary = summarize(self._report([0.05, -0.05, 0.0, 0.02]))
        assert summary["win_rate"] == pytest.approx(2 / 4)  # 0.05 and 0.02; 0.0 doesn't count as a win

    def test_hit_target_rate_uses_okr_target_low(self):
        target = OKR_TARGET_LOW_PP / 100
        summary = summarize(self._report([target, target - 0.001, target + 0.05]))
        assert summary["hit_target_rate"] == pytest.approx(2 / 3)

    def test_to_markdown_renders_without_crashing(self):
        report = self._report([0.10, -0.05])
        markdown = to_markdown(report, summarize(report))
        assert "Committee backtest" in markdown
        assert "Mean alpha vs SPY" in markdown


class TestRunBacktestEndToEnd:
    """Fully offline (synthetic bars/macro, DummyLLMClient, HeuristicForecaster)
    smoke test: the pipeline runs to completion with no lookahead-related
    crashes and produces a sane report shape. Not a claim about real alpha —
    see fetch_backtest_data() for the only network-dependent piece."""

    def _build_data(self, n_bars: int = 300) -> BacktestData:
        symbols = {}
        # SPY (the benchmark, also required to be in UNIVERSE) stays flat.
        symbols[BENCHMARK_SYMBOL] = SymbolHistory(
            BENCHMARK_SYMBOL, "index_etf", "Broad Market", _bars(n_bars, _flat(n_bars, 500.0))
        )
        # One clearly-trending-up name and one flat name from the real
        # universe table, so screening/eligibility logic runs unmodified.
        up_symbol = next(e.symbol for e in UNIVERSE if e.symbol != BENCHMARK_SYMBOL)
        flat_symbol = next(e.symbol for e in UNIVERSE if e.symbol not in (BENCHMARK_SYMBOL, up_symbol))
        symbols[up_symbol] = SymbolHistory(
            up_symbol, "stock", "Technology", _bars(n_bars, _trending(n_bars, 100.0, 0.003))
        )
        symbols[flat_symbol] = SymbolHistory(
            flat_symbol, "stock", "Technology", _bars(n_bars, _flat(n_bars, 100.0))
        )
        macro = MacroHistory(
            ten_year=TimeSeries(dates=[b.timestamp for b in symbols[BENCHMARK_SYMBOL].bars], values=_flat(n_bars, 4.0)),
            vix=TimeSeries(dates=[b.timestamp for b in symbols[BENCHMARK_SYMBOL].bars], values=_flat(n_bars, 15.0)),
            dollar=TimeSeries(dates=[b.timestamp for b in symbols[BENCHMARK_SYMBOL].bars], values=_flat(n_bars, 100.0)),
        )
        return BacktestData(symbols=symbols, macro=macro)

    def test_runs_to_completion_and_produces_trials(self):
        data = self._build_data()
        report = run_backtest(
            data,
            DummyLLMClient(),
            HeuristicForecaster(),
            hold_bars=40,
            step_bars=40,
            min_picks=2,
            max_picks=2,
        )
        assert len(report.trials) > 0
        for trial in report.trials:
            assert len(trial.picks) >= 1
            assert trial.entry_date < trial.exit_date
            # every picked symbol actually had data at entry (no lookahead crash)
            for pick in trial.picks:
                assert pick.entry_price > 0
                assert pick.exit_price > 0

    def test_missing_benchmark_raises_instead_of_silently_skipping(self):
        data = BacktestData(symbols={}, macro=MacroHistory(TimeSeries([], []), TimeSeries([], []), TimeSeries([], [])))
        with pytest.raises(RuntimeError):
            run_backtest(data, DummyLLMClient(), HeuristicForecaster())
