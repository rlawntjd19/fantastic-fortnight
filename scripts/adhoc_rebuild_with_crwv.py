"""One-off: (1) check whether SK Hynix has any real NYSE/AMEX/NASDAQ-listed
instrument (it's primarily Korea Exchange-listed; check known OTC ADR
tickers for real exchange data rather than assuming), and (2) rebuild the
mix with CoreWeave folded back in at real, current prices, checked against
the committee's actual screen_ineligible() function. Not a permanent part
of the pipeline; prints to the job log, then this script and its
workflow get deleted.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import yfinance as yf

from trading_agent.committee.universe import UniverseEntry, screen_ineligible

print("=" * 70)
print("SK Hynix -- checking for any real NYSE/AMEX/NASDAQ-listed instrument")
print("=" * 70)

sk_hynix_candidates = ["000660.KS", "HXSCF", "HXSCL", "SKHYY", "SKHYF"]
for symbol in sk_hynix_candidates:
    try:
        info = yf.Ticker(symbol).info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        exchange = info.get("exchange", "?")
        quote_type = info.get("quoteType", "?")
        long_name = info.get("longName") or info.get("shortName") or "?"
        if price is None and not long_name or long_name == "?":
            print(f"  {symbol}: no usable data (likely not a real/tradable ticker)")
            continue
        print(f"  {symbol}: {long_name} | exchange={exchange} | type={quote_type} | price={price}")
    except Exception as exc:  # noqa: BLE001
        print(f"  {symbol}: fetch failed ({exc})")

print()
print("=" * 70)
print("Rebuilt mix: QQQM / NBIS / CRWV / SMH -- fresh prices + eligibility")
print("=" * 70)

WEIGHTS = {"QQQM": 0.30, "NBIS": 0.30, "CRWV": 0.25, "SMH": 0.15}
SEC_TYPE = {"QQQM": "index_etf", "NBIS": "stock", "CRWV": "stock", "SMH": "index_etf"}
BUDGET = 25_000

prices = {}
for symbol in WEIGHTS:
    info = yf.Ticker(symbol).info
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    exchange = info.get("exchange", "?")
    market_cap = info.get("marketCap")
    total_assets = info.get("totalAssets")
    quote_type = info.get("quoteType", "?")
    prices[symbol] = price

    print(f"\n{symbol}: price=${price}  exchange={exchange}  type={quote_type}  "
          f"market_cap={market_cap}  AUM={total_assets}")

    entry = UniverseEntry(symbol, SEC_TYPE[symbol], "n/a")
    fundamentals = {"exchange": exchange, "market_cap": market_cap, "total_assets": total_assets}
    reason = screen_ineligible(entry, fundamentals, price)
    print(f"  screen_ineligible() verdict: {'PASS' if reason is None else 'FAIL -- ' + reason}")

print()
print("--- Suggested whole-share allocation (target sum near $25,000) ---")
for symbol, w in WEIGHTS.items():
    target_dollars = BUDGET * w
    shares = int(target_dollars // prices[symbol])
    print(f"  {symbol}: target ${target_dollars:,.0f} / price ${prices[symbol]:.2f} -> {shares} shares "
          f"(~${shares*prices[symbol]:,.2f})")
