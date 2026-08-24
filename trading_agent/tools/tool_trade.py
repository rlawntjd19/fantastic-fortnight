"""tool_trade.py — thin, code-only wrappers around `PaperBroker`'s order
actions. See `trading_agent/tools/__init__.py`: nothing here is exposed
to an LLM as an autonomously-callable function. `Trader` (agents/trader.py)
never decides whether to call these — it only drafts a `TradePlan`;
whatever caller has a `PaperBroker` decides whether/when to book it.
"""
from __future__ import annotations

from trading_agent.agents.schemas import FinalDecision
from trading_agent.engine.paper_broker import PaperBroker


def execute_decision(broker: PaperBroker, decision: FinalDecision) -> None:
    """Books `decision` into `broker` if it cleared risk controls.
    See `PaperBroker.execute` for the full contract."""
    broker.execute(decision)


def check_stop_losses(broker: PaperBroker, current_prices: dict[str, float]) -> list[str]:
    """Closes any open position whose stop has been breached at these
    prices. See `PaperBroker.check_stop_losses`."""
    return broker.check_stop_losses(current_prices)
