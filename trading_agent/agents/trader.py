"""Trader agent: turns a research consensus into a concrete draft TradePlan.

This is only ever a *proposal*. It intentionally does not know about
account equity or hard risk limits — that separation of concerns means
the RiskManager (engine/risk_controls.py) is the single place final
sizing/leverage is decided, and it cannot be bypassed by the trader
proposing something larger.
"""
from __future__ import annotations

from trading_agent.agents.schemas import Action, ResearchDebateResult, Signal, TradePlan
from trading_agent.llm.client import LLMClient


class Trader:
    def __init__(self, llm: LLMClient, requested_tranches: int = 2) -> None:
        self._llm = llm
        self._requested_tranches = max(1, requested_tranches)

    def propose(
        self,
        symbol: str,
        current_price: float,
        research: ResearchDebateResult,
        requested_leverage: float = 1.0,
        recent_lessons: list[str] | None = None,
    ) -> TradePlan:
        """`recent_lessons` (from `engine.memory.ReflectionMemory.recent_lessons`,
        if wired in by the caller) is the one bounded form of "adaptation"
        this project implements: short deterministic notes about how this
        symbol's recent closed trades went, added as extra *narration*
        context only. It cannot and does not change the action, target,
        stop, or tranche math below — those stay a fixed function of
        `research.consensus_signal`/`consensus_confidence`, same as ever.
        Unsupervised self-modification of the actual decision rules is a
        deliberately different, much riskier thing this project does not do.
        """
        if research.consensus_signal == Signal.BULLISH:
            action = Action.BUY
            target_price = current_price * (1 + 0.03 + 0.05 * research.consensus_confidence)
            stop_loss_price = current_price * (1 - 0.02 - 0.02 * (1 - research.consensus_confidence))
        elif research.consensus_signal == Signal.BEARISH:
            action = Action.SELL
            target_price = current_price * (1 - 0.03 - 0.05 * research.consensus_confidence)
            stop_loss_price = current_price * (1 + 0.02 + 0.02 * (1 - research.consensus_confidence))
        else:
            action = Action.HOLD
            target_price = current_price
            stop_loss_price = current_price

        tranche_sizes = _even_tranches(self._requested_tranches) if action != Action.HOLD else [1.0]

        narration_input = research.rationale
        if recent_lessons:
            narration_input += "\nRecent closed trades on this symbol:\n" + "\n".join(
                f"- {lesson}" for lesson in recent_lessons
            )
        rationale = self._llm.narrate(
            system="You are a trader. In one sentence, state the plan and the key risk to watch. "
            "If recent trade history is given, you may reference it, but it does not change the plan.",
            user=narration_input,
        )
        return TradePlan(
            symbol=symbol,
            action=action,
            entry_price=current_price,
            target_price=target_price,
            stop_loss_price=stop_loss_price,
            leverage=requested_leverage,
            tranche_sizes=tranche_sizes,
            rationale=rationale,
        )


def _even_tranches(n: int) -> list[float]:
    return [1.0 / n] * n
