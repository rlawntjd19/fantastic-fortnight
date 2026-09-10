"""One-off: measure the opportunity set OUTSIDE the client's current four
holdings -- fixed income, international developed, EM, Korea, and the
AI-thesis single names validated earlier this session.

Answers three questions with real data, not assertion:
  1. Does adding bonds actually reduce this portfolio's variance right now?
     (Post-2022 the stock/bond correlation has NOT been reliably negative --
     measure it rather than repeating the textbook.)
  2. Do international/EM/Korea sleeves diversify a US-mega-cap book?
  3. What does the committee say about each candidate on its own merits?

Not a permanent part of the pipeline; prints to the job log, then this
script and its workflow get deleted.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import sys

sys.path.insert(0, ".")

import numpy as np
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

HELD = ["SPY", "QQQM", "GLD"]          # post-restructure book
CANDIDATES = {
    "AGG":  "US aggregate bond",
    "IEF":  "US Treasury 7-10y",
    "TLT":  "US Treasury 20y+",
    "VEA":  "Developed intl ex-US",
    "VWO":  "Emerging markets",
    "EWY":  "South Korea (Samsung/SK Hynix heavy)",
    "MU":   "Micron -- AI memory (committee +1.00 earlier)",
    "NBIS": "Nebius -- AI cloud (committee +1.00 earlier)",
}
ALL = HELD + list(CANDIDATES)


def daily_returns(symbol):
    hist = yf.Ticker(symbol).history(period="1y", interval="1d")
    r = hist["Close"].pct_change().dropna()
    r.index = [d.date() for d in r.index]
    return r


print("=" * 74)
print("PASS 1: Real 1-year correlation -- held book vs candidate additions")
print("=" * 74)
frames = {s: daily_returns(s) for s in ALL}
df = pd.DataFrame(frames).dropna()
print(f"(shared trading days: {len(df)}, {df.index[0]} to {df.index[-1]})\n")
print(df.corr().round(2).to_string())

print("\nAnnualized vol (1y) and trailing 1y return:")
for s in ALL:
    hist = yf.Ticker(s).history(period="1y", interval="1d")
    tr = hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1
    print(f"  {s:<5} vol {df[s].std()*(252**.5):>6.1%}   return {tr:>+7.1%}   {CANDIDATES.get(s,'(held)')}")

# --- Does adding each candidate actually reduce portfolio variance? ---
print()
print("=" * 74)
print("PASS 2: Marginal effect of a 10% sleeve on the post-restructure book")
print("=" * 74)
print("Base book = 55% SPY / 28% QQQM / 17% GLD (the recommended invested sleeve).")
print("Test = fund the 10% sleeve pro-rata from that base, measure the change.\n")

base_w = {"SPY": .55, "QQQM": .28, "GLD": .17}
cov = df.cov() * 252


def pvol(weights):
    syms = list(weights)
    w = np.array([weights[s] for s in syms])
    c = cov.loc[syms, syms].to_numpy()
    return float(np.sqrt(w @ c @ w))


base_vol = pvol(base_w)
print(f"  Base portfolio volatility: {base_vol:.2%}\n")
print(f"  {'Add 10%':<7} {'new vol':>9} {'Δ vol':>8} {'corr to base':>13}")
base_series = sum(df[s] * w for s, w in base_w.items())
for cand in CANDIDATES:
    w = {s: v * 0.9 for s, v in base_w.items()}
    w[cand] = 0.10
    nv = pvol(w)
    corr_to_base = float(np.corrcoef(base_series, df[cand])[0, 1])
    print(f"  {cand:<7} {nv:>8.2%} {nv-base_vol:>+8.2%} {corr_to_base:>13.2f}")

print()
print("=" * 74)
print("PASS 3: Committee assessment of each candidate")
print("=" * 74)

live = dataclasses.replace(DEFAULT_CONFIG.live_data, enabled=True)
config = dataclasses.replace(DEFAULT_CONFIG, live_data=live)
llm = build_llm_client(config)
provider = build_market_data_provider(config)
macro_provider = build_macro_provider(config)
seasonal_provider = build_seasonal_history_provider(config)
forecaster = build_price_forecaster(config)

from trading_agent.agents.analysts import (
    FundamentalAnalyst, MacroAnalyst, SeasonalityAnalyst, SentimentAnalyst,
    TechnicalAnalyst, ForecastAnalyst,
)
analysts = {
    "technical": TechnicalAnalyst(llm),
    "fundamental": FundamentalAnalyst(llm),
    "sentiment": SentimentAnalyst(llm),
    "macro": MacroAnalyst(llm, macro_provider),
    "forecast": ForecastAnalyst(llm, forecaster),
    "seasonality": SeasonalityAnalyst(llm),
}
rm = ResearchManager(llm)
spy_mom = momentum(provider.get_snapshot(BENCHMARK_SYMBOL).closes, 10)
today = dt.date.today()

for sym, label in CANDIDATES.items():
    sec = "stock" if sym in ("MU", "NBIS") else "index_etf"
    try:
        snap = provider.get_snapshot(sym)
        seas = seasonal_provider.get_snapshot(sym) if seasonal_provider else None
        a = assess_symbol(UniverseEntry(sym, sec, "n/a"), snap, spy_mom, analysts, rm,
                          seasonal_snapshot=seas, as_of=today)
        vol_s = f"{a.volatility:.1%}" if a.volatility else "n/a"
        print(f"\n  {sym} -- {label}")
        print(f"     composite {a.composite_score:+.4f} | {a.debate.consensus_signal.value} "
              f"(conf {a.debate.consensus_confidence:.2f}) | 20-bar vol {vol_s}")
        for r in a.analyst_reports:
            if r.confidence > 0:
                print(f"       [{r.agent_name}] {r.signal.value} ({r.confidence:.2f}) -- {r.summary[:88]}")
    except Exception as exc:  # noqa: BLE001
        print(f"\n  {sym}: assessment failed ({exc})")
