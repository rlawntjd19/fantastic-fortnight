"""Regression coverage for the --live hard-fail guard in
cli._run_daily_picks: if --live was requested but the data-provider
factory fell back to something other than YFinanceFeed (e.g. yfinance
failed to import), the run must refuse outright rather than silently
publish a report full of simulated prices as if it were live data."""
import os

import trading_agent.cli as cli_module
from trading_agent.cli import main
from trading_agent.data.providers import SimulatedFeed


def test_live_run_refuses_when_provider_is_not_really_live(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Simulate the exact failure mode data/factory.py degrades to: --live
    # was requested but the provider that comes back is SimulatedFeed.
    monkeypatch.setattr(cli_module, "build_market_data_provider", lambda config: SimulatedFeed())

    exit_code = main(["daily-picks", "--live", "--date", "2026-09-02"])

    assert exit_code == 1
    assert not os.path.exists("research_team")


def test_live_run_proceeds_when_provider_is_really_live(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from trading_agent.data.yfinance_provider import YFinanceFeed

    class _FakeYFinanceFeed(YFinanceFeed):
        def __init__(self):  # skip the real yfinance import check
            pass

        def get_snapshot(self, symbol):
            from trading_agent.data.providers import SimulatedFeed as _SF

            return _SF(seed=hash(symbol) % 1000).get_snapshot(symbol)

    monkeypatch.setattr(cli_module, "build_market_data_provider", lambda config: _FakeYFinanceFeed())
    monkeypatch.setattr(
        cli_module,
        "build_macro_provider",
        lambda config: __import__("trading_agent.data.macro", fromlist=["StaticMacroProvider"]).StaticMacroProvider(),
    )
    # Otherwise --live's real config.live_data.enabled=True makes this
    # reach the real build_seasonal_history_provider(), which (since
    # yfinance is actually installed here) returns a real YFinanceFeed and
    # tries real network for SeasonalityAnalyst's long-history fetch —
    # every other live-data seam in this test is faked, this one must be
    # too.
    monkeypatch.setattr(cli_module, "build_seasonal_history_provider", lambda config: None)

    exit_code = main(["daily-picks", "--live", "--date", "2026-09-02"])

    assert exit_code == 0
    # run_id is timestamped from wall-clock time (not --date), so multiple
    # same-day --live runs never overwrite each other's report.
    written = [f for f in os.listdir("research_team/reports") if f.endswith(".md")]
    assert len(written) == 1
    assert written[0].endswith("Z.md")
    assert os.path.exists("research_team/LATEST_PICKS.md")
