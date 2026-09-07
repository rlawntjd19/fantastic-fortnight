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


# Broad-market/index ETFs are never S&P 500 "constituents" themselves but
# are explicitly in-scope per the mandate ("index ETFs, no mutual funds") —
# kept as their own small list so get_live_universe() can union them onto
# whatever the real constituent fetch returns, live runs only.
_BROAD_MARKET_ETFS: list[UniverseEntry] = [
    UniverseEntry("SPY", "index_etf", "Broad Market"),
    UniverseEntry("VOO", "index_etf", "Broad Market"),
    UniverseEntry("VTI", "index_etf", "Broad Market"),
    UniverseEntry("QQQ", "index_etf", "Large-Cap Growth"),
    UniverseEntry("DIA", "index_etf", "Broad Market"),
]

_SP500_WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def fetch_sp500_constituents() -> list[UniverseEntry]:
    """Fetches the real, current S&P 500 constituent list from Wikipedia's
    actively-maintained "List of S&P 500 companies" page — never a
    hardcoded/typed-from-memory ticker list, so index reconstitutions
    (additions, removals, ticker changes) show up on the next live run
    instead of silently going stale. Sector labels come straight from the
    page's own GICS Sector column (the real 11-sector GICS taxonomy, not
    this module's rougher static-universe buckets) — `screen_ineligible`
    and `PortfolioManager`'s diversification cap both just group by
    whatever string is here, so this is a drop-in.

    Raises on any fetch/parse failure — callers decide the fallback (see
    get_live_universe), the same way `MarketDataProvider.get_snapshot`
    raises rather than silently returning something plausible-looking.
    """
    import io

    import pandas as pd
    import requests

    # Wikipedia's servers reject requests with no identifying User-Agent
    # (their bot-traffic policy) — fetch the HTML ourselves with one, then
    # hand the raw text to pandas rather than letting pd.read_html(url)
    # make its own unidentified request.
    response = requests.get(
        _SP500_WIKIPEDIA_URL,
        headers={"User-Agent": "trading-agent-research-committee/1.0 (educational project, not investment advice)"},
        timeout=20,
    )
    response.raise_for_status()

    table = pd.read_html(io.StringIO(response.text))[0]  # the constituents table is always first on this page

    entries: list[UniverseEntry] = []
    seen_symbols: set[str] = set()
    for _, row in table.iterrows():
        raw_symbol = str(row.get("Symbol", "")).strip()
        if not raw_symbol or raw_symbol.lower() == "nan":
            continue
        # yfinance expects a dash for multi-class tickers (e.g. "BRK-B"),
        # Wikipedia lists them with a dot ("BRK.B").
        symbol = raw_symbol.replace(".", "-")
        if symbol in seen_symbols:
            continue
        seen_symbols.add(symbol)
        sector = str(row.get("GICS Sector", "")).strip() or "Unclassified"
        entries.append(UniverseEntry(symbol, "stock", sector))

    if len(entries) < 400:  # sanity floor: a real S&P 500 fetch should return ~500
        raise RuntimeError(f"parsed only {len(entries)} symbols from the S&P 500 page — page structure likely changed")

    return entries


def get_live_universe() -> list[UniverseEntry]:
    """The candidate universe for LIVE daily screening: real, freshly-
    fetched S&P 500 constituents plus the standing broad-market ETF list.
    Raises if the constituent fetch fails — `daily_report.run_daily_cycle`
    catches this and falls back to the static `UNIVERSE` below, so a
    Wikipedia outage/page change degrades the day's picking rather than
    crashing the whole run.

    `committee.backtest` deliberately keeps using the static `UNIVERSE`
    unchanged — this project's basket-size backtest evidence (see
    daily_report.py's LIVE_MIN_PICKS comment) was computed against that
    exact 40-name list; broadening the backtest's own candidate pool would
    need a fresh backtest run before it's evidence about anything.
    """
    sp500 = fetch_sp500_constituents()
    sp500_symbols = {e.symbol for e in sp500}
    return sp500 + [etf for etf in _BROAD_MARKET_ETFS if etf.symbol not in sp500_symbols]
