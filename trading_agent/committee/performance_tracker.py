"""Persists the standing basket day-over-day and marks it to market against
SPY, so the +10-15pp-vs-benchmark OKR is a running, checkable number
instead of a one-time guess.

Plain JSON on disk (mirrors `engine/journal.py`'s append-only-file
approach) — no database, easy to inspect or hand-edit, and diffable in git
so every day's committee decisions and their eventual outcome are part of
the repo's history.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict

from trading_agent.committee.schemas import PortfolioState, Position

DEFAULT_STATE_PATH = os.environ.get(
    "TRADING_AGENT_COMMITTEE_STATE_PATH", "research_team/state/portfolio.json"
)

# Paper capital the allocation table below is sized against — illustrative
# only, no real money anywhere in this codebase. Split across however many
# positions are actually open (2-5, per the mandate) weighted by conviction
# and inverse volatility (see build_scoreboard) rather than a fixed 1/5 or
# flat equal split: a basket that holds fewer, higher-conviction names
# deploys the same capital more heavily into each rather than sitting on
# uninvested cash for slots the committee chose not to fill, and within a
# basket, higher-conviction/lower-risk names get more than lower-conviction/
# higher-risk ones — the same "signal over risk" idea real risk-parity and
# vol-targeting sizing methods use, not an LLM guessing dollar amounts.
PORTFOLIO_CAPITAL_USD = float(os.environ.get("TRADING_AGENT_COMMITTEE_CAPITAL_USD", "100000"))

# Composite scores range roughly -1..1; a held position is never actually
# bearish (it would have been closed), but can be only mildly bullish or
# neutral — floor it so a soft-conviction name still gets a small stake
# instead of being sized to ~zero.
CONVICTION_FLOOR = 0.10

# Annualized-volatility floor/fallback, as a fraction (0.05 = 5%/yr). Floors
# guard against a near-zero realized-vol name (thin data, holiday-shortened
# window) swamping the whole allocation; the fallback covers a name build_
# scoreboard has no volatility estimate for at all (e.g. this run's price
# fetch failed for it) with a typical-large-cap-equity figure rather than
# guessing zero risk.
VOLATILITY_FLOOR_PCT = 0.05
DEFAULT_VOLATILITY_PCT = 0.25


def compute_weights(
    symbols: list[str],
    conviction_by_symbol: dict[str, float],
    volatility_by_symbol: dict[str, float],
) -> dict[str, float]:
    """weight_i = (conviction_i / volatility_i) / Σ (conviction_j / volatility_j)
    across `symbols`, normalized to sum to 1 — the one place this formula
    is defined, shared by `build_scoreboard` (live) and
    `committee.backtest` (historical), so the two can never quietly drift
    apart on how a basket is actually sized."""
    raw_weights: dict[str, float] = {}
    for symbol in symbols:
        conviction = max(conviction_by_symbol.get(symbol, CONVICTION_FLOOR), CONVICTION_FLOOR)
        vol = max(volatility_by_symbol.get(symbol, DEFAULT_VOLATILITY_PCT), VOLATILITY_FLOOR_PCT)
        raw_weights[symbol] = conviction / vol
    total_raw = sum(raw_weights.values()) or 1.0
    return {symbol: raw / total_raw for symbol, raw in raw_weights.items()}


def load_state(path: str = DEFAULT_STATE_PATH) -> PortfolioState:
    if not os.path.exists(path):
        return PortfolioState()
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return PortfolioState(
        positions=[Position(**p) for p in raw.get("positions", [])],
        closed=[Position(**p) for p in raw.get("closed", [])],
    )


def save_state(state: PortfolioState, path: str = DEFAULT_STATE_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "positions": [asdict(p) for p in state.positions],
        "closed": [asdict(p) for p in state.closed],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def alpha_pct(entry_price: float, current_price: float, benchmark_entry: float, benchmark_current: float) -> float:
    """Position return minus benchmark return over the same window — the
    unit the +10-15pp OKR is measured in."""
    position_return = current_price / entry_price - 1.0
    benchmark_return = benchmark_current / benchmark_entry - 1.0
    return position_return - benchmark_return


def build_scoreboard(
    state: PortfolioState,
    current_prices: dict[str, float],
    spy_current: float,
    conviction_by_symbol: dict[str, float] | None = None,
    volatility_by_symbol: dict[str, float] | None = None,
) -> list[dict]:
    """Marks every open position to market and sizes it against
    `PORTFOLIO_CAPITAL_USD`, weighted by `conviction / volatility` and
    normalized to sum to 1 across the open basket — a live snapshot ("if
    fully deployed today" at today's weights), not a buy-and-hold share
    count carried from each position's entry date. The alpha/return fields
    below are what track true since-entry performance, independent of this
    sizing. `conviction_by_symbol`/`volatility_by_symbol` are optional —
    omitted or missing entries fall back to the floor/default constants
    above, which collapses to a flat equal split when no signal is given
    for any held name (e.g. a caller that hasn't wired conviction data
    through yet), rather than crashing.
    """
    conviction_by_symbol = conviction_by_symbol or {}
    volatility_by_symbol = volatility_by_symbol or {}
    priced_open = [p for p in state.open_positions if current_prices.get(p.symbol) is not None]
    weights = compute_weights([p.symbol for p in priced_open], conviction_by_symbol, volatility_by_symbol)

    rows = []
    for p in priced_open:
        current = current_prices[p.symbol]
        weight = weights[p.symbol]
        capital_for_position = PORTFOLIO_CAPITAL_USD * weight
        shares = int(capital_for_position // current)
        allocated_value = shares * current
        rows.append(
            {
                "symbol": p.symbol,
                "entry_date": p.entry_date,
                "entry_price": p.entry_price,
                "current_price": current,
                "position_return_pct": current / p.entry_price - 1.0,
                "benchmark_return_pct": spy_current / p.benchmark_entry_price - 1.0,
                "alpha_pct": alpha_pct(p.entry_price, current, p.benchmark_entry_price, spy_current),
                "weight_pct": weight,
                "shares": shares,
                "allocated_value": allocated_value,
            }
        )
    return rows
