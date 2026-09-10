import sys
sys.path.insert(0, ".")
import yfinance as yf

fx = yf.Ticker("KRW=X")  # USD/KRW
fx_info = fx.info
rate = fx_info.get("regularMarketPrice") or fx_info.get("currentPrice")
print(f"Live USD/KRW rate: {rate}")

skhy = yf.Ticker("SKHY").info
krx = yf.Ticker("000660.KS").info

skhy_price = skhy.get("currentPrice") or skhy.get("regularMarketPrice")
krx_price_krw = krx.get("currentPrice") or krx.get("regularMarketPrice")
skhy_shares = skhy.get("sharesOutstanding")
krx_shares = krx.get("sharesOutstanding")

print(f"SKHY price: ${skhy_price}")
print(f"000660.KS price: {krx_price_krw} KRW")
print(f"SKHY shares outstanding: {skhy_shares}")
print(f"000660.KS shares outstanding: {krx_shares}")
ratio = skhy_shares / krx_shares if skhy_shares and krx_shares else None
print(f"Shares-outstanding ratio (SKHY / KRX): {ratio}")

if rate and ratio:
    krx_price_usd_per_ordinary = krx_price_krw / rate
    implied_adr_price = krx_price_usd_per_ordinary / ratio
    print(f"\nKRX ordinary share in USD (at live rate): ${krx_price_usd_per_ordinary:.2f}")
    print(f"Implied SKHY ADR fair value (KRX price / ADR ratio): ${implied_adr_price:.2f}")
    print(f"Actual SKHY price: ${skhy_price:.2f}")
    print(f"Premium/discount vs implied parity: {(skhy_price/implied_adr_price - 1):+.1%}")
