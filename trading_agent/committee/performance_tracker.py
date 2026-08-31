"""Persists the standing basket day-over-day and marks it to market against
SPY, so the +5%-vs-benchmark OKR is a running, checkable number instead of
a one-time guess.

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
    unit the +5% OKR is measured in."""
    position_return = current_price / entry_price - 1.0
    benchmark_return = benchmark_current / benchmark_entry - 1.0
    return position_return - benchmark_return


def build_scoreboard(state: PortfolioState, current_prices: dict[str, float], spy_current: float) -> list[dict]:
    rows = []
    for p in state.open_positions:
        current = current_prices.get(p.symbol)
        if current is None:
            continue
        rows.append(
            {
                "symbol": p.symbol,
                "entry_date": p.entry_date,
                "entry_price": p.entry_price,
                "current_price": current,
                "position_return_pct": current / p.entry_price - 1.0,
                "benchmark_return_pct": spy_current / p.benchmark_entry_price - 1.0,
                "alpha_pct": alpha_pct(p.entry_price, current, p.benchmark_entry_price, spy_current),
            }
        )
    return rows
