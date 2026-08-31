"""Real market data via Alpha Vantage (https://www.alphavantage.co).

An alternative to `yfinance_provider.YFinanceFeed` — same
`MarketDataProvider` contract, same "never silently fall back to fake
data on a failed *primary* fetch" rule, same "every fundamentals/news
field is optional" treatment `agents/analysts.py` already expects. Useful
when `yfinance`'s TLS-fingerprint impersonation (via `curl_cffi`, done to
get past Yahoo's bot detection) doesn't survive a network's
TLS-intercepting proxy: Alpha Vantage is a plain, documented REST API
needing only an API key, no fingerprint tricks, no cookie/crumb dance.

**Free-tier quota is real and tight.** A single `get_snapshot()` call can
cost up to 4 requests (daily bars, a real-time quote, fundamentals,
news) — screening a large universe on a free key will exhaust the daily
cap fast. `AlphaVantageConfig.include_fundamentals` /
`include_news` / `include_realtime_quote` exist specifically so a
quota-conscious caller can turn secondary fetches off and spend the
budget on price data alone.

Zero new dependency: stdlib `urllib.request` only, the same "no new
package for one more optional data source" choice `tools/tool_jina_search.py`
already makes elsewhere in this project.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from trading_agent.data.macro import MacroSnapshot
from trading_agent.data.providers import Bar, MarketSnapshot

_BASE_URL = "https://www.alphavantage.co/query"
_INSTALL_HINT = (
    "Alpha Vantage API 키가 설정되어 있지 않습니다. "
    "https://www.alphavantage.co/support/#api-key 에서 무료 키를 발급받아 "
    "ALPHAVANTAGE_API_KEY 환경 변수에 설정하세요."
)

# Alpha Vantage's OVERVIEW field -> our fundamentals dict key. Kept as a
# table so adding one more field is a one-line change, matching
# yfinance_provider.py's _INFO_FIELD_MAP. No debt-to-equity or analyst-
# recommendations entry: Alpha Vantage's free OVERVIEW endpoint doesn't
# expose either, and both are already optional downstream.
_OVERVIEW_FIELD_MAP = {
    "PERatio": "pe_ratio",
    "ForwardPE": "forward_pe",
    "PriceToBookRatio": "price_to_book",
    "QuarterlyRevenueGrowthYOY": "revenue_growth_yoy",
    "QuarterlyEarningsGrowthYOY": "earnings_growth_yoy",
    "ReturnOnEquityTTM": "return_on_equity",
    "ProfitMargin": "profit_margin",
    "DividendYield": "dividend_yield",
    "MarketCapitalization": "market_cap",
    "Beta": "beta",
    "EPS": "eps_trailing",
}
_OVERVIEW_TEXT_FIELDS = {"Sector": "sector", "Industry": "industry"}


class _AlphaVantageClient:
    """Shared HTTP + rate-limit + error-detection plumbing for
    `AlphaVantageFeed` and `AlphaVantageMacroProvider`. Alpha Vantage
    returns HTTP 200 with an "Error Message"/"Note"/"Information" key
    instead of the expected payload on a bad symbol, bad key, or rate
    limit — every caller needs the same check, so it lives here once."""

    def __init__(self, api_key: str | None, requests_per_minute: float) -> None:
        if not api_key:
            raise RuntimeError(_INSTALL_HINT)
        self._api_key = api_key
        self._min_interval = 60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        self._last_request_at: float | None = None

    def get(self, **params: str) -> dict:
        self._throttle()
        query = urllib.parse.urlencode({**params, "apikey": self._api_key})
        with urllib.request.urlopen(f"{_BASE_URL}?{query}", timeout=20) as response:
            return json.loads(response.read())

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        now = time.monotonic()
        if self._last_request_at is not None:
            wait = self._min_interval - (now - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()  # record post-sleep, not the pre-sleep reading
        self._last_request_at = now

    @staticmethod
    def raise_if_error(payload: dict, context: str) -> None:
        if "Error Message" in payload:
            raise RuntimeError(f"Alpha Vantage error for {context}: {payload['Error Message']}")
        note = payload.get("Note") or payload.get("Information")
        if note:
            raise RuntimeError(f"Alpha Vantage rate limit/config issue for {context}: {note}")

    @staticmethod
    def is_error_payload(payload: dict) -> bool:
        return bool(payload.get("Error Message") or payload.get("Note") or payload.get("Information"))


class AlphaVantageFeed:
    def __init__(
        self,
        api_key: str | None,
        requests_per_minute: float = 5.0,
        include_fundamentals: bool = True,
        include_news: bool = True,
        include_realtime_quote: bool = True,
        outputsize: str = "full",
    ) -> None:
        """`outputsize="full"` (the default) returns Alpha Vantage's entire
        daily history rather than just the last ~100 bars ("compact") —
        needed for the portfolio pipeline's ~1-year covariance/backtest
        window; single-symbol commands work fine with the extra data too,
        it's just not trimmed for them specifically."""
        self._client = _AlphaVantageClient(api_key, requests_per_minute)
        self._include_fundamentals = include_fundamentals
        self._include_news = include_news
        self._include_realtime_quote = include_realtime_quote
        self._outputsize = outputsize

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        bars = self._fetch_daily_bars(symbol)
        if self._include_realtime_quote:
            self._apply_realtime_quote(symbol, bars)
        fundamentals = self._fetch_fundamentals(symbol) if self._include_fundamentals else {}
        headlines = self._fetch_headlines(symbol) if self._include_news else []
        return MarketSnapshot(symbol=symbol, bars=bars, fundamentals=fundamentals, news_headlines=headlines)

    # -- Price bars: primary fetch, never silently faked on failure -----

    def _fetch_daily_bars(self, symbol: str) -> list[Bar]:
        payload = self._client.get(function="TIME_SERIES_DAILY", symbol=symbol, outputsize=self._outputsize)
        self._client.raise_if_error(payload, f"daily bars for '{symbol}'")
        series = payload.get("Time Series (Daily)")
        if not series:
            raise RuntimeError(
                f"'{symbol}'에 대한 Alpha Vantage 시세 데이터를 찾을 수 없습니다. "
                f"실제 티커가 맞는지 확인하세요."
            )
        bars = [
            Bar(
                timestamp=_parse_date_utc(date_str),
                open=float(values["1. open"]),
                high=float(values["2. high"]),
                low=float(values["3. low"]),
                close=float(values["4. close"]),
                volume=float(values["5. volume"]),
            )
            for date_str, values in series.items()
        ]
        bars.sort(key=lambda b: b.timestamp)
        return bars

    def _apply_realtime_quote(self, symbol: str, bars: list[Bar]) -> None:
        """Best-effort: overlays the latest near-real-time price on top of
        the daily bars fetched above, so `MarketSnapshot.last_price`
        reflects today's quote even before Alpha Vantage's daily series
        catches up. Flat open=high=low=close from the single quoted
        price — the same "synthesize a flat bar from a close-only
        reading" approach `forecast/kronos_forecaster.py` already uses
        elsewhere in this project. Never fatal: any failure here just
        leaves the already-fetched daily bars as they are."""
        try:
            payload = self._client.get(function="GLOBAL_QUOTE", symbol=symbol)
            if self._client.is_error_payload(payload):
                return
            quote = payload.get("Global Quote") or {}
            price, trading_day = quote.get("05. price"), quote.get("07. latest trading day")
            if not price or not trading_day:
                return
            price = float(price)
            ts = _parse_date_utc(trading_day)
            new_bar = Bar(
                timestamp=ts, open=price, high=price, low=price, close=price, volume=float(quote.get("06. volume") or 0)
            )
            if bars and bars[-1].timestamp == ts:
                bars[-1] = new_bar  # today's daily bar already present -> refresh with the live quote
            elif not bars or ts > bars[-1].timestamp:
                bars.append(new_bar)
        except Exception:
            pass

    # -- Fundamentals & news: secondary, optional, best-effort -----------

    def _fetch_fundamentals(self, symbol: str) -> dict:
        try:
            payload = self._client.get(function="OVERVIEW", symbol=symbol)
        except Exception:
            return {}
        if self._client.is_error_payload(payload):
            return {}  # rate-limited/unavailable; every fundamental field is optional downstream

        fundamentals: dict = {}
        for av_key, our_key in _OVERVIEW_FIELD_MAP.items():
            value = payload.get(av_key)
            if value in (None, "", "None", "-"):
                continue
            try:
                fundamentals[our_key] = float(value)
            except ValueError:
                continue
        for av_key, our_key in _OVERVIEW_TEXT_FIELDS.items():
            value = payload.get(av_key)
            if value and value not in ("None", "-"):
                fundamentals[our_key] = value
        return fundamentals

    def _fetch_headlines(self, symbol: str) -> list[str]:
        try:
            payload = self._client.get(function="NEWS_SENTIMENT", tickers=symbol, limit="10")
        except Exception:
            return []
        if self._client.is_error_payload(payload):
            return []
        return [item["title"] for item in payload.get("feed", [])[:5] if item.get("title")]


class AlphaVantageMacroProvider:
    """Macro context via Alpha Vantage — thinner than
    `data.macro.YFinanceMacroProvider`: Alpha Vantage's API exposes
    Treasury yields directly (`TREASURY_YIELD`) but has no VIX or
    dollar-index equivalent, so those two `MacroSnapshot` fields are
    always None here (an honest "no signal", the same as every other
    optional field in this project) rather than approximated from an
    unrelated proxy that could mislead a reader into thinking it's the
    real thing."""

    def __init__(self, api_key: str | None, requests_per_minute: float = 5.0) -> None:
        self._client = _AlphaVantageClient(api_key, requests_per_minute)

    def get_macro_snapshot(self) -> MacroSnapshot:
        level, change = self._ten_year_yield()
        return MacroSnapshot(
            ten_year_yield_pct=level,
            ten_year_yield_change_pct=change,
            vix_level=None,
            dollar_index_change_pct=None,
        )

    def _ten_year_yield(self) -> tuple[float | None, float | None]:
        try:
            payload = self._client.get(function="TREASURY_YIELD", interval="daily", maturity="10year")
            if self._client.is_error_payload(payload):
                return None, None
            values = [
                (row["date"], float(row["value"]))
                for row in payload.get("data") or []
                if row.get("value") not in (None, ".", "")
            ]
            if not values:
                return None, None
            values.sort(key=lambda dv: dv[0])
            level = values[-1][1]
            first = values[0][1]
            change = (level / first - 1) if first else None
            return level, change
        except Exception:
            return None, None


def _parse_date_utc(date_str: str) -> int:
    return int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
