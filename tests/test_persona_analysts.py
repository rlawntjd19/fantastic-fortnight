from trading_agent.agents.persona_analysts import (
    ContrarianInvestorAnalyst,
    GrowthInvestorAnalyst,
    ValueInvestorAnalyst,
)
from trading_agent.agents.schemas import Signal
from trading_agent.data.providers import Bar, MarketSnapshot
from trading_agent.llm.client import DummyLLMClient


def _snapshot(closes, fundamentals=None):
    bars = [Bar(i, c, c, c, c, 1000.0) for i, c in enumerate(closes)]
    return MarketSnapshot(symbol="TEST", bars=bars, fundamentals=fundamentals or {})


def _flat_closes(n=40, price=100.0):
    return [price] * n


def test_value_investor_bullish_on_cheap_safe_profitable_company():
    snapshot = _snapshot(
        _flat_closes(),
        fundamentals={"pe_ratio": 10.0, "debt_to_equity": 20.0, "profit_margin": 0.25},
    )
    report = ValueInvestorAnalyst(DummyLLMClient()).analyze(snapshot)
    assert report.signal == Signal.BULLISH
    assert report.confidence > 0


def test_value_investor_bearish_on_expensive_leveraged_unprofitable_company():
    snapshot = _snapshot(
        _flat_closes(),
        fundamentals={"pe_ratio": 40.0, "debt_to_equity": 200.0, "profit_margin": -0.05},
    )
    report = ValueInvestorAnalyst(DummyLLMClient()).analyze(snapshot)
    assert report.signal == Signal.BEARISH


def test_value_investor_neutral_with_no_fundamentals():
    report = ValueInvestorAnalyst(DummyLLMClient()).analyze(_snapshot(_flat_closes()))
    assert report.signal == Signal.NEUTRAL
    assert report.confidence == 0.0


def test_growth_investor_bullish_on_high_growth_and_momentum():
    closes = [100 * (1.01**i) for i in range(30)]  # steady uptrend -> positive 20-bar momentum
    snapshot = _snapshot(closes, fundamentals={"revenue_growth_yoy": 0.35})
    report = GrowthInvestorAnalyst(DummyLLMClient()).analyze(snapshot)
    assert report.signal == Signal.BULLISH


def test_growth_investor_bearish_on_negative_growth():
    snapshot = _snapshot(_flat_closes(), fundamentals={"revenue_growth_yoy": -0.10})
    report = GrowthInvestorAnalyst(DummyLLMClient()).analyze(snapshot)
    assert report.signal == Signal.BEARISH


def test_contrarian_bullish_on_oversold_rsi_and_high_vix():
    # A sharp, sustained decline drives RSI low.
    closes = [100 - i * 2 for i in range(20)]
    snapshot = _snapshot(closes)
    report = ContrarianInvestorAnalyst(DummyLLMClient(), vix_level=30.0).analyze(snapshot)
    assert report.signal == Signal.BULLISH


def test_contrarian_bearish_on_overbought_rsi_and_low_vix():
    closes = [100 + i * 2 for i in range(20)]
    snapshot = _snapshot(closes)
    report = ContrarianInvestorAnalyst(DummyLLMClient(), vix_level=10.0).analyze(snapshot)
    assert report.signal == Signal.BEARISH


def test_contrarian_reads_vix_opposite_of_macro_analyst():
    # High VIX is bearish for MacroAnalyst but bullish for the contrarian —
    # that divergence is the entire point of this persona. Alternating
    # closes keep RSI at a neutral ~50 (equal up/down changes) and 10-bar
    # momentum at ~0, isolating the VIX contribution from both analysts.
    from trading_agent.agents.analysts import MacroAnalyst
    from trading_agent.data.macro import MacroSnapshot

    class _StaticMacro:
        def get_macro_snapshot(self):
            return MacroSnapshot(vix_level=30.0)

    closes = [100, 101] * 10
    snapshot = _snapshot(closes)
    macro_report = MacroAnalyst(DummyLLMClient(), _StaticMacro()).analyze(snapshot)
    contrarian_report = ContrarianInvestorAnalyst(DummyLLMClient(), vix_level=30.0).analyze(snapshot)
    assert macro_report.signal == Signal.BEARISH
    assert contrarian_report.signal == Signal.BULLISH
