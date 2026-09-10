"""One-off: fetch real, current prices + eligibility fields for the
five-ticker mix (QQQM, SPYG, NBIS, CRWV, SMH) so a $25,000 (+/- $2,000)
share allocation can be computed for a real, graded assignment with a
hard entry-price basis (today's market open). Confirms SMH's eligibility
(not yet checked) alongside fresh quotes for the other four. Not a
permanent part of the pipeline; prints to the job log, then this script
and its workflow get deleted.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import yfinance as yf

from trading_agent.committee.universe import MIN_ETF_AUM_USD, MIN_MARKET_CAP_USD, MIN_PRICE_USD

TICKERS = ["QQQM", "SPYG", "NBIS", "CRWV", "SMH"]


def main() -> None:
    for symbol in TICKERS:
        print("=" * 60)
        print(symbol)
        print("=" * 60)
        ticker = yf.Ticker(symbol)
        info = ticker.info
        long_name = info.get("longName") or info.get("shortName") or "?"
        quote_type = info.get("quoteType", "?")
        exchange = info.get("exchange", "?")
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
        market_cap = info.get("marketCap")
        total_assets = info.get("totalAssets")

        print(f"  Name: {long_name}")
        print(f"  Type: {quote_type} | Exchange: {exchange}")
        print(f"  Current/last price: {price}")
        print(f"  Previous close: {prev_close}")
        print(f"  Market cap: {market_cap}")
        print(f"  Total assets (ETF AUM): {total_assets}")

        reasons = []
        if len(symbol) == 5 and symbol.isalpha() and symbol.upper().endswith("X"):
            reasons.append("5-letter ticker ending in X")
        if price is not None and price <= MIN_PRICE_USD:
            reasons.append(f"price ${price:.2f} at/below ${MIN_PRICE_USD:.2f} floor")
        if quote_type == "ETF":
            if total_assets is not None and total_assets < MIN_ETF_AUM_USD:
                reasons.append(f"ETF AUM ${total_assets:,.0f} below ${MIN_ETF_AUM_USD:,.0f} floor")
        else:
            if market_cap is not None and market_cap < MIN_MARKET_CAP_USD:
                reasons.append(f"market cap ${market_cap:,.0f} below ${MIN_MARKET_CAP_USD:,.0f} floor")

        print(f"  ELIGIBILITY: {'FAIL -- ' + '; '.join(reasons) if reasons else 'PASS'}")
        print()


if __name__ == "__main__":
    main()
