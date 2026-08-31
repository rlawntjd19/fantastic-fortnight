"""Build the configured market data and macro data providers.

Mirrors `forecast.factory.build_price_forecaster` / `llm.client.build_llm_client`:
falls back to the offline `SimulatedFeed`/`StaticMacroProvider` if live
data is enabled but the chosen provider's package/key isn't available.
It does NOT catch failures from an actual `get_snapshot()` call (bad
ticker, no network) — see yfinance_provider.py/alphavantage_provider.py
for why those are raised instead of silently masked.

`config.live_data.provider` picks the backend: `"yfinance"` (default) or
`"alphavantage"`.
"""
from __future__ import annotations

import sys

from trading_agent.data.macro import StaticMacroProvider
from trading_agent.data.providers import SimulatedFeed


def build_market_data_provider(config):
    if not config.live_data.enabled:
        return SimulatedFeed()

    try:
        if config.live_data.provider == "alphavantage":
            from trading_agent.data.alphavantage_provider import AlphaVantageFeed

            av = config.alphavantage
            return AlphaVantageFeed(
                api_key=av.api_key,
                requests_per_minute=av.requests_per_minute,
                include_fundamentals=av.include_fundamentals,
                include_news=av.include_news,
                include_realtime_quote=av.include_realtime_quote,
            )

        from trading_agent.data.yfinance_provider import YFinanceFeed

        return YFinanceFeed(period=config.live_data.period, interval=config.live_data.interval)
    except Exception as exc:  # noqa: BLE001 - missing/broken install must degrade, not crash
        print(
            f"[trading_agent] Live data provider unavailable ({exc}); falling back to simulated feed.",
            file=sys.stderr,
        )
        return SimulatedFeed()


def build_macro_provider(config):
    if not config.live_data.enabled:
        return StaticMacroProvider()

    try:
        if config.live_data.provider == "alphavantage":
            from trading_agent.data.alphavantage_provider import AlphaVantageMacroProvider

            av = config.alphavantage
            return AlphaVantageMacroProvider(api_key=av.api_key, requests_per_minute=av.requests_per_minute)

        from trading_agent.data.macro import YFinanceMacroProvider

        return YFinanceMacroProvider()
    except Exception as exc:  # noqa: BLE001 - missing/broken install must degrade, not crash
        print(
            f"[trading_agent] Macro data provider unavailable ({exc}); using a neutral static snapshot.",
            file=sys.stderr,
        )
        return StaticMacroProvider()
