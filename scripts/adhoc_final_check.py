"""One-off, final pre-submission check for Option A (QQQM 57 / NBIS 22 /
SMH 5) against the Emory FIN 483 Stock Picks Assignment rubric. Reuses
the committee's actual `screen_ineligible` function (not a re-implementation)
so the eligibility verdict is exactly the same code path the live pipeline
uses. Not a permanent part of the pipeline; prints to the job log, then
this script and its workflow get deleted.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import yfinance as yf

from trading_agent.committee.universe import UniverseEntry, screen_ineligible

POSITIONS = [
    ("QQQM", 57, "index_etf"),
    ("NBIS", 22, "stock"),
    ("SMH", 5, "index_etf"),
]

_ALLOWED_EXCHANGES = {"NYSE", "AMEX", "NASDAQ"}
# yfinance exchange codes -> the assignment's own NYSE/AMEX/NASDAQ language
_EXCHANGE_LABELS = {
    "NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ",
    "NYQ": "NYSE", "ASE": "AMEX", "PCX": "NYSE Arca (NYSE)",
    "BTS": "Cboe BZX", "BATS": "Cboe BZX",
}


def main() -> None:
    print("=" * 70)
    print("FINAL PRE-SUBMISSION CHECK -- Option A")
    print("=" * 70)

    total_value = 0.0
    all_pass = True

    for symbol, shares, sec_type in POSITIONS:
        print(f"\n{symbol} -- {shares} shares")
        print("-" * 40)
        ticker = yf.Ticker(symbol)
        info = ticker.info

        price = info.get("currentPrice") or info.get("regularMarketPrice")
        exchange_code = info.get("exchange", "?")
        exchange_label = _EXCHANGE_LABELS.get(exchange_code, exchange_code)
        market_cap = info.get("marketCap")
        total_assets = info.get("totalAssets")
        quote_type = info.get("quoteType", "?")
        long_name = info.get("longName") or info.get("shortName") or "?"

        value = shares * price if price else 0.0
        total_value += value

        print(f"  Name: {long_name}")
        print(f"  Fresh price: ${price}")
        print(f"  Position value: {shares} x ${price} = ${value:,.2f}")
        print(f"  Exchange: {exchange_code} -> {exchange_label}")
        print(f"  Quote type: {quote_type}")
        print(f"  Market cap: {market_cap}")
        print(f"  Total assets (ETF AUM): {total_assets}")

        # Rule-by-rule, explicit
        checks = []
        checks.append(("Trades on NYSE/AMEX/NASDAQ", exchange_code in _EXCHANGE_LABELS and "NASDAQ" in exchange_label or exchange_label in ("NYSE", "AMEX") or exchange_code in {"NMS", "NGM", "NCM", "NYQ", "ASE"}))
        checks.append(("Not a 5-letter ticker ending in X", not (len(symbol) == 5 and symbol.isalpha() and symbol.upper().endswith("X"))))
        checks.append(("Not a raw stock index (is a fund/stock)", quote_type in ("ETF", "EQUITY")))
        checks.append((f"Price > $5.00 (actual: ${price})", price is not None and price > 5.0))
        if quote_type == "ETF":
            checks.append((f"ETF AUM > $500M (actual: ${total_assets:,.0f})" if total_assets else "ETF AUM > $500M (missing data)", total_assets is not None and total_assets > 500_000_000))
        else:
            checks.append((f"Market cap > $500M (actual: ${market_cap:,.0f})" if market_cap else "Market cap > $500M (missing data)", market_cap is not None and market_cap > 500_000_000))

        for label, passed in checks:
            status = "PASS" if passed else "FAIL"
            if not passed:
                all_pass = False
            print(f"    [{status}] {label}")

        # Also run the committee's own real screen_ineligible() function directly
        entry = UniverseEntry(symbol, sec_type, "n/a")
        fundamentals = {"exchange": exchange_code, "market_cap": market_cap, "total_assets": total_assets}
        reason = screen_ineligible(entry, fundamentals, price)
        print(f"  Committee's own screen_ineligible() verdict: {'PASS' if reason is None else 'FAIL -- ' + reason}")
        if reason is not None:
            all_pass = False

    print("\n" + "=" * 70)
    print("PORTFOLIO-LEVEL CHECKS")
    print("=" * 70)
    n_tickers = len(POSITIONS)
    print(f"  Number of distinct tickers: {n_tickers} (rule: 2-5) -> {'PASS' if 2 <= n_tickers <= 5 else 'FAIL'}")
    print(f"  Total investment: ${total_value:,.2f} (rule: $23,000-$27,000) -> "
          f"{'PASS' if 23_000 <= total_value <= 27_000 else 'FAIL'}")
    print(f"  Distance from $25,000 target: ${total_value - 25_000:+,.2f} ({(total_value-25_000)/25_000:+.2%})")

    print("\n" + "=" * 70)
    print(f"OVERALL: {'ALL CHECKS PASS' if all_pass else 'AT LEAST ONE CHECK FAILED -- REVIEW ABOVE'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
