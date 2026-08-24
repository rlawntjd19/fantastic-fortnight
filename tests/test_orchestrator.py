from trading_agent.config import DEFAULT_CONFIG, Config, RiskLimits
from trading_agent.data.providers import SimulatedFeed
from trading_agent.engine.orchestrator import TradingCycle
from trading_agent.engine.risk_controls import DailyCircuitBreaker
from trading_agent.llm.client import DummyLLMClient


def _run(leverage=20.0, tranches=5, config=None):
    cfg = config or DEFAULT_CONFIG
    cycle = TradingCycle(
        cfg,
        DummyLLMClient(),
        SimulatedFeed(seed=1),
        requested_leverage=leverage,
        requested_tranches=tranches,
    )
    return cycle.run_cycle("TEST_SYMBOL", account_equity=cfg.starting_paper_equity)


def test_cycle_runs_fully_offline_and_produces_a_decision():
    artifacts = _run()
    # technical, fundamental, sentiment, forecast (heuristic fallback by default)
    assert len(artifacts.analyst_reports) == 4
    assert {r.agent_name for r in artifacts.analyst_reports} == {
        "technical_analyst",
        "fundamental_analyst",
        "sentiment_analyst",
        "forecast_analyst",
    }
    assert artifacts.decision.requires_human_approval is True


def test_forecast_analyst_uses_heuristic_fallback_when_kronos_disabled():
    artifacts = _run()
    forecast_report = next(
        r for r in artifacts.analyst_reports if r.agent_name == "forecast_analyst"
    )
    assert forecast_report.key_points[0].startswith("heuristic ")


def test_cycle_never_exceeds_configured_leverage_ceiling_regardless_of_request():
    artifacts = _run(leverage=20.0)  # mirrors the 20x from the source transcript
    limits = DEFAULT_CONFIG.risk
    assert artifacts.decision.risk_verdict.adjusted_leverage <= limits.max_leverage


def test_cycle_never_exceeds_configured_position_size_ceiling():
    artifacts = _run(tranches=5)
    limits = DEFAULT_CONFIG.risk
    assert (
        artifacts.decision.risk_verdict.adjusted_position_pct_of_equity
        <= limits.max_position_pct_of_equity
    )


def test_decision_status_is_pending_approval_when_within_limits():
    cfg = Config(risk=RiskLimits(max_leverage=3.0, max_position_pct_of_equity=0.10))
    artifacts = _run(leverage=1.0, tranches=1, config=cfg)
    if artifacts.decision.trade_plan.action.value != "hold":
        assert artifacts.decision.status == "pending_approval"


def test_circuit_breaker_blocks_new_signal_after_large_simulated_drawdown():
    cfg = DEFAULT_CONFIG
    breaker = DailyCircuitBreaker(
        starting_equity=cfg.starting_paper_equity,
        limit_pct=cfg.risk.daily_loss_circuit_breaker_pct,
    )
    cycle = TradingCycle(cfg, DummyLLMClient(), SimulatedFeed(seed=1), requested_leverage=1.0)
    drawn_down_equity = cfg.starting_paper_equity * 0.90  # below the 5% default limit
    artifacts = cycle.run_cycle(
        "TEST_SYMBOL", account_equity=drawn_down_equity, circuit_breaker=breaker
    )
    if artifacts.decision.trade_plan.action.value != "hold":
        assert artifacts.decision.status == "blocked"
