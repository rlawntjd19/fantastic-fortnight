import sys
sys.path.insert(0, ".")
import yfinance as yf

for symbol in ["SKHY", "SKHYX"]:
    try:
        info = yf.Ticker(symbol).info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        exchange = info.get("exchange", "?")
        quote_type = info.get("quoteType", "?")
        long_name = info.get("longName") or info.get("shortName") or "?"
        print(f"{symbol}: name={long_name!r} exchange={exchange} type={quote_type} price={price}")
    except Exception as exc:  # noqa: BLE001
        print(f"{symbol}: fetch failed ({exc})")
