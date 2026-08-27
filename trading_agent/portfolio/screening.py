"""Screening desk: runs the existing analyst pool (Technical/Fundamental/
Sentiment/Macro/Forecast) plus the bull/bear research debate against every
symbol in the universe, exactly the way `engine/orchestrator.TradingCycle`
does for a single symbol — this just fans that same, already-tested
analyst stage out across many symbols instead of one.

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
        self._technical = TechnicalAnalyst(llm)
        self._fundamental = FundamentalAnalyst(llm)
        self._sentiment = SentimentAnalyst(llm)
        self._macro = MacroAnalyst(llm, macro_provider or build_macro_provider(config))
        self._forecast = ForecastAnalyst(
            llm, forecaster or build_price_forecaster(config), pred_len=config.kronos.pred_len
        )
        self._research_manager = ResearchManager(llm)

    def screen_one(self, entry: UniverseEntry) -> CandidateScore:
        snapshot = self._data_provider.get_snapshot(entry.symbol)
        reports = [
            analyst.analyze(snapshot)
            for analyst in (self._technical, self._fundamental, self._sentiment, self._macro, self._forecast)
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
