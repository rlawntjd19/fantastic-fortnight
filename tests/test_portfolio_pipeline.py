from trading_agent.config import DEFAULT_CONFIG
from trading_agent.data.macro import StaticMacroProvider
from trading_agent.data.providers import SimulatedFeed
from trading_agent.forecast.heuristic_forecaster import HeuristicForecaster
from trading_agent.llm.client import DummyLLMClient
from trading_agent.portfolio.pipeline import run_portfolio_research
from trading_agent.portfolio.report import render_markdown_report
from trading_agent.portfolio.universe import UNIVERSE


def _run(**overrides):
    provider = SimulatedFeed(seed=11, n_bars=260)
    kwargs = dict(
        config=DEFAULT_CONFIG,
        llm=DummyLLMClient(),
        data_provider=provider,
        macro_provider=StaticMacroProvider(),
        forecaster=HeuristicForecaster(),
        budget=25_000.0,
    )
    kwargs.update(overrides)
    return run_portfolio_research(**kwargs)


def test_pipeline_screens_the_whole_universe():
    report = _run()
    assert len(report.universe) == len(UNIVERSE)
    assert {c.symbol for c in report.universe} == {e.symbol for e in UNIVERSE}


def test_pipeline_selects_between_two_and_five_stocks():
    report = _run()
    assert 2 <= len(report.selected) <= 5


def test_pipeline_respects_min_and_max_stocks_override():
    report = _run(min_stocks=3, max_stocks=3)
    assert len(report.selected) == 3


def test_pipeline_allocation_never_exceeds_budget():
    report = _run(budget=25_000.0)
    spent = sum(a.dollars for a in report.allocation)
    assert spent + report.leftover_cash <= 25_000.0 + 1e-6
    assert spent <= 25_000.0 + 1e-6


def test_pipeline_optimized_weights_sum_to_one():
    report = _run()
    assert sum(report.optimized.weights.values()) - 1.0 < 1e-6


def test_pipeline_backtest_and_forward_simulation_present():
    report = _run()
    assert report.backtest.num_bars > 0
    assert report.forward_simulation.horizon_days == 63
    assert 0.0 <= report.forward_simulation.prob_positive <= 1.0


def test_pipeline_is_deterministic_offline():
    r1 = _run()
    r2 = _run()
    assert [c.symbol for c in r1.selected] == [c.symbol for c in r2.selected]
    assert r1.optimized.weights == r2.optimized.weights


def test_markdown_report_renders_without_error_and_mentions_selected_symbols():
    report = _run()
    memo = render_markdown_report(report)
    assert "Investment Committee Memo" in memo
    for c in report.selected:
        assert c.symbol in memo
