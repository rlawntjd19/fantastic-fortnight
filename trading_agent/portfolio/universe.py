"""Candidate universe for portfolio construction.

A fixed, sector-tagged list of large-cap US common stocks plus a handful
of low-cost, broad/sector ETFs — long-only-eligible, exchange-traded,
no mutual funds and no derivatives. Sector tags drive the
diversification cap in `selection.select_portfolio` — the goal is a
universe broad enough that a 2-5 name portfolio can still span several
sectors (or blend single-name conviction picks with a diversified ETF
core) instead of concentrating in whichever name happens to screen best
that day. ETFs get their own "(ETF)" sector tag rather than sharing their
underlying sector's tag, so e.g. XLF and JPM can both be picked without
tripping the same-sector cap — a single-name financial and a
diversified financials basket are not the same concentration risk.

Extending this: add an entry here; nothing else needs to change, since
`pipeline.run_portfolio_research` iterates this list generically. Every
analyst here already treats missing fundamentals data as optional (see
`agents/analysts.py`), so ETFs — which `yfinance` reports far fewer
fundamentals fields for than single stocks — degrade gracefully rather
than erroring.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UniverseEntry:
    symbol: str
    sector: str


UNIVERSE: list[UniverseEntry] = [
    UniverseEntry("AAPL", "Technology"),
    UniverseEntry("MSFT", "Technology"),
    UniverseEntry("NVDA", "Technology"),
    UniverseEntry("GOOGL", "Communication Services"),
    UniverseEntry("META", "Communication Services"),
    UniverseEntry("AMZN", "Consumer Discretionary"),
    UniverseEntry("HD", "Consumer Discretionary"),
    UniverseEntry("JPM", "Financials"),
    UniverseEntry("V", "Financials"),
    UniverseEntry("UNH", "Health Care"),
    UniverseEntry("LLY", "Health Care"),
    UniverseEntry("XOM", "Energy"),
    UniverseEntry("COST", "Consumer Staples"),
    UniverseEntry("CAT", "Industrials"),
    # Broad/sector ETFs: exchange-traded, long-only, not mutual funds.
    UniverseEntry("VTI", "Diversified (ETF)"),
    UniverseEntry("QQQ", "Technology (ETF)"),
    UniverseEntry("XLF", "Financials (ETF)"),
    UniverseEntry("XLV", "Health Care (ETF)"),
    UniverseEntry("XLE", "Energy (ETF)"),
]

# Market proxy used for beta/Treynor and for the historical-backtest
# comparison line. Not itself eligible for selection (it's an index ETF,
# not a stock the manager is choosing between).
BENCHMARK_SYMBOL = "SPY"
