"""Build the configured market data and macro data providers.

Mirrors `forecast.factory.build_price_forecaster` / `llm.client.build_llm_client`:
falls back to the offline `SimulatedFeed`/`StaticMacroProvider` if live
data is enabled but `yfinance` isn't installed. It does NOT catch
failures from an actual `get_snapshot()` call (bad ticker, no network) —
see yfinance_provider.py for why those are raised instead of silently
masked.
"""
from __future__ import annotations

import sys

from trading_agent.data.macro import StaticMacroProvider
from trading_agent.data.providers import SimulatedFeed


def build_market_data_provider(config):
    if not config.live_data.enabled:
        return SimulatedFeed()

    try:
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
        from trading_agent.data.macro import YFinanceMacroProvider

        return YFinanceMacroProvider()
    except Exception as exc:  # noqa: BLE001 - missing/broken install must degrade, not crash
        print(
            f"[trading_agent] Macro data provider unavailable ({exc}); using a neutral static snapshot.",
            file=sys.stderr,
        )
        return StaticMacroProvider()
