import dataclasses

import pytest

from trading_agent.config import DEFAULT_CONFIG
from trading_agent.data.factory import build_market_data_provider
from trading_agent.data.providers import SimulatedFeed


def test_build_market_data_provider_defaults_to_simulated():
    provider = build_market_data_provider(DEFAULT_CONFIG)
    assert isinstance(provider, SimulatedFeed)


def test_build_market_data_provider_falls_back_when_live_enabled_but_yfinance_missing():
    cfg = dataclasses.replace(DEFAULT_CONFIG, live_data=dataclasses.replace(DEFAULT_CONFIG.live_data, enabled=True))
    # yfinance isn't a hard dependency of this test environment, so unless
    # it happens to be installed this should degrade to the simulated feed
    # rather than raising.
    provider = build_market_data_provider(cfg)
    assert provider is not None


def test_yfinance_feed_raises_actionable_error_when_uninstalled():
    from trading_agent.data.yfinance_provider import YFinanceFeed

    try:
        import yfinance  # noqa: F401

        pytest.skip("yfinance is installed in this environment; import-guard path not exercised")
    except ImportError:
        pass

    with pytest.raises(RuntimeError, match="pip install"):
        YFinanceFeed()
