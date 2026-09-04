"""Tests for SeasonalityAnalyst: a real, per-symbol calendar-anomaly check
(the Halloween-effect/January-effect/Santa-Claus-rally family of
documented calendar seasonality) computed from that symbol's own
multi-year price history — never a hardcoded opinion about which tickers
"do well in Q4". These tests build synthetic-but-real-calendar-dated bars
directly (not via the offline SimulatedFeed, whose bar timestamps are
sequential indices with no real calendar meaning and so can never produce
a seasonal read — see test_no_real_calendar_history_reports_neutral
below for that exact degrade-gracefully case).
"""
import datetime as dt

from trading_agent.agents.analysts import SeasonalityAnalyst
from trading_agent.agents.schemas import Signal
from trading_agent.data.providers import Bar, MarketSnapshot
from trading_agent.llm.client import DummyLLMClient


def _epoch(year: int, month: int, day: int) -> int:
    return int(dt.datetime(year, month, day, tzinfo=dt.timezone.utc).timestamp())


def _snapshot(anchor_month_day: tuple[int, int], prices_by_year: dict[int, tuple[float, float]]) -> MarketSnapshot:
    """`prices_by_year`: {year: (anchor_price, year_end_price)}."""
    bars = []
    for year, (anchor_price, year_end_price) in prices_by_year.items():
        month, day = anchor_month_day
        bars.append(Bar(_epoch(year, month, day), anchor_price, anchor_price, anchor_price, anchor_price, 1_000.0))
        bars.append(Bar(_epoch(year, 12, 31), year_end_price, year_end_price, year_end_price, year_end_price, 1_000.0))
    bars.sort(key=lambda b: b.timestamp)
    return MarketSnapshot(symbol="TEST", bars=bars)


def _analyst() -> SeasonalityAnalyst:
    return SeasonalityAnalyst(DummyLLMClient())


def test_consistently_positive_seasonal_years_reports_bullish():
    prices = {
        2020: (100.0, 110.0),
        2021: (100.0, 108.0),
        2022: (100.0, 105.0),
        2023: (100.0, 112.0),
        2024: (100.0, 106.0),
    }
    report = _analyst().analyze(_snapshot((9, 4), prices), dt.date(2025, 9, 4))

    assert report.signal == Signal.BULLISH
    assert report.confidence > 0
    assert len(report.key_points) == len(prices) + 1  # one line per year + the summary line


def test_consistently_negative_seasonal_years_reports_bearish():
    prices = {
        2020: (100.0, 90.0),
        2021: (100.0, 92.0),
        2022: (100.0, 95.0),
        2023: (100.0, 88.0),
        2024: (100.0, 94.0),
    }
    report = _analyst().analyze(_snapshot((9, 4), prices), dt.date(2025, 9, 4))

    assert report.signal == Signal.BEARISH
    assert report.confidence > 0


def test_mixed_seasonal_years_reports_neutral():
    prices = {
        2020: (100.0, 110.0),
        2021: (100.0, 92.0),
        2022: (100.0, 105.0),
        2023: (100.0, 88.0),
        2024: (100.0, 101.0),
    }
    report = _analyst().analyze(_snapshot((9, 4), prices), dt.date(2025, 9, 4))

    assert report.signal == Signal.NEUTRAL


def test_too_few_qualifying_years_reports_neutral_at_zero_confidence():
    # Only 2 past years of data; SeasonalityAnalyst.MIN_QUALIFYING_YEARS is 4
    # — a thin sample must not be allowed to look decisive.
    prices = {2023: (100.0, 110.0), 2024: (100.0, 105.0)}
    report = _analyst().analyze(_snapshot((9, 4), prices), dt.date(2025, 9, 4))

    assert report.signal == Signal.NEUTRAL
    assert report.confidence == 0.0


def test_no_history_reports_neutral_at_zero_confidence():
    report = _analyst().analyze(None, dt.date(2025, 9, 4))

    assert report.signal == Signal.NEUTRAL
    assert report.confidence == 0.0


def test_no_real_calendar_history_reports_neutral():
    # The offline SimulatedFeed's Bar.timestamp is a sequential bar index
    # (0, 1, 2, ...), not a real epoch second — interpreted as an epoch,
    # 120 bars span about two minutes of real 1970-01-01 time, so no two
    # bars ever land in different calendar years. This is the exact
    # mechanism that makes SeasonalityAnalyst a safe no-op under every
    # existing offline test and the whole committee.backtest harness,
    # without needing to special-case "is this a SimulatedFeed" anywhere.
    bars = [Bar(timestamp=i, open=100.0, high=100.0, low=100.0, close=100.0 + i, volume=1_000.0) for i in range(120)]
    snapshot = MarketSnapshot(symbol="TEST", bars=bars)

    report = _analyst().analyze(snapshot, dt.date(2025, 9, 4))

    assert report.signal == Signal.NEUTRAL
    assert report.confidence == 0.0


def test_a_year_whose_nearest_bar_is_too_far_from_the_target_dates_is_excluded():
    # 2020-2023 have real anchor/year-end bars; 2024's only bar sits three
    # weeks away from both target dates (well past the 7-day slop window)
    # and must not count as a qualifying year.
    prices = {
        2020: (100.0, 110.0),
        2021: (100.0, 108.0),
        2022: (100.0, 105.0),
        2023: (100.0, 112.0),
    }
    snapshot = _snapshot((9, 4), prices)
    stray_bar = Bar(_epoch(2024, 6, 15), 100.0, 100.0, 100.0, 100.0, 1_000.0)
    snapshot.bars.append(stray_bar)
    snapshot.bars.sort(key=lambda b: b.timestamp)

    report = _analyst().analyze(snapshot, dt.date(2025, 9, 4))

    # Still exactly 4 qualifying years (2020-2023) -> a real (non-thin) read.
    assert len([p for p in report.key_points if " -> year-end): " in p]) == 4


def test_feb_29_as_of_date_skips_non_leap_years_without_crashing():
    # as_of itself is Feb 29 (2028 is a leap year); dt.date(year, 2, 29)
    # raises ValueError for every non-leap `year` in between, which must
    # be caught and skipped rather than propagate.
    prices = {2020: (100.0, 110.0), 2024: (100.0, 106.0)}  # the only leap years in range
    snapshot = _snapshot((2, 29), prices)

    report = _analyst().analyze(snapshot, dt.date(2028, 2, 29))

    # Only 2 qualifying (leap) years -> well under the 4-year minimum.
    assert report.signal == Signal.NEUTRAL
    assert report.confidence == 0.0
