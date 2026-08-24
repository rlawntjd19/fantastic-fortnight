"""Analyst agents: turn raw market data into an AnalystReport each.

Each analyst computes its signal with a deterministic rule first (so the
system works and is testable with no LLM at all), then optionally asks
the LLM client for a short human-readable narrative on top. The LLM never
decides the signal/confidence numbers themselves.
"""
from __future__ import annotations

from trading_agent.agents.schemas import AnalystReport, Signal
from trading_agent.data.indicators import momentum, rsi, sma
from trading_agent.data.macro import MacroDataProvider
from trading_agent.data.providers import MarketSnapshot
from trading_agent.forecast.base import PriceForecaster
from trading_agent.llm.client import LLMClient


class TechnicalAnalyst:
    name = "technical_analyst"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def analyze(self, snapshot: MarketSnapshot) -> AnalystReport:
        closes = snapshot.closes
        fast = sma(closes, 10)
        slow = sma(closes, 30)
        rsi_value = rsi(closes, 14)
        mom = momentum(closes, 10)

        points: list[str] = []
        score = 0.0
        if fast is not None and slow is not None:
            if fast > slow:
                score += 1
                points.append(f"SMA10 ({fast:.2f}) above SMA30 ({slow:.2f}): uptrend")
            else:
                score -= 1
                points.append(f"SMA10 ({fast:.2f}) below SMA30 ({slow:.2f}): downtrend")
        if rsi_value is not None:
            if rsi_value >= 70:
                score -= 0.5
                points.append(f"RSI {rsi_value:.1f}: overbought, pullback risk")
            elif rsi_value <= 30:
                score += 0.5
                points.append(f"RSI {rsi_value:.1f}: oversold, bounce potential")
            else:
                points.append(f"RSI {rsi_value:.1f}: neutral")
        if mom is not None:
            score += 0.5 if mom > 0 else -0.5
            points.append(f"10-bar momentum {mom * 100:.1f}%")

        signal, confidence = _score_to_signal(score, max_abs_score=2.0)
        summary = self._llm.narrate(
            system="You are a terse technical analyst. One sentence, no advice.",
            user="\n".join(points) or "No indicator data available.",
        )
        return AnalystReport(self.name, signal, confidence, summary, points)


class FundamentalAnalyst:
    """Company-level fundamentals: valuation, growth, profitability, leverage,
    and (when the data provider exposes it) sell-side analyst consensus.

    Every field is read defensively (`snapshot.fundamentals.get(...)`) and
    simply skipped if absent — `YFinanceFeed` already fetches each of these
    independently so one missing field never blocks the rest; the same
    goes here for scoring.
    """

    name = "fundamental_analyst"
    # Sum of every term's max |contribution| below — keeps the same
    # normalization approach TechnicalAnalyst uses (max_abs_score = the
    # largest possible score magnitude, not a special threshold).
    _MAX_ABS_SCORE = 5.0

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def analyze(self, snapshot: MarketSnapshot) -> AnalystReport:
        f = snapshot.fundamentals
        points: list[str] = []
        score = 0.0

        pe = f.get("pe_ratio")
        if pe is not None:
            if pe < 15:
                score += 1
                points.append(f"P/E {pe:.1f}: reasonably valued or cheap")
            elif pe > 30:
                score -= 1
                points.append(f"P/E {pe:.1f}: richly valued")
            else:
                points.append(f"P/E {pe:.1f}: fair value")

        growth = f.get("revenue_growth_yoy")
        if growth is not None:
            score += 1 if growth > 0.10 else (-0.5 if growth < 0 else 0)
            points.append(f"YoY revenue growth {growth * 100:.1f}%")

        forward_pe = f.get("forward_pe")
        if forward_pe is not None and pe is not None and pe > 0:
            if forward_pe < pe:
                score += 0.5
                points.append(f"Forward P/E {forward_pe:.1f} < trailing {pe:.1f}: earnings expected to grow")
            elif forward_pe > pe:
                score -= 0.5
                points.append(f"Forward P/E {forward_pe:.1f} > trailing {pe:.1f}: earnings expected to shrink")

        roe = f.get("return_on_equity")
        if roe is not None:
            score += 0.5 if roe > 0.15 else (-0.5 if roe < 0.05 else 0)
            points.append(f"Return on equity {roe * 100:.1f}%")

        margin = f.get("profit_margin")
        if margin is not None:
            score += 0.5 if margin > 0.15 else (-1 if margin < 0 else 0)
            points.append(f"Profit margin {margin * 100:.1f}%")

        debt_to_equity = f.get("debt_to_equity")
        if debt_to_equity is not None:
            # yfinance reports this as a percentage (e.g. 150 == 150%), not a ratio.
            score += -0.5 if debt_to_equity > 200 else (0.5 if debt_to_equity < 50 else 0)
            points.append(f"Debt/Equity {debt_to_equity:.0f}%")

        recs = f.get("analyst_recommendations")
        if recs:
            bullish_count = recs.get("strong_buy", 0) + recs.get("buy", 0)
            bearish_count = recs.get("sell", 0) + recs.get("strong_sell", 0)
            if bullish_count > bearish_count:
                score += 0.5
            elif bearish_count > bullish_count:
                score -= 0.5
            points.append(
                f"Analyst consensus: {bullish_count} buy-side vs {bearish_count} sell-side "
                f"({recs.get('hold', 0)} hold)"
            )

        signal, confidence = _score_to_signal(score, max_abs_score=self._MAX_ABS_SCORE)
        summary = self._llm.narrate(
            system="You are a terse fundamental analyst. One sentence, no advice.",
            user="\n".join(points) or "No fundamental data available.",
        )
        return AnalystReport(self.name, signal, confidence, summary, points)


class SentimentAnalyst:
    name = "sentiment_analyst"

    _POSITIVE_WORDS = ("buying", "return", "rally", "beat", "upgrade", "resistance broken")
    _NEGATIVE_WORDS = ("selloff", "downgrade", "miss", "resistance", "warning", "lawsuit")

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def analyze(self, snapshot: MarketSnapshot) -> AnalystReport:
        headlines = snapshot.news_headlines
        score = 0.0
        points: list[str] = []
        for headline in headlines:
            lowered = headline.lower()
            pos = any(w in lowered for w in self._POSITIVE_WORDS)
            neg = any(w in lowered for w in self._NEGATIVE_WORDS)
            if pos and not neg:
                score += 1
                points.append(f"+ {headline}")
            elif neg and not pos:
                score -= 1
                points.append(f"- {headline}")
            else:
                points.append(f"= {headline}")

        signal, confidence = _score_to_signal(score, max_abs_score=max(1.0, len(headlines)))
        summary = self._llm.narrate(
            system="You are a terse news-sentiment analyst. One sentence, no advice.",
            user="\n".join(headlines) or "No headlines available.",
        )
        return AnalystReport(self.name, signal, confidence, summary, points)


class MacroAnalyst:
    """Reads market-wide macro context (rate regime, VIX, dollar strength)
    rather than anything company-specific — the same separation a trading
    desk draws between a stock analyst and a macro/rates desk. See
    `data/macro.py` for the provider (`StaticMacroProvider` offline,
    `YFinanceMacroProvider` when live data is enabled).
    """

    name = "macro_analyst"
    _MAX_ABS_SCORE = 2.0

    def __init__(self, llm: LLMClient, macro_provider: MacroDataProvider) -> None:
        self._llm = llm
        self._macro_provider = macro_provider

    def analyze(self, snapshot: MarketSnapshot) -> AnalystReport:
        macro = self._macro_provider.get_macro_snapshot()
        points: list[str] = []
        score = 0.0

        if macro.ten_year_yield_change_pct is not None:
            if macro.ten_year_yield_change_pct > 0.05:
                score -= 0.5
                points.append(
                    f"10Y yield up {macro.ten_year_yield_change_pct * 100:.1f}%: tightening headwind for risk assets"
                )
            elif macro.ten_year_yield_change_pct < -0.05:
                score += 0.5
                points.append(
                    f"10Y yield down {macro.ten_year_yield_change_pct * 100:.1f}%: easier conditions for risk assets"
                )

        if macro.vix_level is not None:
            if macro.vix_level > 25:
                score -= 1
                points.append(f"VIX {macro.vix_level:.1f}: elevated fear, risk-off regime")
            elif macro.vix_level < 15:
                score += 0.5
                points.append(f"VIX {macro.vix_level:.1f}: calm, risk-on regime")
            else:
                points.append(f"VIX {macro.vix_level:.1f}: normal range")

        if macro.dollar_index_change_pct is not None:
            if macro.dollar_index_change_pct > 0.02:
                score -= 0.5
                points.append(
                    f"Dollar index up {macro.dollar_index_change_pct * 100:.1f}%: headwind for risk assets"
                )
            elif macro.dollar_index_change_pct < -0.02:
                score += 0.5
                points.append(
                    f"Dollar index down {macro.dollar_index_change_pct * 100:.1f}%: tailwind for risk assets"
                )

        signal, confidence = _score_to_signal(score, max_abs_score=self._MAX_ABS_SCORE)
        summary = self._llm.narrate(
            system="You are a terse macro strategist. One sentence, no advice.",
            user="\n".join(points) or "No macro data available.",
        )
        return AnalystReport(self.name, signal, confidence, summary, points)


class ForecastAnalyst:
    """Wraps a `PriceForecaster` (Kronos, or the offline heuristic fallback).

    Like the other analysts, the forecaster only supplies numbers
    (predicted return, sample dispersion); this class turns those into a
    signal/confidence using a fixed, inspectable rule, and the forecaster
    itself never sees or influences position sizing or leverage.
    """

    name = "forecast_analyst"

    # A pred_len-horizon move of this size or larger maps to full-confidence
    # bullish/bearish; smaller moves scale down linearly. Kept conservative
    # since Kronos's own docs are explicit that it forecasts prices, not
    # profitable trades.
    _FULL_CONFIDENCE_MOVE = 0.05
    # Below this fraction of the full-confidence move, treat the forecast
    # as noise rather than a directional call (a return-fraction score
    # needs its own threshold — it isn't comparable to the raw point
    # totals `_score_to_signal`'s fixed 0.25 cutoff was built for).
    _NEUTRAL_BAND = 0.20 * _FULL_CONFIDENCE_MOVE

    def __init__(self, llm: LLMClient, forecaster: PriceForecaster, pred_len: int = 10) -> None:
        self._llm = llm
        self._forecaster = forecaster
        self._pred_len = pred_len

    def analyze(self, snapshot: MarketSnapshot) -> AnalystReport:
        result = self._forecaster.forecast(snapshot.closes, self._pred_len)

        raw_confidence = min(1.0, abs(result.expected_return) / self._FULL_CONFIDENCE_MOVE)
        if result.expected_return > self._NEUTRAL_BAND:
            signal = Signal.BULLISH
        elif result.expected_return < -self._NEUTRAL_BAND:
            signal = Signal.BEARISH
        else:
            signal = Signal.NEUTRAL
        # Wide sample dispersion (the model's own samples disagree on
        # direction/magnitude) should pull confidence toward zero rather
        # than letting a noisy point estimate look decisive.
        uncertainty_penalty = 1.0 / (1.0 + result.dispersion / self._FULL_CONFIDENCE_MOVE)
        confidence = raw_confidence * uncertainty_penalty

        points = [
            f"{result.source} {self._pred_len}-bar forecast: "
            f"{result.expected_return * 100:+.1f}% expected move "
            f"(dispersion {result.dispersion * 100:.1f}%, n={result.sample_count})"
        ]
        summary = self._llm.narrate(
            system="You are a terse quant summarizing a price forecast. One sentence, no advice.",
            user=points[0],
        )
        return AnalystReport(self.name, signal, confidence, summary, points)


def _score_to_signal(score: float, max_abs_score: float) -> tuple[Signal, float]:
    confidence = min(1.0, abs(score) / max_abs_score) if max_abs_score else 0.0
    if score > 0.25:
        return Signal.BULLISH, confidence
    if score < -0.25:
        return Signal.BEARISH, confidence
    return Signal.NEUTRAL, confidence
