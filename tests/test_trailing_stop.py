import pytest

from trading_agent.engine.paper_broker import PaperBroker, Position
from trading_agent.engine.risk_controls import trailing_stop_price


def test_long_trailing_stop_ratchets_up_as_price_rises():
    new_stop = trailing_stop_price(quantity=10, current_stop=90.0, current_price=110.0, trailing_stop_pct=0.05)
    assert new_stop == pytest.approx(110.0 * 0.95)


def test_long_trailing_stop_never_loosens_on_pullback():
    # stop was already at 100 from a prior high; price pulls back to 95
    new_stop = trailing_stop_price(quantity=10, current_stop=100.0, current_price=95.0, trailing_stop_pct=0.05)
    assert new_stop == 100.0


def test_short_trailing_stop_ratchets_down_as_price_falls():
    new_stop = trailing_stop_price(quantity=-10, current_stop=110.0, current_price=90.0, trailing_stop_pct=0.05)
    assert new_stop == pytest.approx(90.0 * 1.05)


def test_short_trailing_stop_never_loosens_on_bounce():
    new_stop = trailing_stop_price(quantity=-10, current_stop=95.0, current_price=100.0, trailing_stop_pct=0.05)
    assert new_stop == 95.0


def test_paper_broker_apply_trailing_stops_updates_open_positions():
    broker = PaperBroker(cash_equity=1_000_000)
    broker.positions["AAPL"] = Position(
        symbol="AAPL", quantity=100, avg_entry_price=100.0, leverage=1.0, stop_loss_price=90.0
    )
    broker.apply_trailing_stops({"AAPL": 120.0}, trailing_stop_pct=0.05)
    assert broker.positions["AAPL"].stop_loss_price == pytest.approx(120.0 * 0.95)


def test_paper_broker_apply_trailing_stops_skips_symbols_without_a_price():
    broker = PaperBroker(cash_equity=1_000_000)
    broker.positions["AAPL"] = Position(
        symbol="AAPL", quantity=100, avg_entry_price=100.0, leverage=1.0, stop_loss_price=90.0
    )
    broker.apply_trailing_stops({}, trailing_stop_pct=0.05)
    assert broker.positions["AAPL"].stop_loss_price == 90.0
