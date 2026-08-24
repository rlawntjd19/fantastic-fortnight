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
"""
from __future__ import annotations

from trading_agent.data.providers import Bar, MarketSnapshot


class YFinanceFeed:
    def __init__(self, period: str = "6mo", interval: str = "1d") -> None:
        try:
            import yfinance  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "yfinance가 설치되어 있지 않습니다. 설치하려면:\n"
                "  pip install -r requirements-live.txt"
            ) from exc

        self._period = period
        self._interval = interval

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
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

        fundamentals: dict = {}
        headlines: list[str] = []
        try:
            info = ticker.info
            if info.get("trailingPE"):
                fundamentals["pe_ratio"] = info["trailingPE"]
            if info.get("revenueGrowth") is not None:
                fundamentals["revenue_growth_yoy"] = info["revenueGrowth"]
        except Exception:
            pass  # fundamentals are best-effort; analysts already handle missing fields
        try:
            headlines = [
                item["title"]
                for item in (ticker.news or [])[:5]
                if item.get("title")
            ]
        except Exception:
            pass

        return MarketSnapshot(symbol=symbol, bars=bars, fundamentals=fundamentals, news_headlines=headlines)
