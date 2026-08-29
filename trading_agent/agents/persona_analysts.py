"""Investor-persona analysts: same "deterministic rule first, LLM narrates
after" contract as `analysts.py` — each persona just encodes a different,
well-known investing philosophy as its scoring rule, and the LLM narrates
in that persona's voice on top of the already-computed number.

Inspired by the named investor-persona agents (Buffett/Wood/Burry-style)
in open multi-agent trading-agent projects such as virattt/ai-hedge-fund —
but with one hard difference, consistent with the rest of this package:
the persona's LLM voice never decides the signal or confidence, only how
the already-computed rationale gets worded. Letting an LLM freely reason
"what would Warren Buffett do" and using *that* as the actual trading
signal would reintroduce exactly the untestable, unreproducible,
LLM-decides-the-number pattern the rest of this package's analysts are
built to avoid (see `analysts.py`'s module docstring).

Each persona reads the same `MarketSnapshot.fundamentals` / `.closes`
data the existing analysts already read, just weighted toward a
different philosophy — no new data provider is needed. Wired into
`portfolio/screening.py`'s multi-symbol pipeline only, not the
single-symbol `engine/orchestrator.TradingCycle` — the point here is
more research viewpoints feeding a stock-selection vote, not more
signals feeding a single leveraged trade plan.
"""
from __future__ import annotations

from trading_agent.agents.analysts import score_to_signal
from trading_agent.agents.schemas import AnalystReport
from trading_agent.data.indicators import momentum, rsi
from trading_agent.data.providers import MarketSnapshot
from trading_agent.llm.client import LLMClient


class ValueInvestorAnalyst:
    """Graham/Buffett-style: cheap, low-leverage, profitable. Growth doesn't
    excuse a rich price here, and a cheap price doesn't excuse a fragile
    balance sheet — both have to hold at once."""

    name = "value_investor_analyst"
    _MAX_ABS_SCORE = 3.0

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def analyze(self, snapshot: MarketSnapshot) -> AnalystReport:
        f = snapshot.fundamentals
        points: list[str] = []
        score = 0.0

        pe = f.get("pe_ratio")
        if pe is not None:
            if pe < 15:
                score += 1.5
                points.append(f"P/E {pe:.1f}: within a margin of safety")
            elif pe > 25:
                score -= 1.5
                points.append(f"P/E {pe:.1f}: too rich, regardless of the growth story")
            else:
                points.append(f"P/E {pe:.1f}: fair, not cheap")

        debt_to_equity = f.get("debt_to_equity")
        if debt_to_equity is not None:
            if debt_to_equity < 50:
                score += 1.0
                points.append(f"Debt/Equity {debt_to_equity:.0f}%: conservative balance sheet")
            elif debt_to_equity > 150:
                score -= 1.0
                points.append(f"Debt/Equity {debt_to_equity:.0f}%: too much leverage for comfort")

        margin = f.get("profit_margin")
        if margin is not None:
            if margin > 0.15:
                score += 0.5
                points.append(f"Profit margin {margin * 100:.1f}%: a real, durable business")
            elif margin < 0:
                score -= 1.0
                points.append(f"Profit margin {margin * 100:.1f}%: not even profitable")

        signal, confidence = score_to_signal(score, max_abs_score=self._MAX_ABS_SCORE)
        summary = self._llm.narrate(
            system="You are a patient value investor in the Graham/Buffett tradition: "
            "you only care about price versus intrinsic worth, quality of the business, "
            "and balance-sheet safety. One skeptical sentence, no advice.",
            user="\n".join(points) or "No fundamental data available.",
        )
        return AnalystReport(self.name, signal, confidence, summary, points)


class GrowthInvestorAnalyst:
    """Cathie-Wood-style disruptive-growth: revenue growth and price
    momentum matter far more than today's valuation multiple."""

    name = "growth_investor_analyst"
    _MAX_ABS_SCORE = 3.0

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def analyze(self, snapshot: MarketSnapshot) -> AnalystReport:
        f = snapshot.fundamentals
        points: list[str] = []
        score = 0.0

        growth = f.get("revenue_growth_yoy")
        if growth is not None:
            if growth > 0.20:
                score += 2.0
                points.append(f"YoY revenue growth {growth * 100:.1f}%: exactly the compounding this thesis needs")
            elif growth > 0.10:
                score += 1.0
                points.append(f"YoY revenue growth {growth * 100:.1f}%: solid, not spectacular")
            elif growth < 0:
                score -= 1.5
                points.append(f"YoY revenue growth {growth * 100:.1f}%: the growth story has stalled")

        mom = momentum(snapshot.closes, 20)
        if mom is not None:
            if mom > 0.05:
                score += 1.0
                points.append(f"20-bar momentum {mom * 100:.1f}%: the market is starting to price in the story")
            elif mom < -0.10:
                score -= 0.5
                points.append(f"20-bar momentum {mom * 100:.1f}%: momentum has broken down")

        signal, confidence = score_to_signal(score, max_abs_score=self._MAX_ABS_SCORE)
        summary = self._llm.narrate(
            system="You are an enthusiastic disruptive-growth investor in the Cathie "
            "Wood tradition: revenue growth and adoption curves matter far more than "
            "this quarter's P/E. One conviction-driven sentence, no advice.",
            user="\n".join(points) or "No growth data available.",
        )
        return AnalystReport(self.name, signal, confidence, summary, points)


class ContrarianInvestorAnalyst:
    """Burry-style contrarian: fear is a buying opportunity, crowd euphoria
    is a warning sign — the deliberate mirror image of how
    `TechnicalAnalyst`/`MacroAnalyst` read the same RSI/VIX numbers."""

    name = "contrarian_investor_analyst"
    _MAX_ABS_SCORE = 2.5

    def __init__(self, llm: LLMClient, vix_level: float | None = None) -> None:
        self._llm = llm
        self._vix_level = vix_level

    def analyze(self, snapshot: MarketSnapshot) -> AnalystReport:
        points: list[str] = []
        score = 0.0

        rsi_value = rsi(snapshot.closes, 14)
        if rsi_value is not None:
            if rsi_value <= 30:
                score += 1.5
                points.append(f"RSI {rsi_value:.1f}: everyone else is panicking, which is the point")
            elif rsi_value >= 75:
                score -= 1.5
                points.append(f"RSI {rsi_value:.1f}: crowd euphoria, exactly when to get cautious")

        mom = momentum(snapshot.closes, 10)
        if mom is not None:
            if mom < -0.05:
                score += 0.5
                points.append(f"10-bar momentum {mom * 100:.1f}%: a sell-off worth fading, not chasing")
            elif mom > 0.10:
                score -= 0.5
                points.append(f"10-bar momentum {mom * 100:.1f}%: a crowded trade, not a reason to join it")

        if self._vix_level is not None:
            if self._vix_level > 25:
                score += 1.0
                points.append(f"VIX {self._vix_level:.1f}: be greedy when others are fearful")
            elif self._vix_level < 13:
                score -= 0.5
                points.append(f"VIX {self._vix_level:.1f}: complacency this low rarely ends well")

        signal, confidence = score_to_signal(score, max_abs_score=self._MAX_ABS_SCORE)
        summary = self._llm.narrate(
            system="You are a skeptical contrarian investor in the Michael Burry "
            "tradition: you distrust whatever the crowd currently believes, and read "
            "fear/greed gauges backwards from the consensus. One terse sentence, no advice.",
            user="\n".join(points) or "No contrarian signal available.",
        )
        return AnalystReport(self.name, signal, confidence, summary, points)
