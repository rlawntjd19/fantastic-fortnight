"""Market/news data provider interfaces.

Only a deterministic, offline `SimulatedFeed` ships by default so the
package runs and tests pass with no network access and no brokerage
credentials. Wiring in a real market-data vendor is a matter of
implementing `MarketDataProvider` against that vendor's API — this
project intentionally does not ship a live order-execution connector.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Bar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class MarketSnapshot:
    symbol: str
    bars: list[Bar]
    fundamentals: dict = field(default_factory=dict)
    news_headlines: list[str] = field(default_factory=list)

    @property
    def last_price(self) -> float:
        return self.bars[-1].close

    @property
    def closes(self) -> list[float]:
        return [b.close for b in self.bars]


class MarketDataProvider(Protocol):
    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        ...


class SimulatedFeed:
    """Deterministic pseudo-random-walk feed for demos, backtests and tests."""

    def __init__(self, seed: int = 7, start_price: float = 1000.0, n_bars: int = 120) -> None:
        self._rng = random.Random(seed)
        self._start_price = start_price
        self._n_bars = n_bars

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        price = self._start_price
        bars: list[Bar] = []
        for i in range(self._n_bars):
            drift = self._rng.uniform(-0.01, 0.011)
            open_ = price
            close = max(0.01, open_ * (1 + drift))
            high = max(open_, close) * (1 + abs(self._rng.uniform(0, 0.004)))
            low = min(open_, close) * (1 - abs(self._rng.uniform(0, 0.004)))
            volume = self._rng.uniform(1_000, 10_000)
            bars.append(Bar(i, open_, high, low, close, volume))
            price = close
        return MarketSnapshot(
            symbol=symbol,
            bars=bars,
            fundamentals={"pe_ratio": 12.4, "revenue_growth_yoy": 0.18},
            news_headlines=[
                f"{symbol} sees institutional buying return after pullback",
                f"{symbol} faces resistance near recent highs",
            ],
        )
