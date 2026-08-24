"""tool_get_price_local.py — read the latest price for a symbol from
whatever `MarketDataProvider` is configured (`SimulatedFeed` by default,
`YFinanceFeed` when live data is enabled).

Functionally this is just `provider.get_snapshot(symbol).last_price`,
already used throughout the pipeline (`TradingCycle.fetch_snapshot`) —
this module exists as a stable, directly-importable entry point for
other code that wants just the price without building a whole cycle.
"""
from __future__ import annotations

from trading_agent.data.providers import MarketDataProvider


def get_latest_price(provider: MarketDataProvider, symbol: str) -> float:
    return provider.get_snapshot(symbol).last_price
