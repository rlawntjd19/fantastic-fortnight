"""Orchestrates one full daily committee run: mark the existing basket to
market, re-underwrite every held name, screen the universe for
replacements/new entries, and render the day's report.

Pipeline (mirrors `engine/orchestrator.TradingCycle`'s shape, one level up
— per-symbol analysts feed a per-symbol debate feed one portfolio-level
decision instead of one trade plan):

    SPY snapshot (benchmark) ──┐
                                ▼
    for each universe symbol → 5 analyst desks → ResearchManager debate
                                │  CandidateAssessment(composite_score, ...)
                                ▼
    held positions ── re-underwrite ── PortfolioManager exit rule
                                │
                                ▼
    PortfolioManager.select()  →  new entries fill open slots
                                │
                                ▼
    PortfolioState (persisted) + CommitteeReport (rendered)
"""
from __future__ import annotations

import datetime as dt

from trading_agent.agents.analysts import (
    FundamentalAnalyst,
    MacroAnalyst,
    SentimentAnalyst,
    TechnicalAnalyst,
    ForecastAnalyst,
)
from trading_agent.agents.researchers import ResearchManager
from trading_agent.agents.schemas import Signal
from trading_agent.committee.performance_tracker import build_scoreboard
from trading_agent.committee.portfolio_manager import PortfolioManager
from trading_agent.committee.schemas import CandidateAssessment, CommitteeReport, Position
from trading_agent.committee.universe import BENCHMARK_SYMBOL, UNIVERSE, screen_ineligible
from trading_agent.config import Config
from trading_agent.data.indicators import momentum
from trading_agent.data.macro import MacroDataProvider
from trading_agent.data.providers import MarketDataProvider
from trading_agent.forecast.base import PriceForecaster
from trading_agent.llm.client import LLMClient

# Analytics run daily starting the day this committee shipped, through this
# date inclusive, matching the mandate's "everyday until 9/7" window. Past
# it, `run_daily_cycle` still marks the existing basket to market (the OKR
# needs tracking to continue after picking stops) but no longer screens for
# new entries.
RESEARCH_WINDOW_END = dt.date(2026, 9, 7)

# A held position that has run this long without its thesis breaking is
# past the mandate's 2-3 month horizon and is flagged for close-out rather
# than held indefinitely.
MAX_HOLD_DAYS = 95

_REL_STRENGTH_FULL_SCALE = 0.10  # a 10pp spread vs SPY maps to a full +-1 score contribution


def _composite_score(reports, debate, relative_strength: float | None) -> float:
    direction = {Signal.BULLISH: 1, Signal.BEARISH: -1, Signal.NEUTRAL: 0}[debate.consensus_signal]
    non_neutral = [r for r in reports if r.signal != Signal.NEUTRAL]
    agreement = (
        sum(1 for r in non_neutral if r.signal == debate.consensus_signal) / len(non_neutral)
        if non_neutral
        else 0.0
    )
    desk_component = direction * debate.consensus_confidence * (0.5 + 0.5 * agreement)

    rel_component = 0.0
    if relative_strength is not None:
        rel_component = max(-1.0, min(1.0, relative_strength / _REL_STRENGTH_FULL_SCALE))

    return round(0.6 * desk_component + 0.4 * rel_component, 4)


def _assess_symbol(
    entry,
    snapshot,
    spy_momentum: float | None,
    analysts: dict,
    research_manager: ResearchManager,
) -> CandidateAssessment:
    reports = [
        analysts["technical"].analyze(snapshot),
        analysts["fundamental"].analyze(snapshot),
        analysts["sentiment"].analyze(snapshot),
        analysts["macro"].analyze(snapshot),
        analysts["forecast"].analyze(snapshot),
    ]
    debate = research_manager.debate(reports)

    symbol_momentum = momentum(snapshot.closes, 10)
    relative_strength = (
        symbol_momentum - spy_momentum if symbol_momentum is not None and spy_momentum is not None else None
    )

    return CandidateAssessment(
        symbol=entry.symbol,
        security_type=entry.security_type,
        sector=snapshot.fundamentals.get("sector") or entry.sector,
        market_cap=snapshot.fundamentals.get("market_cap"),
        last_price=snapshot.last_price,
        analyst_reports=reports,
        debate=debate,
        relative_strength_vs_spy=relative_strength,
        composite_score=_composite_score(reports, debate, relative_strength),
    )


def run_daily_cycle(
    config: Config,
    llm: LLMClient,
    provider: MarketDataProvider,
    macro_provider: MacroDataProvider,
    forecaster: PriceForecaster,
    state,
    run_date: dt.date | None = None,
) -> CommitteeReport:
    """Runs one day's cycle against `state` (mutated in place) and returns
    the report to render. Caller is responsible for persisting `state`
    afterwards (see `performance_tracker.save_state`)."""
    run_date = run_date or dt.date.today()
    window_open = run_date <= RESEARCH_WINDOW_END

    analysts = {
        "technical": TechnicalAnalyst(llm),
        "fundamental": FundamentalAnalyst(llm),
        "sentiment": SentimentAnalyst(llm),
        "macro": MacroAnalyst(llm, macro_provider),
        "forecast": ForecastAnalyst(llm, forecaster),
    }
    research_manager = ResearchManager(llm)
    cio = PortfolioManager(llm)

    screened_out: list[str] = []

    try:
        spy_snapshot = provider.get_snapshot(BENCHMARK_SYMBOL)
    except Exception as exc:  # noqa: BLE001 - a benchmark fetch failure must degrade, not crash the run
        screened_out.append(f"{BENCHMARK_SYMBOL}: benchmark fetch failed ({exc}); relative-strength scoring disabled this run")
        spy_snapshot = None
    spy_momentum = momentum(spy_snapshot.closes, 10) if spy_snapshot else None
    spy_price = spy_snapshot.last_price if spy_snapshot else None

    # --- mark existing basket to market and re-underwrite each holding ---
    exits: list[Position] = []
    held_symbols = {p.symbol for p in state.open_positions}
    current_prices: dict[str, float] = {}
    for position in list(state.open_positions):
        entry = next((e for e in UNIVERSE if e.symbol == position.symbol), None)
        try:
            snapshot = provider.get_snapshot(position.symbol)
        except Exception as exc:  # noqa: BLE001
            screened_out.append(f"{position.symbol}: could not mark to market ({exc}); kept at last known price")
            continue
        current_prices[position.symbol] = snapshot.last_price

        if entry is None:
            continue  # held name fell out of the static universe table; still tracked, just not re-underwritten
        assessment = _assess_symbol(entry, snapshot, spy_momentum, analysts, research_manager)

        days_held = (run_date - dt.date.fromisoformat(position.entry_date)).days
        thesis_broke = assessment.debate.consensus_signal == Signal.BEARISH
        horizon_reached = days_held >= MAX_HOLD_DAYS

        if thesis_broke or horizon_reached:
            position.status = "closed_thesis_broke" if thesis_broke else "closed_horizon"
            position.exit_date = run_date.isoformat()
            position.exit_price = snapshot.last_price
            position.benchmark_exit_price = spy_price
            position.exit_reason = (
                f"Committee consensus flipped bearish (confidence {assessment.debate.consensus_confidence:.2f}): "
                f"{assessment.debate.rationale}"
                if thesis_broke
                else f"Held {days_held} days, past the {MAX_HOLD_DAYS}-day (~3mo) horizon with no bearish break; closing on schedule."
            )
            state.positions.remove(position)
            state.closed.append(position)
            exits.append(position)
            held_symbols.discard(position.symbol)

    # --- screen the universe for new candidates (only while the window is open) ---
    candidates: list[CandidateAssessment] = []
    if window_open:
        for entry in UNIVERSE:
            if entry.symbol == BENCHMARK_SYMBOL and entry.security_type == "index_etf":
                pass  # SPY itself is still eligible as a defensive pick
            try:
                snapshot = spy_snapshot if entry.symbol == BENCHMARK_SYMBOL and spy_snapshot else provider.get_snapshot(entry.symbol)
            except Exception as exc:  # noqa: BLE001 - one bad ticker must not kill the whole run
                screened_out.append(f"{entry.symbol}: data fetch failed ({exc})")
                continue

            exclusion_reason = screen_ineligible(entry, snapshot.fundamentals, snapshot.last_price)
            if exclusion_reason:
                screened_out.append(exclusion_reason)
                continue

            current_prices.setdefault(entry.symbol, snapshot.last_price)
            candidates.append(_assess_symbol(entry, snapshot, spy_momentum, analysts, research_manager))

    slots_open = max(0, cio._max_picks - len(state.open_positions))
    new_picks, cio_rationale = cio.select(candidates, held_symbols, slots_open) if window_open else (
        [],
        "Research window closed (past the everyday-until-2026-09-07 mandate) — no new candidates were screened; "
        "the existing basket is still marked to market below.",
    )

    for pick in new_picks:
        position = Position(
            symbol=pick.symbol,
            security_type=pick.security_type,
            entry_date=run_date.isoformat(),
            entry_price=pick.entry_price,
            benchmark_entry_price=spy_price or pick.entry_price,
            thesis=pick.thesis,
        )
        state.positions.append(position)
        current_prices.setdefault(pick.symbol, pick.entry_price)

    scoreboard = build_scoreboard(state, current_prices, spy_price) if spy_price else []
    if scoreboard:
        avg_alpha = sum(r["alpha_pct"] for r in scoreboard) / len(scoreboard)
        okr_summary = (
            f"Basket-average alpha vs SPY across {len(scoreboard)} open position(s): {avg_alpha * 100:+.2f}pp "
            f"(OKR target: +5.00pp or better over each position's 2-3 month hold)."
        )
    else:
        okr_summary = "No open, price-verified positions yet — nothing to score against the OKR this run."

    return CommitteeReport(
        run_date=run_date.isoformat(),
        universe_size=len(UNIVERSE),
        screened_out=screened_out,
        candidates=candidates,
        exits=exits,
        entries=new_picks,
        open_positions=state.open_positions,
        scoreboard=scoreboard,
        cio_rationale=cio_rationale,
        okr_summary=okr_summary,
    )
