import sys
sys.path.insert(0, ".")
import yfinance as yf

t = yf.Ticker("SKHY")
info = t.info
fields = [
    "longName", "shortName", "exchange", "fullExchangeName", "exchangeTimezoneName",
    "quoteType", "currency", "financialCurrency", "currentPrice", "regularMarketPrice",
    "marketCap", "sharesOutstanding", "regularMarketVolume", "averageVolume",
    "averageVolume10days", "regularMarketDayHigh", "regularMarketDayLow",
    "bid", "ask", "bidSize", "askSize", "quoteSourceName", "market",
    "underlyingSymbol", "symbol", "region", "typeDisp",
]
for f in fields:
    print(f"  {f}: {info.get(f)}")

print()
print("--- 5-day history ---")
hist = t.history(period="5d", interval="1d")
print(hist.to_string() if not hist.empty else "EMPTY")

print()
print("--- Compare to real 000660.KS (Korea Exchange primary listing) ---")
kr = yf.Ticker("000660.KS")
kr_info = kr.info
print(f"  000660.KS price: {kr_info.get('currentPrice') or kr_info.get('regularMarketPrice')} {kr_info.get('currency')}")
print(f"  000660.KS market cap: {kr_info.get('marketCap')}")
print(f"  000660.KS shares outstanding: {kr_info.get('sharesOutstanding')}")
