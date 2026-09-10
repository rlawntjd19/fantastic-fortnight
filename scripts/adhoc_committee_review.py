"""One-off: run the real committee analyst pipeline (same code path as the
live daily cycle -- trading_agent.committee.daily_report.assess_symbol)
against the user's personal 5-asset mix (QQQM, SPYG, NBIS, CRWV, SMH),
plus a direct real-data holdings-overlap check for QQQM vs SPYG.

This does NOT touch the live S&P-500 committee state/report files --
it's a read-only assessment of an outside basket, using the exact same
analyst desks and scoring code the live pipeline uses, so the verdict is
the committee's real logic, not a fresh ad hoc opinion. Not a permanent
part of the pipeline; prints to the job log, then this script and its
workflow get deleted.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import sys

sys.path.insert(0, ".")

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

BASKET = [
    UniverseEntry("QQQM", "index_etf", "Large-Cap Growth"),
    UniverseEntry("SPYG", "index_etf", "Large-Cap Growth"),
    UniverseEntry("NBIS", "stock", "Technology"),
    UniverseEntry("CRWV", "stock", "Technology"),
    UniverseEntry("SMH", "index_etf", "Semiconductors"),
]


def main() -> None:
    live_data = dataclasses.replace(DEFAULT_CONFIG.live_data, enabled=True)
    config = dataclasses.replace(DEFAULT_CONFIG, live_data=live_data)

    llm = build_llm_client(config)
    provider = build_market_data_provider(config)
    macro_provider = build_macro_provider(config)
    seasonal_provider = build_seasonal_history_provider(config)
    forecaster = build_price_forecaster(config)

    from trading_agent.agents.analysts import (
        FundamentalAnalyst,
        MacroAnalyst,
        SeasonalityAnalyst,
        SentimentAnalyst,
        TechnicalAnalyst,
        ForecastAnalyst,
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

    for entry in BASKET:
        print("=" * 70)
        print(f"{entry.symbol}  ({entry.security_type})")
        print("=" * 70)
        try:
            snapshot = provider.get_snapshot(entry.symbol)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED to fetch snapshot: {exc}")
            continue

        seasonal_snapshot = None
        if seasonal_provider is not None:
            try:
                seasonal_snapshot = seasonal_provider.get_snapshot(entry.symbol)
            except Exception:  # noqa: BLE001
                pass

        try:
            assessment = assess_symbol(
                entry,
                snapshot,
                spy_momentum,
                analysts,
                research_manager,
                seasonal_snapshot=seasonal_snapshot,
                as_of=today,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED to assess: {exc}")
            continue

        print(f"  Last price: {snapshot.last_price}")
        print(f"  Relative strength vs SPY (10-bar): "
              f"{assessment.relative_strength_vs_spy:+.2%}" if assessment.relative_strength_vs_spy is not None else "  Relative strength vs SPY: n/a")
        print(f"  Realized volatility (20-bar, annualized): "
              f"{assessment.volatility:.2%}" if assessment.volatility is not None else "  Volatility: n/a")
        print(f"  Composite score: {assessment.composite_score:+.4f}  (-1 bearish .. +1 bullish)")
        print()
        print("  --- Analyst desks ---")
        for r in assessment.analyst_reports:
            print(f"  [{r.agent_name}] {r.signal.value} (conf {r.confidence:.2f}) -- {r.summary}")
            for kp in r.key_points:
                print(f"      - {kp}")
        print()
        print("  --- Research debate ---")
        print(f"  Consensus: {assessment.debate.consensus_signal.value} "
              f"(confidence {assessment.debate.consensus_confidence:.2f})")
        print(f"  Bull thesis: {assessment.debate.bull_thesis}")
        print(f"  Bear thesis: {assessment.debate.bear_thesis}")
        print(f"  Rationale: {assessment.debate.rationale}")
        print()

    # --- Real holdings-overlap check: QQQM vs SPYG ---
    print("=" * 70)
    print("QQQM vs SPYG -- real top-holdings / sector overlap")
    print("=" * 70)
    import yfinance as yf

    for symbol in ["QQQM", "SPYG"]:
        try:
            fd = yf.Ticker(symbol).funds_data
            print(f"\n{symbol} top holdings (real, from fund data):")
            top = fd.top_holdings
            if top is not None and not top.empty:
                print(top.to_string())
            else:
                print("  (no top-holdings data returned)")
            print(f"\n{symbol} sector weightings (real):")
            sectors = fd.sector_weightings
            if sectors:
                for sector, weight in sorted(sectors.items(), key=lambda kv: -kv[1]):
                    print(f"  {sector}: {weight:.1%}")
            else:
                print("  (no sector-weighting data returned)")
        except Exception as exc:  # noqa: BLE001
            print(f"  {symbol}: fund-data fetch failed ({exc})")


if __name__ == "__main__":
    main()
