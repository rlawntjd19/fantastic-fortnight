"""Central configuration and hard risk ceilings.

These limits are enforced in `engine.risk_controls` in code, not by any
LLM agent. Analysts/researchers/trader agents may propose whatever they
want; the RiskManager can only ever narrow a proposal down to fit inside
these ceilings, never widen it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RiskLimits:
    # Hard ceiling on leverage the system will ever assemble into a trade
    # plan, regardless of what any agent argues for. The transcript this
    # design responds to used 20x; the default here is intentionally far
    # more conservative and must be raised explicitly and knowingly.
    max_leverage: float = 3.0

    # Max fraction of paper account equity allowed in a single symbol's
    # position notional (before leverage).
    max_position_pct_of_equity: float = 0.10

    # Every trade plan must carry a stop loss within this fraction of entry.
    max_stop_loss_pct: float = 0.05

    # Max number of tranches a scaled entry may be split into.
    max_tranches: int = 3

    # Daily circuit breaker: once realized+unrealized PnL for the day drops
    # this fraction below the day's starting equity, no new BUY signals are
    # allowed to reach the human approval stage (closing/reducing positions
    # is still allowed).
    daily_loss_circuit_breaker_pct: float = 0.05


@dataclass(frozen=True)
class Config:
    model_name: str = os.environ.get("TRADING_AGENT_MODEL", "claude-sonnet-5")
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    starting_paper_equity: float = float(
        os.environ.get("TRADING_AGENT_STARTING_EQUITY", "10_000_000")
    )
    risk: RiskLimits = field(default_factory=RiskLimits)
    memory_path: str = os.environ.get(
        "TRADING_AGENT_MEMORY_PATH", "trading_agent_memory.json"
    )


DEFAULT_CONFIG = Config()
