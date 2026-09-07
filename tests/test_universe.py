"""Tests for the live-only S&P 500 universe expansion
(committee/universe.py's fetch_sp500_constituents/get_live_universe).

fetch_sp500_constituents() hits real network (Wikipedia) when actually
called — every test here fakes `requests.get` so nothing touches the
network or requires it to be reachable from this sandbox, the same
pattern test_yfinance_provider.py uses for yfinance itself.
"""
import pytest
import requests

from trading_agent.committee.universe import (
    UNIVERSE,
    UniverseEntry,
    fetch_sp500_constituents,
    get_live_universe,
)


def _wikipedia_table_html(rows: list[tuple[str, str]]) -> str:
    """`rows`: list of (symbol, gics_sector) as they'd literally appear in
    Wikipedia's "List of S&P 500 companies" first table."""
    body = "".join(
        f"<tr><td>{symbol}</td><td>Some Company {i}</td><td>{sector}</td><td>Sub-Industry</td></tr>"
        for i, (symbol, sector) in enumerate(rows)
    )
    return (
        "<html><body><table>"
        "<tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>GICS Sub-Industry</th></tr>"
        f"{body}"
        "</table></body></html>"
    )


class _FakeResponse:
    def __init__(self, text: str, status_ok: bool = True):
        self.text = text
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise requests.HTTPError("simulated HTTP failure")


def _padded_real_size_rows(extra: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """A real S&P 500 fetch returns ~500 rows; pad with synthetic ones past
    the function's own 400-row sanity floor so tests can focus on the
    handful of rows they actually care about."""
    padding = [(f"TICK{i:04d}", "Industrials") for i in range(420)]
    return extra + padding


def test_fetch_sp500_converts_dot_tickers_to_dashes(monkeypatch):
    html = _wikipedia_table_html(_padded_real_size_rows([("BRK.B", "Financials")]))
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(html))

    entries = fetch_sp500_constituents()

    by_symbol = {e.symbol: e for e in entries}
    assert "BRK-B" in by_symbol
    assert "BRK.B" not in by_symbol
    assert by_symbol["BRK-B"].security_type == "stock"


def test_fetch_sp500_uses_real_gics_sector_labels(monkeypatch):
    html = _wikipedia_table_html(_padded_real_size_rows([("AAPL", "Information Technology")]))
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(html))

    entries = fetch_sp500_constituents()

    aapl = next(e for e in entries if e.symbol == "AAPL")
    assert aapl.sector == "Information Technology"


def test_fetch_sp500_dedupes_repeated_symbols(monkeypatch):
    html = _wikipedia_table_html(_padded_real_size_rows([("AAPL", "Information Technology"), ("AAPL", "Information Technology")]))
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(html))

    entries = fetch_sp500_constituents()

    assert sum(1 for e in entries if e.symbol == "AAPL") == 1


def test_fetch_sp500_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse("", status_ok=False))

    with pytest.raises(requests.HTTPError):
        fetch_sp500_constituents()


def test_fetch_sp500_raises_when_page_structure_changed(monkeypatch):
    # Far fewer than a real S&P 500 page's ~500 rows -- treated as the page
    # layout having changed under us, not a legitimately smaller index.
    html = _wikipedia_table_html([("AAPL", "Information Technology"), ("MSFT", "Information Technology")])
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(html))

    with pytest.raises(RuntimeError, match="page structure likely changed"):
        fetch_sp500_constituents()


def test_get_live_universe_unions_etfs_onto_the_sp500_fetch(monkeypatch):
    import trading_agent.committee.universe as universe_module

    fake_sp500 = [UniverseEntry("AAPL", "stock", "Information Technology")]
    monkeypatch.setattr(universe_module, "fetch_sp500_constituents", lambda: fake_sp500)

    result = get_live_universe()

    symbols = {e.symbol for e in result}
    assert "AAPL" in symbols
    assert {"SPY", "VOO", "VTI", "QQQ", "DIA"} <= symbols
    assert len(result) == 6  # 1 fetched stock + 5 ETFs, no duplicates


def test_get_live_universe_does_not_duplicate_an_etf_already_in_the_fetch(monkeypatch):
    import trading_agent.committee.universe as universe_module

    fake_sp500 = [UniverseEntry("AAPL", "stock", "Information Technology"), UniverseEntry("SPY", "index_etf", "Broad Market")]
    monkeypatch.setattr(universe_module, "fetch_sp500_constituents", lambda: fake_sp500)

    result = get_live_universe()

    assert sum(1 for e in result if e.symbol == "SPY") == 1
    assert len(result) == 6  # AAPL, SPY (from fetch) + VOO, VTI, QQQ, DIA


def test_get_live_universe_propagates_a_fetch_failure(monkeypatch):
    import trading_agent.committee.universe as universe_module

    def _raise():
        raise RuntimeError("simulated Wikipedia outage")

    monkeypatch.setattr(universe_module, "fetch_sp500_constituents", _raise)

    with pytest.raises(RuntimeError, match="simulated Wikipedia outage"):
        get_live_universe()


def test_static_universe_is_untouched_and_still_forty_names():
    # committee.backtest's basket-size evidence depends on this list never
    # silently changing shape.
    assert len(UNIVERSE) == 40
