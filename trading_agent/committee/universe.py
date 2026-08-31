"""The fixed candidate universe the committee screens every day, plus the
screening rules that keep it to "US stocks, no small-cap" and "index ETFs,
no mutual funds" per the mandate.

The list itself is a static starting universe (diversified across sectors
so the diversification cap in `PortfolioManager` has something to work
with) — it is deliberately not "the whole market" so a daily run stays fast
and each name has a real, checkable reason to be considered. Anything not
in this list is simply never evaluated; nothing here is investment advice.
"""
from __future__ import annotations

from dataclasses import dataclass

# Full eligibility rubric (as specified for this mandate):
#   - Trades on NYSE, AMEX, or NASDAQ; stocks, ADRs, or ETFs only.
#   - Not an open-end mutual fund (5-letter ticker ending in "X").
#   - Not a raw stock index itself (an index *fund*/ETF is fine).
#   - Price > $5.00/share at entry (no penny stocks).
#   - Market cap > $500M (stocks) / AUM > $500M (ETFs) — the rubric's hard
#     floor. The committee's own "no small-cap" preference from the mandate
#     sits well above that floor (see MIN_MARKET_CAP_USD below); every name
#     in this static universe already clears the higher bar comfortably.
MIN_PRICE_USD = 5.0
MIN_ETF_AUM_USD = 500_000_000.0

# "No small-cap" cutoff: standard small-cap/mid-cap boundary is roughly
# $2B, so anything below that is excluded even though the rubric's own
# floor (above) is looser at $500M.
MIN_MARKET_CAP_USD = 2_000_000_000.0

# yfinance `exchange` codes seen for NYSE/AMEX/NASDAQ-listed equities and
# ETFs (Nasdaq tiers NMS/NGM/NCM, NYSE NYQ, NYSE American/AMEX ASE, NYSE
# Arca PCX for most ETFs, BATS/Cboe BZX for a handful of ETFs). Best-effort:
# a missing code doesn't block a name (the static universe below is already
# 100% NYSE/NASDAQ-listed), it only catches something that clearly isn't.
_ALLOWED_EXCHANGE_CODES = {"NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "BTS", "BATS"}

# Benchmark every pick is measured against for the outperformance OKR.
BENCHMARK_SYMBOL = "SPY"


@dataclass(frozen=True)
class UniverseEntry:
    symbol: str
    security_type: str  # "stock" | "index_etf"
    sector: str  # static fallback label; live fundamentals override when available


UNIVERSE: list[UniverseEntry] = [
    # -- Technology --
    UniverseEntry("AAPL", "stock", "Technology"),
    UniverseEntry("MSFT", "stock", "Technology"),
    UniverseEntry("NVDA", "stock", "Technology"),
    UniverseEntry("GOOGL", "stock", "Technology"),
    UniverseEntry("META", "stock", "Technology"),
    UniverseEntry("AVGO", "stock", "Technology"),
    UniverseEntry("CRM", "stock", "Technology"),
    UniverseEntry("ADBE", "stock", "Technology"),
    UniverseEntry("AMD", "stock", "Technology"),
    UniverseEntry("ORCL", "stock", "Technology"),
    # -- Consumer --
    UniverseEntry("AMZN", "stock", "Consumer"),
    UniverseEntry("COST", "stock", "Consumer"),
    UniverseEntry("WMT", "stock", "Consumer"),
    UniverseEntry("HD", "stock", "Consumer"),
    UniverseEntry("MCD", "stock", "Consumer"),
    UniverseEntry("NKE", "stock", "Consumer"),
    # -- Healthcare --
    UniverseEntry("UNH", "stock", "Healthcare"),
    UniverseEntry("LLY", "stock", "Healthcare"),
    UniverseEntry("JNJ", "stock", "Healthcare"),
    UniverseEntry("ABBV", "stock", "Healthcare"),
    UniverseEntry("MRK", "stock", "Healthcare"),
    # -- Financials --
    UniverseEntry("JPM", "stock", "Financials"),
    UniverseEntry("V", "stock", "Financials"),
    UniverseEntry("MA", "stock", "Financials"),
    UniverseEntry("GS", "stock", "Financials"),
    UniverseEntry("BRK-B", "stock", "Financials"),
    # -- Industrials / Energy --
    UniverseEntry("CAT", "stock", "Industrials"),
    UniverseEntry("HON", "stock", "Industrials"),
    UniverseEntry("GE", "stock", "Industrials"),
    UniverseEntry("XOM", "stock", "Energy"),
    UniverseEntry("CVX", "stock", "Energy"),
    # -- Communication / Staples --
    UniverseEntry("NFLX", "stock", "Communication"),
    UniverseEntry("DIS", "stock", "Communication"),
    UniverseEntry("PG", "stock", "Staples"),
    UniverseEntry("KO", "stock", "Staples"),
    # -- Broad-market index ETFs (never a mutual fund: all are exchange-traded) --
    UniverseEntry("SPY", "index_etf", "Broad Market"),
    UniverseEntry("VOO", "index_etf", "Broad Market"),
    UniverseEntry("VTI", "index_etf", "Broad Market"),
    UniverseEntry("QQQ", "index_etf", "Large-Cap Growth"),
    UniverseEntry("DIA", "index_etf", "Broad Market"),
]


def screen_ineligible(entry: UniverseEntry, fundamentals: dict, last_price: float) -> str | None:
    """Returns a human-readable exclusion reason, or None if `entry` clears
    the full eligibility rubric. Every field is read defensively — a field
    yfinance doesn't expose for a given ticker is treated as "can't verify,
    don't block" (same pattern the analysts use), except the two rules the
    static universe itself already guarantees structurally (ticker shape,
    security type) and the exchange check, which only rejects a code that's
    positively known to be wrong."""
    symbol = entry.symbol

    if len(symbol) == 5 and symbol.isalpha() and symbol.upper().endswith("X"):
        return f"{symbol}: 5-letter ticker ending in X — open-end mutual fund pattern, excluded"
    if symbol.startswith("^"):
        return f"{symbol}: raw index ticker, not a tradable security — excluded"

    exchange = fundamentals.get("exchange")
    if exchange and exchange not in _ALLOWED_EXCHANGE_CODES:
        return f"{symbol}: exchange code '{exchange}' is not NYSE/AMEX/NASDAQ — excluded"

    if last_price is not None and last_price <= MIN_PRICE_USD:
        return f"{symbol}: price ${last_price:.2f} at or below the ${MIN_PRICE_USD:.2f} floor — excluded"

    if entry.security_type == "stock":
        market_cap = fundamentals.get("market_cap")
        if market_cap is not None and market_cap < MIN_MARKET_CAP_USD:
            return f"{symbol}: market cap ${market_cap:,.0f} below the ${MIN_MARKET_CAP_USD:,.0f} no-small-cap screen"
    else:
        aum = fundamentals.get("total_assets")
        if aum is not None and aum < MIN_ETF_AUM_USD:
            return f"{symbol}: AUM ${aum:,.0f} below the ${MIN_ETF_AUM_USD:,.0f} ETF floor — excluded"

    return None
