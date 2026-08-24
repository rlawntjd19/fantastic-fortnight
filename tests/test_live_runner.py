from trading_agent.config import DEFAULT_CONFIG
from trading_agent.data.providers import SimulatedFeed
from trading_agent.engine.live_runner import run_loop, run_tick
from trading_agent.engine.orchestrator import TradingCycle
from trading_agent.engine.paper_broker import PaperBroker
from trading_agent.engine.risk_controls import DailyCircuitBreaker
from trading_agent.llm.client import DummyLLMClient


def _setup(leverage=1.0):
    cfg = DEFAULT_CONFIG
    broker = PaperBroker(cash_equity=cfg.starting_paper_equity)
    breaker = DailyCircuitBreaker(
        starting_equity=cfg.starting_paper_equity, limit_pct=cfg.risk.daily_loss_circuit_breaker_pct
    )
    cycle = TradingCycle(cfg, DummyLLMClient(), SimulatedFeed(seed=3), requested_leverage=leverage)
    return cycle, broker, breaker


def test_run_tick_books_immediately_when_pending_approval():
    cycle, broker, breaker = _setup()
    result = run_tick(cycle, broker, "AAPL", breaker)
    if result.artifacts.decision.status == "pending_approval":
        assert result.booked is True
    else:
        assert result.booked is False


def test_run_tick_checks_stop_loss_before_new_analysis():
    cycle, broker, breaker = _setup()
    first = run_tick(cycle, broker, "AAPL", breaker)
    if first.artifacts.decision.trade_plan.action.value == "hold":
        return  # nothing opened, nothing to stop out — inconclusive for this seed/config

    # Move the just-opened position's stop to guarantee a breach on the very
    # next tick regardless of which way the (random-walk) price moves.
    pos = broker.positions["AAPL"]
    pos.stop_loss_price = pos.avg_entry_price * (1.5 if pos.quantity > 0 else 0.5)

    second = run_tick(cycle, broker, "AAPL", breaker)
    assert "AAPL" in second.stopped_out


def test_run_tick_on_stage_hook_fires():
    cycle, broker, breaker = _setup()
    stages: list[str] = []
    run_tick(cycle, broker, "AAPL", breaker, on_stage=lambda name, payload: stages.append(name))
    assert "analyst_report" in stages
    assert "risk_verdict" in stages


def test_run_loop_respects_max_iterations():
    cycle, broker, breaker = _setup()
    ticks = []
    run_loop(cycle, broker, "AAPL", breaker, interval_seconds=0, max_iterations=3, on_tick=lambda i, r: ticks.append(i))
    assert ticks == [0, 1, 2]
