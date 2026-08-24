from trading_agent.agents.schemas import Action, TradePlan
from trading_agent.config import RiskLimits
from trading_agent.engine.risk_controls import DailyCircuitBreaker, enforce_hard_limits


def _plan(**overrides):
    base = dict(
        symbol="TEST",
        action=Action.BUY,
        entry_price=100.0,
        target_price=110.0,
        stop_loss_price=98.0,
        leverage=1.0,
        tranche_sizes=[0.5, 0.5],
        rationale="test",
    )
    base.update(overrides)
    return TradePlan(**base)


def test_leverage_is_clamped_to_hard_ceiling_even_if_requested_higher():
    limits = RiskLimits(max_leverage=3.0)
    plan = _plan(leverage=20.0)  # the 20x from the transcript this design responds to
    verdict = enforce_hard_limits(plan, limits, account_equity=1_000_000)
    assert verdict.adjusted_leverage == 3.0
    assert any("leverage" in v for v in verdict.violations_corrected)


def test_leverage_within_limit_is_untouched():
    limits = RiskLimits(max_leverage=3.0)
    plan = _plan(leverage=2.0)
    verdict = enforce_hard_limits(plan, limits, account_equity=1_000_000)
    assert verdict.adjusted_leverage == 2.0
    assert not any("leverage" in v for v in verdict.violations_corrected)


def test_position_size_is_clamped_to_equity_pct_ceiling():
    limits = RiskLimits(max_position_pct_of_equity=0.10)
    plan = _plan(tranche_sizes=[0.5, 0.5])  # requests 100% of equity
    verdict = enforce_hard_limits(plan, limits, account_equity=1_000_000)
    assert verdict.adjusted_position_pct_of_equity == 0.10


def test_missing_stop_loss_blocks_the_trade():
    limits = RiskLimits()
    plan = _plan(stop_loss_price=100.0)  # entry == stop => zero distance
    verdict = enforce_hard_limits(plan, limits, account_equity=1_000_000)
    assert verdict.approved is False


def test_hold_action_is_always_approved_with_no_exposure():
    limits = RiskLimits()
    plan = _plan(action=Action.HOLD)
    verdict = enforce_hard_limits(plan, limits, account_equity=1_000_000)
    assert verdict.approved is True
    assert verdict.adjusted_leverage == 0.0


def test_circuit_breaker_blocks_new_entries_but_not_close():
    limits = RiskLimits(daily_loss_circuit_breaker_pct=0.05)
    breaker = DailyCircuitBreaker(starting_equity=1_000_000, limit_pct=0.05)

    buy_plan = _plan(action=Action.BUY)
    verdict = enforce_hard_limits(
        buy_plan, limits, account_equity=940_000, circuit_breaker=breaker
    )
    assert verdict.approved is False
    assert "daily_circuit_breaker" in verdict.violations_corrected

    close_plan = _plan(action=Action.CLOSE)
    verdict = enforce_hard_limits(
        close_plan, limits, account_equity=940_000, circuit_breaker=breaker
    )
    assert verdict.approved is True


def test_circuit_breaker_does_not_trip_before_threshold():
    breaker = DailyCircuitBreaker(starting_equity=1_000_000, limit_pct=0.05)
    assert breaker.tripped(960_000) is False
    assert breaker.tripped(940_000) is True
