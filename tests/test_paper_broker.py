import pytest

from trading_agent.agents.schemas import Action, FinalDecision, RiskVerdict, TradePlan
from trading_agent.engine.paper_broker import HumanApprovalRequiredError, PaperBroker


def _decision(action=Action.BUY, entry=100.0, stop=98.0, pct=0.10, leverage=1.0, approved=True):
    plan = TradePlan(
        symbol="TEST",
        action=action,
        entry_price=entry,
        target_price=110.0,
        stop_loss_price=stop,
        leverage=leverage,
        tranche_sizes=[1.0],
        rationale="test",
    )
    verdict = RiskVerdict(
        approved=approved,
        adjusted_leverage=leverage,
        adjusted_position_pct_of_equity=pct,
        violations_corrected=[],
        notes="",
    )
    return FinalDecision(
        trade_plan=plan,
        risk_verdict=verdict,
        requires_human_approval=True,
        status="pending_approval" if approved else "blocked",
    )


def test_execute_requires_explicit_human_approval():
    broker = PaperBroker(cash_equity=1_000_000)
    decision = _decision()
    with pytest.raises(HumanApprovalRequiredError):
        broker.execute(decision, human_approved=False)


def test_execute_rejects_blocked_decision_even_if_approved_flag_set():
    broker = PaperBroker(cash_equity=1_000_000)
    decision = _decision(approved=False)
    with pytest.raises(ValueError):
        broker.execute(decision, human_approved=True)


def test_buy_opens_a_long_position_sized_by_risk_verdict():
    broker = PaperBroker(cash_equity=1_000_000)
    decision = _decision(entry=100.0, pct=0.10, leverage=1.0)
    broker.execute(decision, human_approved=True)

    pos = broker.positions["TEST"]
    assert pos.quantity == pytest.approx(1000.0)  # 1,000,000 * 0.10 / 100
    assert pos.avg_entry_price == 100.0


def test_sell_opens_a_short_position():
    broker = PaperBroker(cash_equity=1_000_000)
    decision = _decision(action=Action.SELL, entry=100.0, pct=0.10, leverage=1.0)
    broker.execute(decision, human_approved=True)

    assert broker.positions["TEST"].quantity < 0


def test_mark_to_market_pnl_for_long_position():
    broker = PaperBroker(cash_equity=1_000_000)
    broker.execute(_decision(entry=100.0, pct=0.10, leverage=1.0), human_approved=True)
    equity_up = broker.equity({"TEST": 110.0})
    equity_flat = broker.equity({"TEST": 100.0})
    assert equity_up > equity_flat


def test_stop_loss_auto_closes_long_position_when_breached():
    broker = PaperBroker(cash_equity=1_000_000)
    broker.execute(
        _decision(entry=100.0, stop=95.0, pct=0.10, leverage=1.0), human_approved=True
    )
    closed = broker.check_stop_losses({"TEST": 94.0})
    assert closed == ["TEST"]
    assert "TEST" not in broker.positions
    assert broker.realized_pnl < 0


def test_stop_loss_does_not_trigger_when_price_above_stop():
    broker = PaperBroker(cash_equity=1_000_000)
    broker.execute(
        _decision(entry=100.0, stop=95.0, pct=0.10, leverage=1.0), human_approved=True
    )
    closed = broker.check_stop_losses({"TEST": 101.0})
    assert closed == []
    assert "TEST" in broker.positions


def test_close_action_realizes_pnl_and_removes_position():
    broker = PaperBroker(cash_equity=1_000_000)
    broker.execute(_decision(entry=100.0, pct=0.10, leverage=1.0), human_approved=True)
    close_decision = _decision(action=Action.CLOSE, entry=120.0, pct=0.10, leverage=1.0)
    broker.execute(close_decision, human_approved=True)
    assert "TEST" not in broker.positions
    assert broker.realized_pnl > 0
