"""One-off: (1) precise real correlation between QQQM and SMH to settle
whether both are needed, and (2) run the real committee analyst pipeline
(same assess_symbol code path as every other check in this session)
against ADBE and SNDK as candidate replacements/additions, plus their
real eligibility and correlation to the existing basket. Not a permanent
part of the pipeline; prints to the job log, then this script and its
workflow get deleted.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import sys

sys.path.insert(0, ".")

import yfinance as yf

from trading_agent.agents.researchers import ResearchManager
from trading_agent.committee.daily_report import assess_symbol
from trading_agent.committee.universe import BENCHMARK_SYMBOL, UniverseEntry, screen_ineligible
from trading_agent.config import DEFAULT_CONFIG
from trading_agent.data.factory import (
    build_macro_provider,
    build_market_data_provider,
    build_seasonal_history_provider,
)
from trading_agent.data.indicators import momentum
from trading_agent.forecast.factory import build_price_forecaster
from trading_agent.llm.client import build_llm_client

BASKET_FOR_CORR = ["QQQM", "NBIS", "CRWV", "SMH", "ADBE", "SNDK"]

print("=" * 70)
print("Real 1-year correlation matrix (existing basket + candidates)")
print("=" * 70)

import pandas as pd

frames = {}
for symbol in BASKET_FOR_CORR:
    hist = yf.Ticker(symbol).history(period="1y", interval="1d")
    frames[symbol] = hist["Close"].pct_change().dropna()
df = pd.DataFrame(frames).dropna()
print(f"(shared trading days: {len(df)}, {df.index[0].date()} to {df.index[-1].date()})\n")
print(df.corr().round(2).to_string())

print()
print("=" * 70)
print("Eligibility + real committee assessment: ADBE, SNDK")
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

for symbol in ["ADBE", "SNDK"]:
    print(f"\n{'-'*50}\n{symbol}\n{'-'*50}")
    info = yf.Ticker(symbol).info
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    exchange = info.get("exchange", "?")
    market_cap = info.get("marketCap")
    sector = info.get("sector", "?")
    long_name = info.get("longName") or info.get("shortName") or "?"
    print(f"  Name: {long_name} | Sector: {sector} | Exchange: {exchange}")
    print(f"  Price: {price} | Market cap: {market_cap}")

    entry = UniverseEntry(symbol, "stock", sector or "n/a")
    reason = screen_ineligible(entry, {"exchange": exchange, "market_cap": market_cap}, price)
    print(f"  screen_ineligible() verdict: {'PASS' if reason is None else 'FAIL -- ' + reason}")

    try:
        snapshot = provider.get_snapshot(symbol)
        seasonal_snapshot = seasonal_provider.get_snapshot(symbol) if seasonal_provider else None
        assessment = assess_symbol(
            entry, snapshot, spy_momentum, analysts, research_manager,
            seasonal_snapshot=seasonal_snapshot, as_of=today,
        )
        print(f"  Composite score: {assessment.composite_score:+.4f}")
        print(f"  Consensus: {assessment.debate.consensus_signal.value} (confidence {assessment.debate.consensus_confidence:.2f})")
        print(f"  Realized volatility (20-bar ann.): {assessment.volatility:.2%}" if assessment.volatility else "  Volatility: n/a")
        print(f"  Relative strength vs SPY (10-bar): {assessment.relative_strength_vs_spy:+.2%}" if assessment.relative_strength_vs_spy is not None else "")
        for r in assessment.analyst_reports:
            print(f"    [{r.agent_name}] {r.signal.value} (conf {r.confidence:.2f}) -- {r.summary}")
    except Exception as exc:  # noqa: BLE001
        print(f"  Assessment failed: {exc}")
