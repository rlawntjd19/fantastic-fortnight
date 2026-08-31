"""Real market data via Yahoo Finance (`yfinance`).

Optional: `yfinance` is not a hard dependency of this project (see
requirements-live.txt). If it isn't installed, construction fails fast
with a clear message, and `data/factory.py` falls back to the offline
`SimulatedFeed` — the same pattern `forecast/kronos_forecaster.py` uses.

Unlike that fallback-on-failure pattern, a fetch that fails *after*
construction (bad ticker, no network, delisted symbol) is never silently
swapped for fake data here — `get_snapshot` raises instead. Quietly
handing back a simulated price under a real ticker's name would be a
much worse failure mode for a finance tool than just erroring.

Every optional field below (fundamentals, analyst recommendations, news)
is fetched independently and wrapped so one missing/renamed field from
Yahoo's API can't take down the whole snapshot — `FundamentalAnalyst`
and friends already treat missing fields as "no signal there", not an
error (see agents/analysts.py's `if x is not None` guards).
"""
from __future__ import annotations

from trading_agent.data.providers import Bar, MarketSnapshot

_INSTALL_HINT = "yfinance가 설치되어 있지 않습니다. 설치하려면:\n  pip install -r requirements-live.txt"

# yfinance's Ticker.info key -> our fundamentals dict key. Kept as a table
# so adding one more field is a one-line change, not new branching logic.
_INFO_FIELD_MAP = {
    "trailingPE": "pe_ratio",
    "forwardPE": "forward_pe",
    "priceToBook": "price_to_book",
    "revenueGrowth": "revenue_growth_yoy",
    "earningsGrowth": "earnings_growth_yoy",
    "returnOnEquity": "return_on_equity",
    "profitMargins": "profit_margin",
    "debtToEquity": "debt_to_equity",
    "dividendYield": "dividend_yield",
    "marketCap": "market_cap",
    "totalAssets": "total_assets",  # ETF AUM
    "beta": "beta",
    "trailingEps": "eps_trailing",
    "sector": "sector",
    "industry": "industry",
    "exchange": "exchange",
    "quoteType": "quote_type",
}


class YFinanceFeed:
    def __init__(
        self,
        period: str = "6mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
    ) -> None:
        """`start`/`end` (e.g. "2025-01-01"/"2025-02-28") reproduce a specific
        historical window exactly, taking priority over `period` when given —
        the same idea AI-Trader's "time control framework" replays a fixed
        past period from. Same data in, same bars out, every time."""
        try:
            import yfinance  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(_INSTALL_HINT) from exc

        self._period = period
        self._interval = interval
        self._start = start
        self._end = end

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        if self._start or self._end:
            history = ticker.history(start=self._start, end=self._end, interval=self._interval)
        else:
            history = ticker.history(period=self._period, interval=self._interval)
        if history.empty:
            raise RuntimeError(
                f"'{symbol}'에 대한 시세 데이터를 찾을 수 없습니다. Yahoo Finance 실제 티커가 맞는지 "
                f"확인하세요 (예: SK하이닉스는 '000660.KS', 애플은 'AAPL')."
            )

        bars = [
            Bar(
                timestamp=int(ts.timestamp()),
                open=float(row.Open),
                high=float(row.High),
                low=float(row.Low),
                close=float(row.Close),
                volume=float(row.Volume),
            )
            for ts, row in history.iterrows()
        ]

        fundamentals = self._fetch_fundamentals(ticker)
        headlines = self._fetch_headlines(ticker)

        return MarketSnapshot(symbol=symbol, bars=bars, fundamentals=fundamentals, news_headlines=headlines)

    @staticmethod
    def _fetch_fundamentals(ticker) -> dict:
        fundamentals: dict = {}
        try:
            info = ticker.info or {}
        except Exception:
            return fundamentals  # best-effort; analysts treat missing fields as "no signal"

        for info_key, our_key in _INFO_FIELD_MAP.items():
            try:
                value = info.get(info_key)
            except Exception:
                continue
            if value is not None:
                fundamentals[our_key] = value

        try:
            recs = ticker.recommendations
            if recs is not None and not recs.empty:
                latest = recs.iloc[0]
                fundamentals["analyst_recommendations"] = {
                    "strong_buy": int(latest.get("strongBuy", 0)),
                    "buy": int(latest.get("buy", 0)),
                    "hold": int(latest.get("hold", 0)),
                    "sell": int(latest.get("sell", 0)),
                    "strong_sell": int(latest.get("strongSell", 0)),
                }
        except Exception:
            pass  # not all tickers/yfinance versions expose this

        return fundamentals

    @staticmethod
    def _fetch_headlines(ticker) -> list[str]:
        try:
            return [item["title"] for item in (ticker.news or [])[:5] if item.get("title")]
        except Exception:
            return []
