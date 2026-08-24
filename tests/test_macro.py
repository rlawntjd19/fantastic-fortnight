import pytest

from trading_agent.agents.analysts import MacroAnalyst
from trading_agent.data.macro import MacroSnapshot, StaticMacroProvider
from trading_agent.data.providers import SimulatedFeed
from trading_agent.llm.client import DummyLLMClient


class _FixedMacroProvider:
    def __init__(self, snapshot: MacroSnapshot) -> None:
        self._snapshot = snapshot

    def get_macro_snapshot(self) -> MacroSnapshot:
        return self._snapshot


def test_static_macro_provider_returns_all_none():
    snapshot = StaticMacroProvider().get_macro_snapshot()
    assert snapshot.ten_year_yield_pct is None
    assert snapshot.vix_level is None
    assert snapshot.dollar_index_change_pct is None


def test_macro_analyst_is_neutral_with_no_data():
    analyst = MacroAnalyst(DummyLLMClient(), StaticMacroProvider())
    snapshot = SimulatedFeed().get_snapshot("AAPL")
    report = analyst.analyze(snapshot)
    assert report.signal.value == "neutral"
    assert report.agent_name == "macro_analyst"


def test_macro_analyst_bearish_on_high_vix():
    provider = _FixedMacroProvider(MacroSnapshot(vix_level=35.0))
    analyst = MacroAnalyst(DummyLLMClient(), provider)
    report = analyst.analyze(SimulatedFeed().get_snapshot("AAPL"))
    assert report.signal.value == "bearish"


def test_macro_analyst_bullish_on_low_vix_and_falling_yields():
    provider = _FixedMacroProvider(
        MacroSnapshot(vix_level=10.0, ten_year_yield_change_pct=-0.10, dollar_index_change_pct=-0.05)
    )
    analyst = MacroAnalyst(DummyLLMClient(), provider)
    report = analyst.analyze(SimulatedFeed().get_snapshot("AAPL"))
    assert report.signal.value == "bullish"


def test_macro_analyst_normal_vix_range_is_neutral_contribution():
    provider = _FixedMacroProvider(MacroSnapshot(vix_level=18.0))
    analyst = MacroAnalyst(DummyLLMClient(), provider)
    report = analyst.analyze(SimulatedFeed().get_snapshot("AAPL"))
    assert "normal range" in report.key_points[0]


def test_yfinance_macro_provider_raises_actionable_error_when_uninstalled():
    from trading_agent.data.macro import YFinanceMacroProvider

    try:
        import yfinance  # noqa: F401

        pytest.skip("yfinance is installed in this environment; import-guard path not exercised")
    except ImportError:
        pass

    with pytest.raises(RuntimeError, match="pip install"):
        YFinanceMacroProvider()
