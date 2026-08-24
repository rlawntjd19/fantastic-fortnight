"""Wires analysts -> researchers -> trader -> risk debate -> hard limits
into one pipeline that produces a `FinalDecision`.

`run_cycle` never touches the PaperBroker itself — the caller (CLI,
web session, backtest loop) decides when to call
`PaperBroker.execute(decision)`, which books immediately if the decision
cleared risk controls. See `engine/paper_broker.py` for why that's fine
here (no real brokerage connection exists in this codebase).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from trading_agent.agents.analysts import (
    ForecastAnalyst,
    FundamentalAnalyst,
    MacroAnalyst,
    SentimentAnalyst,
    TechnicalAnalyst,
)
from trading_agent.agents.risk import AggressiveDebator, ConservativeDebator, NeutralDebator
from trading_agent.agents.schemas import AnalystReport, FinalDecision
from trading_agent.agents.trader import Trader
from trading_agent.agents.researchers import ResearchManager
from trading_agent.config import Config
from trading_agent.data.factory import build_macro_provider
from trading_agent.data.macro import MacroDataProvider
from trading_agent.data.providers import MarketDataProvider
from trading_agent.engine.memory import ReflectionMemory
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
        macro_provider: MacroDataProvider | None = None,
        reflection_memory: ReflectionMemory | None = None,
    ) -> None:
        self._config = config
        self._data_provider = data_provider
        self._requested_leverage = requested_leverage
        self._reflection_memory = reflection_memory or ReflectionMemory(config.memory_path)

        self._technical = TechnicalAnalyst(llm)
        self._fundamental = FundamentalAnalyst(llm)
        self._sentiment = SentimentAnalyst(llm)
        self._macro = MacroAnalyst(llm, macro_provider or build_macro_provider(config))
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

    @property
    def reflection_memory(self) -> ReflectionMemory:
        return self._reflection_memory

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
        on_stage: Callable[[str, dict], None] | None = None,
    ) -> CycleArtifacts:
        snapshot = self.fetch_snapshot(symbol)
        return self.run_cycle_with_snapshot(snapshot, account_equity, circuit_breaker, on_stage)

    def run_cycle_with_snapshot(
        self,
        snapshot,
        account_equity: float,
        circuit_breaker: DailyCircuitBreaker | None = None,
        on_stage: Callable[[str, dict], None] | None = None,
    ) -> CycleArtifacts:
        """`on_stage(name, payload)` is an optional, purely observational hook
        fired after each pipeline stage completes — e.g. by the web UI
        (`trading_agent/webapp/`) to stream real progress instead of faking
        it after the fact. It cannot affect the outcome: it's called with
        already-computed values, after the fact, and its return value is
        ignored. Callers that don't pass it (every existing caller) see no
        change in behavior at all.
        """
        notify = on_stage or (lambda name, payload: None)
        symbol = snapshot.symbol

        reports = []
        for analyst in (self._technical, self._fundamental, self._sentiment, self._macro, self._forecast):
            report = analyst.analyze(snapshot)
            reports.append(report)
            notify("analyst_report", {"report": report})

        research = self._research_manager.debate(reports)
        notify("research_debate", {"research": research})

        plan = self._trader.propose(
            symbol=symbol,
            current_price=snapshot.last_price,
            research=research,
            requested_leverage=self._requested_leverage,
            recent_lessons=self._reflection_memory.recent_lessons(symbol),
        )
        notify("trade_plan_drafted", {"plan": plan})

        aggressive_take = self._aggressive.argue(plan)
        notify("risk_debate_aggressive", {"text": aggressive_take})
        conservative_take = self._conservative.argue(plan)
        notify("risk_debate_conservative", {"text": conservative_take})
        moderator_summary = self._neutral.moderate(plan, aggressive_take, conservative_take)
        notify("risk_debate_moderator", {"text": moderator_summary})

        risk_verdict = enforce_hard_limits(
            plan, self._config.risk, account_equity, circuit_breaker
        )
        notify("risk_verdict", {"verdict": risk_verdict})

        decision = FinalDecision(
            trade_plan=plan,
            risk_verdict=risk_verdict,
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
