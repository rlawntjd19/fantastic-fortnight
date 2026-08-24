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


def _generate_bars(rng: random.Random, start_price: float, n: int, start_index: int = 0) -> list[Bar]:
    price = start_price
    bars: list[Bar] = []
    for i in range(n):
        drift = rng.uniform(-0.01, 0.011)
        open_ = price
        close = max(0.01, open_ * (1 + drift))
        high = max(open_, close) * (1 + abs(rng.uniform(0, 0.004)))
        low = min(open_, close) * (1 - abs(rng.uniform(0, 0.004)))
        volume = rng.uniform(1_000, 10_000)
        bars.append(Bar(start_index + i, open_, high, low, close, volume))
        price = close
    return bars


@dataclass
class _SymbolState:
    rng: random.Random
    bars: list[Bar]
    next_index: int


class SimulatedFeed:
    """Deterministic pseudo-random-walk feed for demos, backtests and tests.

    Each symbol gets its own walk, seeded from `(seed, symbol)` so two
    different tickers never look identical and the same ticker is
    reproducible across fresh `SimulatedFeed` instances. Within a single
    instance, calling `get_snapshot` again for a symbol that's already
    been seen advances that symbol's walk by one more bar instead of
    regenerating it from scratch — this is what makes `cli.py watch`'s
    continuous loop see prices actually move between ticks, and what
    keeps a single one-shot call (the normal `signal` command) stable.
    """

    def __init__(self, seed: int = 7, start_price: float = 1000.0, n_bars: int = 120) -> None:
        self._seed = seed
        self._start_price = start_price
        self._n_bars = n_bars
        self._state: dict[str, _SymbolState] = {}

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        state = self._state.get(symbol)
        if state is None:
            rng = random.Random(f"{self._seed}:{symbol}")
            # Give different tickers visibly different price levels, not
            # just different wiggles, so it's obvious the symbol mattered.
            symbol_start_price = self._start_price * rng.uniform(0.3, 3.0)
            bars = _generate_bars(rng, symbol_start_price, self._n_bars)
            state = _SymbolState(rng=rng, bars=bars, next_index=self._n_bars)
            self._state[symbol] = state
        else:
            new_bar = _generate_bars(state.rng, state.bars[-1].close, 1, start_index=state.next_index)
            state.bars = (state.bars + new_bar)[-self._n_bars :]
            state.next_index += 1

        return MarketSnapshot(
            symbol=symbol,
            bars=list(state.bars),
            fundamentals={"pe_ratio": 12.4, "revenue_growth_yoy": 0.18},
            news_headlines=[
                f"{symbol} sees institutional buying return after pullback",
                f"{symbol} faces resistance near recent highs",
            ],
        )
