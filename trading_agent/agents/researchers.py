"""Bull/Bear researcher debate and the manager that resolves it.

Mirrors the "structured debate" idea from multi-agent trading-agent
research: rather than one analyst having the final word, a bull case and
a bear case are both built from the same analyst reports, and a manager
agent produces a single reconciled consensus with a visible rationale.
"""
from __future__ import annotations

from trading_agent.agents.schemas import AnalystReport, ResearchDebateResult, Signal
from trading_agent.llm.client import LLMClient


class BullResearcher:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def build_case(self, reports: list[AnalystReport]) -> str:
        supporting = [r for r in reports if r.signal != Signal.BEARISH]
        points = [p for r in supporting for p in r.key_points]
        return self._llm.narrate(
            system="You are a bull researcher. Make the strongest reasonable case "
            "FOR going long, using only the evidence given. Flag it if the evidence is weak.",
            user="\n".join(points) or "No supporting evidence found.",
        )


class BearResearcher:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def build_case(self, reports: list[AnalystReport]) -> str:
        opposing = [r for r in reports if r.signal != Signal.BULLISH]
        points = [p for r in opposing for p in r.key_points]
        return self._llm.narrate(
            system="You are a bear researcher. Make the strongest reasonable case "
            "AGAINST going long, using only the evidence given. Flag it if the evidence is weak.",
            user="\n".join(points) or "No opposing evidence found.",
        )


class ResearchManager:
    """Reconciles analyst reports plus the bull/bear cases into one consensus.

    The consensus signal/confidence are computed deterministically from the
    weighted analyst votes; the bull/bear narratives are kept for human
    context but do not themselves move the numbers.
    """

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self._bull = BullResearcher(llm)
        self._bear = BearResearcher(llm)

    def debate(self, reports: list[AnalystReport]) -> ResearchDebateResult:
        bull_thesis = self._bull.build_case(reports)
        bear_thesis = self._bear.build_case(reports)

        weighted_score = 0.0
        total_weight = 0.0
        for r in reports:
            direction = {Signal.BULLISH: 1, Signal.BEARISH: -1, Signal.NEUTRAL: 0}[r.signal]
            weighted_score += direction * r.confidence
            total_weight += r.confidence
        avg = weighted_score / total_weight if total_weight else 0.0

        if avg > 0.15:
            consensus = Signal.BULLISH
        elif avg < -0.15:
            consensus = Signal.BEARISH
        else:
            consensus = Signal.NEUTRAL

        rationale = self._llm.narrate(
            system="You are a research manager reconciling a bull and a bear case into "
            "one balanced summary in 2 sentences.",
            user=f"Bull case: {bull_thesis}\nBear case: {bear_thesis}",
        )
        return ResearchDebateResult(
            bull_thesis=bull_thesis,
            bear_thesis=bear_thesis,
            consensus_signal=consensus,
            consensus_confidence=min(1.0, abs(avg)),
            rationale=rationale,
        )
