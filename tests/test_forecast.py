import pytest

from trading_agent.agents.analysts import ForecastAnalyst
from trading_agent.data.providers import SimulatedFeed
from trading_agent.forecast.factory import build_price_forecaster
from trading_agent.forecast.heuristic_forecaster import HeuristicForecaster
from trading_agent.llm.client import DummyLLMClient


def test_heuristic_forecaster_extrapolates_uptrend_positively():
    closes = [100.0 * (1.01**i) for i in range(30)]  # steady 1% per bar uptrend
    result = HeuristicForecaster().forecast(closes, pred_len=5)
    assert result.expected_return > 0
    assert result.source == "heuristic"
    assert len(result.predicted_closes) == 5


def test_heuristic_forecaster_flat_series_has_near_zero_expected_return():
    closes = [100.0] * 30
    result = HeuristicForecaster().forecast(closes, pred_len=5)
    assert result.expected_return == pytest.approx(0.0, abs=1e-9)
    assert result.dispersion == pytest.approx(0.0, abs=1e-9)


def test_heuristic_forecaster_downtrend_is_negative():
    closes = [100.0 * (0.99**i) for i in range(30)]
    result = HeuristicForecaster().forecast(closes, pred_len=5)
    assert result.expected_return < 0


def test_heuristic_forecaster_handles_too_little_data():
    result = HeuristicForecaster().forecast([100.0], pred_len=5)
    assert result.predicted_closes == [100.0] * 5
    assert result.expected_return == 0.0


def test_forecast_analyst_produces_bullish_report_on_uptrend():
    closes = [100.0 * (1.02**i) for i in range(30)]

    class _FixedFeed:
        def get_snapshot(self, symbol):
            from trading_agent.data.providers import Bar, MarketSnapshot

            bars = [Bar(i, c, c, c, c, 1000) for i, c in enumerate(closes)]
            return MarketSnapshot(symbol=symbol, bars=bars)

    analyst = ForecastAnalyst(DummyLLMClient(), HeuristicForecaster(), pred_len=5)
    report = analyst.analyze(_FixedFeed().get_snapshot("TEST"))
    assert report.signal.value == "bullish"
    assert report.agent_name == "forecast_analyst"


def test_build_price_forecaster_defaults_to_heuristic_when_kronos_disabled():
    from trading_agent.config import DEFAULT_CONFIG

    forecaster = build_price_forecaster(DEFAULT_CONFIG)
    assert isinstance(forecaster, HeuristicForecaster)


def test_build_price_forecaster_falls_back_when_kronos_enabled_but_unavailable():
    import dataclasses

    from trading_agent.config import DEFAULT_CONFIG

    cfg = dataclasses.replace(
        DEFAULT_CONFIG, kronos=dataclasses.replace(DEFAULT_CONFIG.kronos, enabled=True)
    )
    # Kronos (the `model` package) is not installed in this test environment,
    # so construction must degrade gracefully rather than raising.
    forecaster = build_price_forecaster(cfg)
    assert isinstance(forecaster, HeuristicForecaster)


def test_kronos_forecaster_raises_actionable_error_when_uninstalled():
    from trading_agent.forecast.kronos_forecaster import KronosForecaster

    with pytest.raises(RuntimeError, match="pip install"):
        KronosForecaster()
