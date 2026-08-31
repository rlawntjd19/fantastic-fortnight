import pytest

from trading_agent.data.providers import Bar, MarketSnapshot
from trading_agent.portfolio.schemas import AllocationLine
from trading_agent.portfolio.watch import PortfolioWatcher, run_loop


class _FakeProvider:
    """Returns queued prices per symbol; raises once a symbol's queue is
    exhausted, to simulate a fetch failure on a later tick."""

    def __init__(self, prices_by_symbol: dict[str, list[float]]):
        self._queues = {s: list(p) for s, p in prices_by_symbol.items()}

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        queue = self._queues.get(symbol, [])
        if not queue:
            raise RuntimeError(f"no more prices queued for {symbol}")
        price = queue.pop(0)
        return MarketSnapshot(symbol=symbol, bars=[Bar(0, price, price, price, price, 100.0)])


def _allocation(symbol="AAPL", shares=10, price=100.0):
    return AllocationLine(symbol=symbol, target_weight=1.0, price=price, shares=shares, dollars=shares * price, actual_weight=1.0)


def test_tick_computes_value_and_pnl_for_a_price_gain():
    provider = _FakeProvider({"AAPL": [110.0]})
    watcher = PortfolioWatcher([_allocation(shares=10, price=100.0)], leftover_cash=50.0, provider=provider)

    tick = watcher.tick()

    assert tick.positions[0].current_price == 110.0
    assert tick.positions[0].current_value == 1100.0
    assert tick.positions[0].pnl_dollars == 100.0
    assert tick.positions[0].pnl_pct == pytest.approx(0.10)
    assert tick.cash == 50.0
    assert tick.total_value == 1150.0
    assert tick.total_cost_basis == 1050.0
    assert tick.total_pnl_dollars == 100.0
    assert not tick.errors


def test_tick_computes_loss_correctly():
    provider = _FakeProvider({"AAPL": [90.0]})
    watcher = PortfolioWatcher([_allocation(shares=10, price=100.0)], leftover_cash=0.0, provider=provider)

    tick = watcher.tick()

    assert tick.positions[0].pnl_dollars == -100.0
    assert tick.positions[0].pnl_pct == pytest.approx(-0.10)
    assert tick.total_pnl_dollars == -100.0


def test_zero_share_allocations_are_excluded():
    allocations = [_allocation(symbol="AAPL", shares=10, price=100.0), _allocation(symbol="HD", shares=0, price=300.0)]
    provider = _FakeProvider({"AAPL": [100.0]})
    watcher = PortfolioWatcher(allocations, leftover_cash=0.0, provider=provider)

    tick = watcher.tick()

    assert [p.symbol for p in tick.positions] == ["AAPL"]


def test_a_failed_fetch_marks_that_position_stale_but_does_not_raise():
    provider = _FakeProvider({"AAPL": []})  # immediately raises
    watcher = PortfolioWatcher([_allocation(symbol="AAPL", shares=10, price=100.0)], leftover_cash=0.0, provider=provider)

    tick = watcher.tick()  # must not raise

    assert tick.positions[0].stale is True
    assert tick.positions[0].current_price == 100.0  # held at cost basis, not zeroed
    assert "AAPL" in tick.errors


def test_a_failed_fetch_does_not_affect_other_positions():
    provider = _FakeProvider({"AAPL": [], "HD": [310.0]})
    allocations = [_allocation(symbol="AAPL", shares=10, price=100.0), _allocation(symbol="HD", shares=5, price=300.0)]
    watcher = PortfolioWatcher(allocations, leftover_cash=0.0, provider=provider)

    tick = watcher.tick()

    hd = next(p for p in tick.positions if p.symbol == "HD")
    assert hd.stale is False
    assert hd.current_price == 310.0
    assert "AAPL" in tick.errors
    assert "HD" not in tick.errors


def test_run_loop_calls_on_tick_max_iterations_times():
    provider = _FakeProvider({"AAPL": [100.0, 101.0, 102.0]})
    watcher = PortfolioWatcher([_allocation(symbol="AAPL", shares=1, price=100.0)], leftover_cash=0.0, provider=provider)

    seen = []
    run_loop(watcher, interval_seconds=0.0, max_iterations=3, on_tick=lambda i, tick: seen.append((i, tick.total_value)))

    assert [i for i, _ in seen] == [0, 1, 2]
    assert [v for _, v in seen] == [100.0, 101.0, 102.0]
