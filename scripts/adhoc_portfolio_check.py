"""One-off: fetch real data for a user-proposed basket (QQQM, NBIS, CRWV,
SPYG, and the ticker the user wrote as "SKHL") and check each against the
committee's own eligibility rubric (trading_agent/committee/universe.py).
Not a permanent part of the pipeline -- prints results to the job log for
a human to read, then this script and its workflow get deleted.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import yfinance as yf

from trading_agent.committee.universe import (
    MIN_ETF_AUM_USD,
    MIN_MARKET_CAP_USD,
    MIN_PRICE_USD,
)

CANDIDATES = ["QQQM", "NBIS", "CRWV", "SPYG", "SKHL"]


def main() -> None:
    for symbol in CANDIDATES:
        print("=" * 60)
        print(symbol)
        print("=" * 60)
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED to fetch: {exc}")
            continue

        if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
            print(f"  No usable data returned -- likely not a real/tradable ticker.")
            print(f"  Raw info keys present: {sorted(info.keys())[:10] if info else 'EMPTY'}")
            continue

        long_name = info.get("longName") or info.get("shortName") or "?"
        quote_type = info.get("quoteType", "?")
        exchange = info.get("exchange", "?")
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        market_cap = info.get("marketCap")
        total_assets = info.get("totalAssets")  # ETFs
        category = info.get("category", "?")
        expense_ratio = info.get("annualReportExpenseRatio") or info.get("netExpenseRatio")
        ytd_return = info.get("ytdReturn")
        beta = info.get("beta") or info.get("beta3Year")
        sector = info.get("sector", "?")

        print(f"  Name: {long_name}")
        print(f"  Type: {quote_type} | Exchange: {exchange} | Sector/Category: {sector or category}")
        print(f"  Price: {price}")
        print(f"  Market cap: {market_cap}")
        print(f"  Total assets (ETF AUM): {total_assets}")
        print(f"  Expense ratio: {expense_ratio}")
        print(f"  Beta: {beta}")
        print(f"  YTD return: {ytd_return}")

        # Eligibility rubric checks (mirrors universe.screen_ineligible)
        reasons = []
        if len(symbol) == 5 and symbol.isalpha() and symbol.upper().endswith("X"):
            reasons.append("5-letter ticker ending in X -- open-end mutual fund pattern")
        if price is not None and price <= MIN_PRICE_USD:
            reasons.append(f"price ${price:.2f} at/below ${MIN_PRICE_USD:.2f} floor")
        if quote_type == "ETF":
            if total_assets is not None and total_assets < MIN_ETF_AUM_USD:
                reasons.append(f"ETF AUM ${total_assets:,.0f} below ${MIN_ETF_AUM_USD:,.0f} floor")
        else:
            if market_cap is not None and market_cap < MIN_MARKET_CAP_USD:
                reasons.append(f"market cap ${market_cap:,.0f} below ${MIN_MARKET_CAP_USD:,.0f} no-small-cap screen")

        if reasons:
            print(f"  ELIGIBILITY: FAIL -- {'; '.join(reasons)}")
        else:
            print(f"  ELIGIBILITY: PASS (per committee rubric)")

        # Real 1-year price history for volatility/momentum context
        try:
            hist = ticker.history(period="1y", interval="1d")
            if not hist.empty:
                closes = hist["Close"]
                one_yr_return = (closes.iloc[-1] / closes.iloc[0]) - 1
                daily_returns = closes.pct_change().dropna()
                annualized_vol = daily_returns.std() * (252 ** 0.5)
                print(f"  1y price return (real): {one_yr_return:+.2%}")
                print(f"  Annualized volatility (real, 1y daily): {annualized_vol:.2%}")
        except Exception as exc:  # noqa: BLE001
            print(f"  History fetch failed: {exc}")

        print()


if __name__ == "__main__":
    main()
