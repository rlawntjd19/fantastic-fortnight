from trading_agent.agents.analysts import FundamentalAnalyst
from trading_agent.data.providers import MarketSnapshot, SimulatedFeed
from trading_agent.llm.client import DummyLLMClient


def _snapshot_with(fundamentals: dict) -> MarketSnapshot:
    base = SimulatedFeed().get_snapshot("AAPL")
    return MarketSnapshot(symbol="AAPL", bars=base.bars, fundamentals=fundamentals)


def test_missing_fundamentals_is_neutral():
    analyst = FundamentalAnalyst(DummyLLMClient())
    report = analyst.analyze(_snapshot_with({}))
    assert report.signal.value == "neutral"
    assert report.confidence == 0.0


def test_cheap_pe_and_strong_growth_is_bullish():
    analyst = FundamentalAnalyst(DummyLLMClient())
    report = analyst.analyze(_snapshot_with({"pe_ratio": 10.0, "revenue_growth_yoy": 0.25}))
    assert report.signal.value == "bullish"


def test_expensive_pe_and_negative_growth_is_bearish():
    analyst = FundamentalAnalyst(DummyLLMClient())
    report = analyst.analyze(_snapshot_with({"pe_ratio": 45.0, "revenue_growth_yoy": -0.10}))
    assert report.signal.value == "bearish"


def test_negative_profit_margin_pulls_score_down():
    analyst = FundamentalAnalyst(DummyLLMClient())
    bullish_ish = analyst.analyze(_snapshot_with({"pe_ratio": 10.0, "revenue_growth_yoy": 0.25}))
    with_bad_margin = analyst.analyze(
        _snapshot_with({"pe_ratio": 10.0, "revenue_growth_yoy": 0.25, "profit_margin": -0.05})
    )
    assert with_bad_margin.confidence < bullish_ish.confidence or with_bad_margin.signal != bullish_ish.signal


def test_analyst_recommendations_shift_signal():
    analyst = FundamentalAnalyst(DummyLLMClient())
    bullish_recs = analyst.analyze(
        _snapshot_with({"analyst_recommendations": {"strong_buy": 10, "buy": 5, "hold": 1, "sell": 0, "strong_sell": 0}})
    )
    bearish_recs = analyst.analyze(
        _snapshot_with({"analyst_recommendations": {"strong_buy": 0, "buy": 0, "hold": 1, "sell": 5, "strong_sell": 10}})
    )
    assert bullish_recs.signal.value == "bullish"
    assert bearish_recs.signal.value == "bearish"


def test_high_debt_to_equity_pulls_score_down():
    analyst = FundamentalAnalyst(DummyLLMClient())
    report = analyst.analyze(_snapshot_with({"debt_to_equity": 300.0}))
    assert any("Debt/Equity" in p for p in report.key_points)
