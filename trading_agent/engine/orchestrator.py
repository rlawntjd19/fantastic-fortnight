"""Wires analysts -> researchers -> trader -> risk debate -> hard limits
into one pipeline that produces a `FinalDecision` a human must approve.

`run_cycle` never touches the PaperBroker. Only the caller (typically the
CLI, after showing the decision to a person) decides whether to call
`PaperBroker.execute(decision, human_approved=True)`.
"""
from __future__ import annotations

from dataclasses import dataclass

from trading_agent.agents.analysts import (
    ForecastAnalyst,
    FundamentalAnalyst,
    SentimentAnalyst,
    TechnicalAnalyst,
)
from trading_agent.agents.risk import AggressiveDebator, ConservativeDebator, NeutralDebator
from trading_agent.agents.schemas import AnalystReport, FinalDecision
from trading_agent.agents.trader import Trader
from trading_agent.agents.researchers import ResearchManager
from trading_agent.config import Config
from trading_agent.data.providers import MarketDataProvider
from trading_agent.engine.risk_controls import DailyCircuitBreaker, enforce_hard_limits
from trading_agent.forecast.base import PriceForecaster
from trading_agent.forecast.factory import build_price_forecaster
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
        forecaster: PriceForecaster | None = None,
    ) -> None:
        self._config = config
        self._data_provider = data_provider
        self._requested_leverage = requested_leverage

        self._technical = TechnicalAnalyst(llm)
        self._fundamental = FundamentalAnalyst(llm)
        self._sentiment = SentimentAnalyst(llm)
        self._forecast = ForecastAnalyst(
            llm, forecaster or build_price_forecaster(config), pred_len=config.kronos.pred_len
        )
        self._research_manager = ResearchManager(llm)
        self._trader = Trader(llm, requested_tranches=requested_tranches)
        self._aggressive = AggressiveDebator(llm)
        self._conservative = ConservativeDebator(llm)
        self._neutral = NeutralDebator(llm)

    @property
    def config(self) -> Config:
        return self._config

    def fetch_snapshot(self, symbol: str):
        """Exposed separately from `run_cycle` so a caller that needs the raw
        snapshot too (e.g. `cli.py watch`, to mark positions to market and
        check stop-losses before running the analysis) can fetch it once and
        reuse it via `run_cycle_with_snapshot`, instead of fetching twice."""
        return self._data_provider.get_snapshot(symbol)

    def run_cycle(
        self,
        symbol: str,
        account_equity: float,
        circuit_breaker: DailyCircuitBreaker | None = None,
    ) -> CycleArtifacts:
        snapshot = self.fetch_snapshot(symbol)
        return self.run_cycle_with_snapshot(snapshot, account_equity, circuit_breaker)

    def run_cycle_with_snapshot(
        self,
        snapshot,
        account_equity: float,
        circuit_breaker: DailyCircuitBreaker | None = None,
    ) -> CycleArtifacts:
        symbol = snapshot.symbol

        reports = [
            self._technical.analyze(snapshot),
            self._fundamental.analyze(snapshot),
            self._sentiment.analyze(snapshot),
            self._forecast.analyze(snapshot),
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
