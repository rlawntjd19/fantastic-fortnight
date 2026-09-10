"""One-off: analyze a real Korean brokerage portfolio (KRW-listed ETFs
wrapping US/gold/China exposure) through the committee pipeline.

Two passes:
 1. Try candidate Korea-listed ticker codes and VERIFY each by name match
    -- never assume a guessed code is right (same discipline that caught
    the bogus SKHY quote earlier this session).
 2. Run the real committee assess_symbol on US-listed proxies for each
    underlying exposure, plus a real correlation matrix, since the
    committee's data pipeline and SPY-relative scoring are USD-native.

Not a permanent part of the pipeline; prints to the job log, then this
script and its workflow get deleted.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import sys

sys.path.insert(0, ".")

import pandas as pd
import yfinance as yf

from trading_agent.agents.researchers import ResearchManager
from trading_agent.committee.daily_report import assess_symbol
from trading_agent.committee.universe import BENCHMARK_SYMBOL, UniverseEntry
from trading_agent.config import DEFAULT_CONFIG
from trading_agent.data.factory import (
    build_macro_provider,
    build_market_data_provider,
    build_seasonal_history_provider,
)
from trading_agent.data.indicators import momentum
from trading_agent.forecast.factory import build_price_forecaster
from trading_agent.llm.client import build_llm_client

# Candidate Korea-listed codes, each with the name we EXPECT. Only trust a
# code whose returned name actually matches -- otherwise report it as
# unverified rather than silently analyzing the wrong fund.
KR_CANDIDATES = {
    "360750.KS": "TIGER 미국S&P500",
    "379810.KS": "KODEX 미국나스닥100",
    "411060.KS": "ACE KRX금현물",
    "371160.KS": "KODEX 차이나과창판STAR50",
}

# US-listed proxies for each underlying exposure the portfolio actually holds.
PROXIES = {
    "SPY": ("S&P 500 (TIGER 미국S&P500 underlying)", "index_etf"),
    "QQQM": ("Nasdaq-100 (KODEX 미국나스닥100 underlying)", "index_etf"),
    "GLD": ("Gold spot (ACE KRX금현물 underlying)", "index_etf"),
    "CQQQ": ("China tech (closest listed proxy for STAR50)", "index_etf"),
}

print("=" * 70)
print("PASS 1: Korea-listed codes -- verify by name match, never assume")
print("=" * 70)
for code, expected in KR_CANDIDATES.items():
    try:
        info = yf.Ticker(code).info
        name = info.get("longName") or info.get("shortName") or ""
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        currency = info.get("currency")
        if not name:
            print(f"  {code}: no data returned -- UNVERIFIED (expected {expected!r})")
            continue
        print(f"  {code}: name={name!r} price={price} {currency}")
        print(f"      expected {expected!r} -> {'LIKELY MATCH' if expected.split()[0].lower() in name.lower() else 'NAME MISMATCH -- do not trust'}")
    except Exception as exc:  # noqa: BLE001
        print(f"  {code}: fetch failed ({exc}) -- UNVERIFIED")

print()
print("=" * 70)
print("PASS 2: Real 1-year correlation across the underlying exposures")
print("=" * 70)
frames = {}
for symbol in PROXIES:
    hist = yf.Ticker(symbol).history(period="1y", interval="1d")
    frames[symbol] = hist["Close"].pct_change().dropna()
# USD/KRW too -- these are KRW-denominated wrappers on USD assets, so FX is
# a real, separate risk factor the holder is carrying whether they meant to or not.
fx = yf.Ticker("KRW=X").history(period="1y", interval="1d")
frames["USDKRW"] = fx["Close"].pct_change().dropna()

df = pd.DataFrame(frames).dropna()
print(f"(shared trading days: {len(df)}, {df.index[0].date()} to {df.index[-1].date()})\n")
print(df.corr().round(2).to_string())

print("\nReal annualized volatility (1y daily):")
for col in df.columns:
    print(f"  {col}: {df[col].std() * (252 ** 0.5):.1%}")

print("\nReal 1-year total return:")
for symbol in PROXIES:
    hist = yf.Ticker(symbol).history(period="1y", interval="1d")
    ret = hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1
    print(f"  {symbol}: {ret:+.1%}")
fx_ret = fx["Close"].iloc[-1] / fx["Close"].iloc[0] - 1
print(f"  USDKRW: {fx_ret:+.1%}  (positive = KRW weakened = unhedged USD holdings gained)")

print()
print("=" * 70)
print("PASS 3: Real committee assessment of each underlying exposure")
print("=" * 70)

live_data = dataclasses.replace(DEFAULT_CONFIG.live_data, enabled=True)
config = dataclasses.replace(DEFAULT_CONFIG, live_data=live_data)
llm = build_llm_client(config)
provider = build_market_data_provider(config)
macro_provider = build_macro_provider(config)
seasonal_provider = build_seasonal_history_provider(config)
forecaster = build_price_forecaster(config)

from trading_agent.agents.analysts import (
    FundamentalAnalyst, MacroAnalyst, SeasonalityAnalyst, SentimentAnalyst, TechnicalAnalyst, ForecastAnalyst,
)
analysts = {
    "technical": TechnicalAnalyst(llm),
    "fundamental": FundamentalAnalyst(llm),
    "sentiment": SentimentAnalyst(llm),
    "macro": MacroAnalyst(llm, macro_provider),
    "forecast": ForecastAnalyst(llm, forecaster),
    "seasonality": SeasonalityAnalyst(llm),
}
research_manager = ResearchManager(llm)
spy_snapshot = provider.get_snapshot(BENCHMARK_SYMBOL)
spy_momentum = momentum(spy_snapshot.closes, 10)
today = dt.date.today()

for symbol, (label, sec_type) in PROXIES.items():
    print(f"\n{'-'*55}\n{symbol} -- {label}\n{'-'*55}")
    try:
        snapshot = provider.get_snapshot(symbol)
        seasonal_snapshot = seasonal_provider.get_snapshot(symbol) if seasonal_provider else None
        entry = UniverseEntry(symbol, sec_type, "n/a")
        a = assess_symbol(
            entry, snapshot, spy_momentum, analysts, research_manager,
            seasonal_snapshot=seasonal_snapshot, as_of=today,
        )
        print(f"  Composite score: {a.composite_score:+.4f}")
        print(f"  Consensus: {a.debate.consensus_signal.value} (confidence {a.debate.consensus_confidence:.2f})")
        if a.volatility:
            print(f"  Realized vol (20-bar ann.): {a.volatility:.2%}")
        if a.relative_strength_vs_spy is not None:
            print(f"  Relative strength vs SPY (10-bar): {a.relative_strength_vs_spy:+.2%}")
        for r in a.analyst_reports:
            print(f"    [{r.agent_name}] {r.signal.value} (conf {r.confidence:.2f}) -- {r.summary}")
    except Exception as exc:  # noqa: BLE001
        print(f"  Assessment failed: {exc}")
