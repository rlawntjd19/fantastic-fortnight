import pytest

from trading_agent.agents.schemas import Action, FinalDecision, RiskVerdict, TradePlan
from trading_agent.engine.paper_broker import PaperBroker


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
        status="pending_approval" if approved else "blocked",
    )


def test_execute_rejects_a_decision_blocked_by_risk_controls():
    broker = PaperBroker(cash_equity=1_000_000)
    decision = _decision(approved=False)
    with pytest.raises(ValueError):
        broker.execute(decision)


def test_buy_opens_a_long_position_sized_by_risk_verdict():
    broker = PaperBroker(cash_equity=1_000_000)
    decision = _decision(entry=100.0, pct=0.10, leverage=1.0)
    broker.execute(decision)

    pos = broker.positions["TEST"]
    assert pos.quantity == pytest.approx(1000.0)  # 1,000,000 * 0.10 / 100
    assert pos.avg_entry_price == 100.0


def test_sell_opens_a_short_position():
    broker = PaperBroker(cash_equity=1_000_000)
    decision = _decision(action=Action.SELL, entry=100.0, pct=0.10, leverage=1.0)
    broker.execute(decision)

    assert broker.positions["TEST"].quantity < 0


def test_mark_to_market_pnl_for_long_position():
    broker = PaperBroker(cash_equity=1_000_000)
    broker.execute(_decision(entry=100.0, pct=0.10, leverage=1.0))
    equity_up = broker.equity({"TEST": 110.0})
    equity_flat = broker.equity({"TEST": 100.0})
    assert equity_up > equity_flat


def test_stop_loss_auto_closes_long_position_when_breached():
    broker = PaperBroker(cash_equity=1_000_000)
    broker.execute(
        _decision(entry=100.0, stop=95.0, pct=0.10, leverage=1.0)
    )
    closed = broker.check_stop_losses({"TEST": 94.0})
    assert closed == ["TEST"]
    assert "TEST" not in broker.positions
    assert broker.realized_pnl < 0


def test_stop_loss_does_not_trigger_when_price_above_stop():
    broker = PaperBroker(cash_equity=1_000_000)
    broker.execute(
        _decision(entry=100.0, stop=95.0, pct=0.10, leverage=1.0)
    )
    closed = broker.check_stop_losses({"TEST": 101.0})
    assert closed == []
    assert "TEST" in broker.positions


def test_close_action_realizes_pnl_and_removes_position():
    broker = PaperBroker(cash_equity=1_000_000)
    broker.execute(_decision(entry=100.0, pct=0.10, leverage=1.0))
    close_decision = _decision(action=Action.CLOSE, entry=120.0, pct=0.10, leverage=1.0)
    broker.execute(close_decision)
    assert "TEST" not in broker.positions
    assert broker.realized_pnl > 0


def test_repeated_buy_nets_into_weighted_average_entry_instead_of_resetting():
    broker = PaperBroker(cash_equity=1_000_000)
    broker.execute(_decision(entry=100.0, pct=0.10, leverage=1.0))
    first_quantity = broker.positions["TEST"].quantity

    broker.execute(_decision(entry=110.0, pct=0.10, leverage=1.0))
    pos = broker.positions["TEST"]

    # quantity should have grown (added to, not replaced)...
    assert pos.quantity > first_quantity
    # ...and the average entry price should sit between the two fill prices,
    # not be reset to the second tick's price (100 < avg < 110).
    assert 100.0 < pos.avg_entry_price < 110.0
    # so unrealized PnL at the latest price is no longer forced to zero.
    assert broker.equity({"TEST": 110.0}) > broker.equity({"TEST": 100.0})


def test_opposite_direction_order_partially_reduces_and_realizes_pnl():
    broker = PaperBroker(cash_equity=1_000_000)
    broker.execute(_decision(entry=100.0, pct=0.10, leverage=1.0))
    original_quantity = broker.positions["TEST"].quantity
    original_avg = broker.positions["TEST"].avg_entry_price

    # A small SELL at a higher price should partially reduce the long and
    # realize a profit on the closed slice, without wiping the cost basis
    # of what's left.
    small_sell = _decision(action=Action.SELL, entry=120.0, pct=0.01, leverage=1.0)
    broker.execute(small_sell)

    assert "TEST" in broker.positions
    assert broker.positions["TEST"].quantity < original_quantity
    assert broker.positions["TEST"].quantity > 0
    assert broker.positions["TEST"].avg_entry_price == original_avg
    assert broker.realized_pnl > 0


def test_opposite_direction_order_larger_than_position_flips_it():
    broker = PaperBroker(cash_equity=1_000_000)
    broker.execute(_decision(entry=100.0, pct=0.10, leverage=1.0))

    big_sell = _decision(action=Action.SELL, entry=90.0, pct=1.0, leverage=1.0)
    broker.execute(big_sell)

    assert broker.positions["TEST"].quantity < 0  # now short
    assert broker.positions["TEST"].avg_entry_price == 90.0
