"""Wires analysts -> researchers -> trader -> risk debate -> hard limits
into one pipeline that produces a `FinalDecision` a human must approve.

`run_cycle` never touches the PaperBroker. Only the caller (typically the
CLI, after showing the decision to a person) decides whether to call
`PaperBroker.execute(decision, human_approved=True)`.
"""
from __future__ import annotations

from dataclasses import dataclass

from trading_agent.agents.analysts import FundamentalAnalyst, SentimentAnalyst, TechnicalAnalyst
from trading_agent.agents.risk import AggressiveDebator, ConservativeDebator, NeutralDebator
from trading_agent.agents.schemas import AnalystReport, FinalDecision
from trading_agent.agents.trader import Trader
from trading_agent.agents.researchers import ResearchManager
from trading_agent.config import Config
from trading_agent.data.providers import MarketDataProvider
from trading_agent.engine.risk_controls import DailyCircuitBreaker, enforce_hard_limits
from trading_agent.llm.client import LLMClient


@dataclass
class CycleArtifacts:
    """Everything the pipeline produced, kept around for display/audit —
    not just the final numbers."""

    analyst_reports: list[AnalystReport]
    aggressive_take: str
    conservative_take: str
    risk_moderator_summary: str
    decision: FinalDecision


class TradingCycle:
    def __init__(
        self,
        config: Config,
        llm: LLMClient,
        data_provider: MarketDataProvider,
        requested_leverage: float = 1.0,
        requested_tranches: int = 2,
    ) -> None:
        self._config = config
        self._data_provider = data_provider
        self._requested_leverage = requested_leverage

        self._technical = TechnicalAnalyst(llm)
        self._fundamental = FundamentalAnalyst(llm)
        self._sentiment = SentimentAnalyst(llm)
        self._research_manager = ResearchManager(llm)
        self._trader = Trader(llm, requested_tranches=requested_tranches)
        self._aggressive = AggressiveDebator(llm)
        self._conservative = ConservativeDebator(llm)
        self._neutral = NeutralDebator(llm)

    def run_cycle(
        self,
        symbol: str,
        account_equity: float,
        circuit_breaker: DailyCircuitBreaker | None = None,
    ) -> CycleArtifacts:
        snapshot = self._data_provider.get_snapshot(symbol)

        reports = [
            self._technical.analyze(snapshot),
            self._fundamental.analyze(snapshot),
            self._sentiment.analyze(snapshot),
        ]

        research = self._research_manager.debate(reports)

        plan = self._trader.propose(
            symbol=symbol,
            current_price=snapshot.last_price,
            research=research,
            requested_leverage=self._requested_leverage,
        )

        aggressive_take = self._aggressive.argue(plan)
        conservative_take = self._conservative.argue(plan)
        moderator_summary = self._neutral.moderate(plan, aggressive_take, conservative_take)

        risk_verdict = enforce_hard_limits(
            plan, self._config.risk, account_equity, circuit_breaker
        )

        decision = FinalDecision(
            trade_plan=plan,
            risk_verdict=risk_verdict,
            requires_human_approval=True,
            status="pending_approval" if risk_verdict.approved else "blocked",
            blocked_reason=None if risk_verdict.approved else risk_verdict.notes,
        )

        return CycleArtifacts(
            analyst_reports=reports,
            aggressive_take=aggressive_take,
            conservative_take=conservative_take,
            risk_moderator_summary=moderator_summary,
            decision=decision,
        )
