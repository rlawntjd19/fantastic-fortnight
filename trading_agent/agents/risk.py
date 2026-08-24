"""Risk-debate agents.

These three produce *narrative only* — an aggressive voice, a conservative
voice, and a neutral moderator summary — for the human reviewing the
decision. None of them can change the actual numbers; that authority sits
solely with `engine.risk_controls.enforce_hard_limits`, which runs after
this debate regardless of what these agents argue.
"""
from __future__ import annotations

from trading_agent.agents.schemas import TradePlan
from trading_agent.llm.client import LLMClient


class AggressiveDebator:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def argue(self, plan: TradePlan) -> str:
        return self._llm.narrate(
            system="You argue for taking the full proposed size. One sentence.",
            user=f"{plan.action.value} {plan.symbol} at {plan.entry_price:.2f}, "
            f"leverage {plan.leverage}x, target {plan.target_price:.2f}.",
        )


class ConservativeDebator:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def argue(self, plan: TradePlan) -> str:
        return self._llm.narrate(
            system="You argue for cutting size and leverage given downside risk. One sentence.",
            user=f"{plan.action.value} {plan.symbol} at {plan.entry_price:.2f}, "
            f"stop {plan.stop_loss_price:.2f}, leverage {plan.leverage}x.",
        )


class NeutralDebator:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def moderate(self, plan: TradePlan, aggressive_take: str, conservative_take: str) -> str:
        return self._llm.narrate(
            system="Summarize both sides into one balanced sentence for a human decision-maker.",
            user=f"Aggressive: {aggressive_take}\nConservative: {conservative_take}",
        )
