"""Screening desk: runs the existing analyst pool (Technical/Fundamental/
Sentiment/Macro/Forecast), three investor-persona analysts, and the
bull/bear research debate against every symbol in the universe. The core
five mirror `engine/orchestrator.TradingCycle`'s single-symbol pipeline —
this just fans that same, already-tested analyst stage out across many
symbols instead of one. The personas (`agents/persona_analysts.py`) are
new here: named investor philosophies (value/growth/contrarian) whose
*scoring rule* differs, not just their narration, so they can genuinely
disagree with the core analysts and with each other — see that module's
docstring for why the LLM still never sets their numbers either.

The LLM never sets these numbers either: `composite_score` is the same
signal/confidence-weighted vote `agents.researchers.ResearchManager`
already computes internally, recomputed here (not exposed by
`ResearchDebateResult`, which only keeps the unsigned confidence) so the
selection stage has a signed ranking key.
"""
from __future__ import annotations

from trading_agent.agents.analysts import (
    ForecastAnalyst,
    FundamentalAnalyst,
    MacroAnalyst,
    SentimentAnalyst,
    TechnicalAnalyst,
)
from trading_agent.agents.persona_analysts import (
    ContrarianInvestorAnalyst,
    GrowthInvestorAnalyst,
    ValueInvestorAnalyst,
)
from trading_agent.agents.researchers import ResearchManager
from trading_agent.agents.schemas import AnalystReport, Signal
from trading_agent.config import Config
from trading_agent.data.factory import build_macro_provider
from trading_agent.data.macro import MacroDataProvider
from trading_agent.data.providers import MarketDataProvider
from trading_agent.forecast.base import PriceForecaster
from trading_agent.forecast.factory import build_price_forecaster
from trading_agent.llm.client import LLMClient
from trading_agent.portfolio.schemas import CandidateScore
from trading_agent.portfolio.universe import UniverseEntry

_DIRECTION = {Signal.BULLISH: 1, Signal.BEARISH: -1, Signal.NEUTRAL: 0}


def composite_score(reports: list[AnalystReport]) -> float:
    """Confidence-weighted average direction across analysts, in [-1, 1].
    Identical formula to `ResearchManager.debate`'s internal `avg` — kept
    here as its own function since that value isn't part of
    `ResearchDebateResult`'s public fields."""
    weighted = 0.0
    total = 0.0
    for r in reports:
        weighted += _DIRECTION[r.signal] * r.confidence
        total += r.confidence
    return weighted / total if total else 0.0


class ScreeningDesk:
    def __init__(
        self,
        config: Config,
        llm: LLMClient,
        data_provider: MarketDataProvider,
        macro_provider: MacroDataProvider | None = None,
        forecaster: PriceForecaster | None = None,
    ) -> None:
        self._data_provider = data_provider
        macro_provider = macro_provider or build_macro_provider(config)
        self._technical = TechnicalAnalyst(llm)
        self._fundamental = FundamentalAnalyst(llm)
        self._sentiment = SentimentAnalyst(llm)
        self._macro = MacroAnalyst(llm, macro_provider)
        self._forecast = ForecastAnalyst(
            llm, forecaster or build_price_forecaster(config), pred_len=config.kronos.pred_len
        )
        self._value_investor = ValueInvestorAnalyst(llm)
        self._growth_investor = GrowthInvestorAnalyst(llm)
        # Market-wide, so read once up front rather than re-fetched per symbol.
        vix_level = macro_provider.get_macro_snapshot().vix_level
        self._contrarian_investor = ContrarianInvestorAnalyst(llm, vix_level=vix_level)
        self._research_manager = ResearchManager(llm)

    def screen_one(self, entry: UniverseEntry) -> CandidateScore:
        snapshot = self._data_provider.get_snapshot(entry.symbol)
        reports = [
            analyst.analyze(snapshot)
            for analyst in (
                self._technical,
                self._fundamental,
                self._sentiment,
                self._macro,
                self._forecast,
                self._value_investor,
                self._growth_investor,
                self._contrarian_investor,
            )
        ]
        debate = self._research_manager.debate(reports)
        return CandidateScore(
            symbol=entry.symbol,
            sector=entry.sector,
            reports=reports,
            debate=debate,
            composite_score=composite_score(reports),
            last_price=snapshot.last_price,
            closes=snapshot.closes,
        )

    def screen(self, universe: list[UniverseEntry]) -> list[CandidateScore]:
        return [self.screen_one(entry) for entry in universe]
