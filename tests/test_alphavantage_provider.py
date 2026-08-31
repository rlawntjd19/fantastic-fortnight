"""Tests for AlphaVantageFeed/AlphaVantageMacroProvider's own parsing and
error-handling logic, with `urllib.request.urlopen` monkeypatched so
nothing here touches the network or needs a real API key — mirrors
tests/test_yfinance_provider.py's approach for the yfinance backend.

`requests_per_minute=0` (disables throttling) everywhere except the
dedicated throttle test — otherwise every multi-request test would hit
the real default 5-req/min limiter and actually sleep for seconds.
"""
import json

import pytest

from trading_agent.data.alphavantage_provider import (
    AlphaVantageFeed,
    AlphaVantageMacroProvider,
    _AlphaVantageClient,
)


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_fake_urlopen(monkeypatch, responses):
    """`responses` is a list consumed in call order, or a single dict reused
    for every call."""
    calls = []

    def fake_urlopen(url, timeout=20):
        calls.append(url)
        payload = responses.pop(0) if isinstance(responses, list) else responses
        return _FakeResponse(payload)

    monkeypatch.setattr("trading_agent.data.alphavantage_provider.urllib.request.urlopen", fake_urlopen)
    return calls


def _daily_series_payload(closes: dict[str, float]) -> dict:
    return {
        "Time Series (Daily)": {
            date: {"1. open": str(c), "2. high": str(c), "3. low": str(c), "4. close": str(c), "5. volume": "1000"}
            for date, c in closes.items()
        }
    }


def _feed(**overrides):
    kwargs = dict(api_key="fake", requests_per_minute=0, include_fundamentals=False, include_news=False, include_realtime_quote=False)
    kwargs.update(overrides)
    return AlphaVantageFeed(**kwargs)


def test_requires_api_key():
    with pytest.raises(RuntimeError):
        AlphaVantageFeed(api_key=None)


def test_get_snapshot_parses_daily_bars_sorted_ascending(monkeypatch):
    payload = _daily_series_payload({"2024-01-03": 103.0, "2024-01-01": 101.0, "2024-01-02": 102.0})
    _install_fake_urlopen(monkeypatch, payload)

    snapshot = _feed().get_snapshot("AAPL")

    assert [b.close for b in snapshot.bars] == [101.0, 102.0, 103.0]
    assert snapshot.symbol == "AAPL"


def test_get_snapshot_raises_on_error_message(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"Error Message": "Invalid API call"})
    with pytest.raises(RuntimeError, match="Invalid API call"):
        _feed().get_snapshot("NOTATICKER")


def test_get_snapshot_raises_on_rate_limit_note(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"Note": "Thank you for using Alpha Vantage! Our standard API call frequency is..."})
    with pytest.raises(RuntimeError, match="rate limit"):
        _feed().get_snapshot("AAPL")


def test_get_snapshot_raises_on_empty_series(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"Time Series (Daily)": {}})
    with pytest.raises(RuntimeError, match="찾을 수 없습니다"):
        _feed().get_snapshot("AAPL")


def test_realtime_quote_appends_a_new_bar_for_a_later_day(monkeypatch):
    responses = [
        _daily_series_payload({"2024-01-01": 100.0}),
        {"Global Quote": {"05. price": "105.5", "06. volume": "500", "07. latest trading day": "2024-01-02"}},
    ]
    _install_fake_urlopen(monkeypatch, responses)

    snapshot = _feed(include_realtime_quote=True).get_snapshot("AAPL")

    assert len(snapshot.bars) == 2
    assert snapshot.last_price == 105.5


def test_realtime_quote_refreshes_same_day_bar_instead_of_duplicating(monkeypatch):
    responses = [
        _daily_series_payload({"2024-01-01": 100.0}),
        {"Global Quote": {"05. price": "101.25", "06. volume": "500", "07. latest trading day": "2024-01-01"}},
    ]
    _install_fake_urlopen(monkeypatch, responses)

    snapshot = _feed(include_realtime_quote=True).get_snapshot("AAPL")

    assert len(snapshot.bars) == 1
    assert snapshot.last_price == 101.25


def test_realtime_quote_failure_is_never_fatal(monkeypatch):
    def fake_urlopen(url, timeout=20):
        if "GLOBAL_QUOTE" in url:
            raise RuntimeError("simulated network failure")
        return _FakeResponse(_daily_series_payload({"2024-01-01": 100.0}))

    monkeypatch.setattr("trading_agent.data.alphavantage_provider.urllib.request.urlopen", fake_urlopen)
    snapshot = _feed(include_realtime_quote=True).get_snapshot("AAPL")
    assert snapshot.last_price == 100.0


def test_fetch_fundamentals_maps_known_overview_fields(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"PERatio": "18.5", "QuarterlyRevenueGrowthYOY": "0.12", "Sector": "TECHNOLOGY"})
    fundamentals = _feed()._fetch_fundamentals("AAPL")
    assert fundamentals["pe_ratio"] == 18.5
    assert fundamentals["revenue_growth_yoy"] == 0.12
    assert fundamentals["sector"] == "TECHNOLOGY"


def test_fetch_fundamentals_skips_none_and_dash_placeholders(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"PERatio": "None", "ForwardPE": "-", "Beta": "1.2"})
    fundamentals = _feed()._fetch_fundamentals("AAPL")
    assert fundamentals == {"beta": 1.2}


def test_fetch_fundamentals_degrades_gracefully_on_rate_limit(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"Information": "rate limited"})
    fundamentals = _feed()._fetch_fundamentals("AAPL")
    assert fundamentals == {}


def test_fetch_headlines_extracts_titles(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"feed": [{"title": "Company beats earnings"}, {"title": "Stock rallies"}, {}]})
    headlines = _feed()._fetch_headlines("AAPL")
    assert headlines == ["Company beats earnings", "Stock rallies"]


def test_fetch_headlines_degrades_gracefully_on_error(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"Error Message": "bad request"})
    assert _feed()._fetch_headlines("AAPL") == []


def test_include_flags_skip_the_corresponding_secondary_fetches(monkeypatch):
    calls = _install_fake_urlopen(monkeypatch, _daily_series_payload({"2024-01-01": 100.0}))
    _feed().get_snapshot("AAPL")
    assert len(calls) == 1  # only the daily-bars call


def test_macro_provider_computes_level_and_relative_change(monkeypatch):
    _install_fake_urlopen(
        monkeypatch,
        {"data": [{"date": "2024-01-03", "value": "4.30"}, {"date": "2024-01-01", "value": "4.00"}]},
    )
    snapshot = AlphaVantageMacroProvider(api_key="fake", requests_per_minute=0).get_macro_snapshot()
    assert snapshot.ten_year_yield_pct == 4.30
    assert snapshot.ten_year_yield_change_pct == pytest.approx(4.30 / 4.00 - 1)
    assert snapshot.vix_level is None
    assert snapshot.dollar_index_change_pct is None


def test_macro_provider_degrades_gracefully_on_failure(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"Error Message": "bad request"})
    snapshot = AlphaVantageMacroProvider(api_key="fake", requests_per_minute=0).get_macro_snapshot()
    assert snapshot.ten_year_yield_pct is None
    assert snapshot.ten_year_yield_change_pct is None


def test_throttle_sleeps_between_requests(monkeypatch):
    sleeps = []
    monkeypatch.setattr("trading_agent.data.alphavantage_provider.time.sleep", lambda s: sleeps.append(s))
    # call 1: one monotonic() read (no prior request, no sleep). call 2: one read
    # to compute the wait, a sleep, then one more post-sleep read to record.
    times = iter([100.0, 100.01, 101.0])
    monkeypatch.setattr("trading_agent.data.alphavantage_provider.time.monotonic", lambda: next(times))

    client = _AlphaVantageClient(api_key="fake", requests_per_minute=60.0)  # 1s min interval
    client._throttle()
    client._throttle()

    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(0.99, abs=1e-6)
    assert client._last_request_at == 101.0
