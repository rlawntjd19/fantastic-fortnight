"""Tests for YFinanceFeed's own parsing logic, using fake ticker/response
objects so nothing here touches the network or requires yfinance/pandas
to be installed (`_fetch_fundamentals`/`_fetch_headlines` are plain
staticmethods with no import-time dependency on yfinance itself).

Whether Yahoo's actual field names still match `_INFO_FIELD_MAP` can't be
verified in this sandbox (outbound requests to Yahoo's API are blocked
here) — these tests instead lock in that our parsing degrades gracefully
around whatever `ticker.info` / `ticker.recommendations` / `ticker.news`
actually return.
"""
import math

import pytest

from trading_agent.data.yfinance_provider import YFinanceFeed


class _FakeRecRow(dict):
    def get(self, key, default=0):
        return dict.get(self, key, default)


class _FakeRecommendations(list):
    """Stands in for the tiny slice of a pandas DataFrame's API
    `_fetch_fundamentals` actually uses: `.empty` and `.iloc[0].get(...)`."""

    def __init__(self, rows):
        super().__init__(_FakeRecRow(r) for r in rows)
        self.empty = len(rows) == 0

    @property
    def iloc(self):
        return self


class _FakeTicker:
    def __init__(self, info=None, recommendations=None, news=None, raise_on_info=False):
        self._info = info or {}
        self.recommendations = recommendations
        self.news = news
        self._raise_on_info = raise_on_info

    @property
    def info(self):
        if self._raise_on_info:
            raise RuntimeError("simulated network failure")
        return self._info


def test_fetch_fundamentals_maps_known_info_fields():
    ticker = _FakeTicker(info={"trailingPE": 18.5, "revenueGrowth": 0.12, "sector": "Technology"})
    fundamentals = YFinanceFeed._fetch_fundamentals(ticker)
    assert fundamentals["pe_ratio"] == 18.5
    assert fundamentals["revenue_growth_yoy"] == 0.12
    assert fundamentals["sector"] == "Technology"


def test_fetch_fundamentals_skips_missing_fields_without_error():
    ticker = _FakeTicker(info={"trailingPE": 18.5})
    fundamentals = YFinanceFeed._fetch_fundamentals(ticker)
    assert fundamentals == {"pe_ratio": 18.5}


def test_fetch_fundamentals_degrades_gracefully_when_info_raises():
    ticker = _FakeTicker(raise_on_info=True)
    fundamentals = YFinanceFeed._fetch_fundamentals(ticker)
    assert fundamentals == {}


def test_fetch_fundamentals_includes_analyst_recommendations():
    recs = _FakeRecommendations([{"strongBuy": 5, "buy": 3, "hold": 2, "sell": 1, "strongSell": 0}])
    ticker = _FakeTicker(info={}, recommendations=recs)
    fundamentals = YFinanceFeed._fetch_fundamentals(ticker)
    assert fundamentals["analyst_recommendations"] == {
        "strong_buy": 5,
        "buy": 3,
        "hold": 2,
        "sell": 1,
        "strong_sell": 0,
    }


def test_fetch_fundamentals_skips_recommendations_when_absent():
    ticker = _FakeTicker(info={}, recommendations=None)
    fundamentals = YFinanceFeed._fetch_fundamentals(ticker)
    assert "analyst_recommendations" not in fundamentals


def test_fetch_fundamentals_skips_recommendations_when_empty():
    ticker = _FakeTicker(info={}, recommendations=_FakeRecommendations([]))
    fundamentals = YFinanceFeed._fetch_fundamentals(ticker)
    assert "analyst_recommendations" not in fundamentals


def test_fetch_headlines_extracts_titles():
    ticker = _FakeTicker(news=[{"title": "Company beats earnings"}, {"title": "Stock rallies"}, {}])
    headlines = YFinanceFeed._fetch_headlines(ticker)
    assert headlines == ["Company beats earnings", "Stock rallies"]


def test_fetch_headlines_degrades_gracefully_when_news_is_none():
    ticker = _FakeTicker(news=None)
    assert YFinanceFeed._fetch_headlines(ticker) == []


# --- get_snapshot(): verifies start/end vs period plumbing by fully faking
# the `yfinance` module via sys.modules, so this runs the same whether or
# not the real package happens to be installed in this environment. ---


class _FakeTimestamp:
    def __init__(self, epoch):
        self._epoch = epoch

    def timestamp(self):
        return self._epoch


class _FakeBarRow:
    def __init__(self, o, h, l, c, v):
        self.Open, self.High, self.Low, self.Close, self.Volume = o, h, l, c, v


class _FakeHistory:
    def __init__(self, rows):
        self._rows = rows
        self.empty = len(rows) == 0

    def iterrows(self):
        for epoch, o, h, l, c, v in self._rows:
            yield _FakeTimestamp(epoch), _FakeBarRow(o, h, l, c, v)


def _install_fake_yfinance(monkeypatch, captured, history):
    import sys
    import types

    class _FakeTicker:
        def __init__(self, symbol):
            captured["symbol"] = symbol

        def history(self, **kwargs):
            captured.update(kwargs)
            return history

        @property
        def info(self):
            return {}

        recommendations = None
        news = None

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_FakeTicker))


def test_get_snapshot_passes_start_end_when_given(monkeypatch):
    captured = {}
    _install_fake_yfinance(
        monkeypatch, captured, _FakeHistory([(1700000000, 100.0, 101.0, 99.0, 100.5, 1000.0)])
    )

    feed = YFinanceFeed(start="2025-01-01", end="2025-02-28")
    snapshot = feed.get_snapshot("AAPL")

    assert captured["start"] == "2025-01-01"
    assert captured["end"] == "2025-02-28"
    assert "period" not in captured
    assert len(snapshot.bars) == 1
    assert snapshot.bars[0].close == 100.5


def test_get_snapshot_passes_period_when_no_start_end(monkeypatch):
    captured = {}
    _install_fake_yfinance(
        monkeypatch, captured, _FakeHistory([(1700000000, 100.0, 101.0, 99.0, 100.5, 1000.0)])
    )

    feed = YFinanceFeed(period="6mo")
    feed.get_snapshot("AAPL")

    assert captured["period"] == "6mo"
    assert "start" not in captured


def test_get_snapshot_raises_on_empty_history(monkeypatch):
    captured = {}
    _install_fake_yfinance(monkeypatch, captured, _FakeHistory([]))

    feed = YFinanceFeed()
    with pytest.raises(RuntimeError, match="시세 데이터를 찾을 수 없습니다"):
        feed.get_snapshot("NOTATICKER")


def test_get_snapshot_drops_a_nan_bar_instead_of_exposing_it(monkeypatch):
    # Reproduces a real production incident: Yahoo served a NaN close for
    # the most recent bar of a held position, which flowed straight into
    # MarketSnapshot.last_price -> performance_tracker.build_scoreboard's
    # `int(capital_for_position // current)`, crashing the whole live run
    # with "ValueError: cannot convert float NaN to integer". A NaN bar
    # must never reach a Bar/MarketSnapshot at all.
    nan = float("nan")
    captured = {}
    _install_fake_yfinance(
        monkeypatch,
        captured,
        _FakeHistory(
            [
                (1700000000, 100.0, 101.0, 99.0, 100.5, 1000.0),
                (1700086400, nan, nan, nan, nan, nan),  # today's bar, not yet fully posted
            ]
        ),
    )

    feed = YFinanceFeed()
    snapshot = feed.get_snapshot("AAPL")

    assert len(snapshot.bars) == 1  # the NaN bar was dropped, not kept
    assert snapshot.last_price == 100.5
    assert math.isfinite(snapshot.last_price)


def test_get_snapshot_raises_when_every_bar_is_nan(monkeypatch):
    nan = float("nan")
    captured = {}
    _install_fake_yfinance(monkeypatch, captured, _FakeHistory([(1700000000, nan, nan, nan, nan, nan)]))

    feed = YFinanceFeed()
    with pytest.raises(RuntimeError, match="결측치"):
        feed.get_snapshot("AAPL")
