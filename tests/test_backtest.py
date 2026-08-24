import pytest

from trading_agent.config import DEFAULT_CONFIG
from trading_agent.data.providers import SimulatedFeed
from trading_agent.engine.backtest import ReplayFeed, run_backtest
from trading_agent.engine.orchestrator import TradingCycle
from trading_agent.engine.paper_broker import PaperBroker
from trading_agent.llm.client import DummyLLMClient


def test_replay_feed_never_reveals_future_bars():
    full = SimulatedFeed(seed=5, n_bars=50).get_snapshot("AAPL")
    replay = ReplayFeed(full, min_lookback=10)

    first = replay.get_snapshot("AAPL")
    assert len(first.bars) == 10
    assert first.bars == full.bars[:10]

    replay.advance()
    second = replay.get_snapshot("AAPL")
    assert len(second.bars) == 11
    # everything visible so far must be a strict prefix of the full series
    assert second.bars == full.bars[:11]


def test_replay_feed_done_flag():
    full = SimulatedFeed(seed=5, n_bars=12).get_snapshot("AAPL")
    replay = ReplayFeed(full, min_lookback=10)
    assert not replay.done
    replay.advance()
    assert not replay.done
    replay.advance()
    assert replay.done


def test_replay_feed_rejects_too_small_lookback():
    full = SimulatedFeed(n_bars=50).get_snapshot("AAPL")
    with pytest.raises(ValueError):
        ReplayFeed(full, min_lookback=1)


def test_run_backtest_produces_full_equity_curve_and_report():
    full = SimulatedFeed(seed=9, n_bars=60).get_snapshot("AAPL")
    replay = ReplayFeed(full, min_lookback=35)
    broker = PaperBroker(cash_equity=DEFAULT_CONFIG.starting_paper_equity)
    cycle = TradingCycle(DEFAULT_CONFIG, DummyLLMClient(), replay, requested_leverage=1.0)

    result = run_backtest(cycle, replay, broker, "AAPL")

    assert result.num_ticks == 60 - 35
    assert len(result.equity_curve) == result.num_ticks
    assert result.performance.starting_equity == result.equity_curve[0][1]
    assert result.performance.ending_equity == result.equity_curve[-1][1]


def test_run_backtest_never_exceeds_leverage_ceiling():
    full = SimulatedFeed(seed=9, n_bars=60).get_snapshot("AAPL")
    replay = ReplayFeed(full, min_lookback=35)
    broker = PaperBroker(cash_equity=DEFAULT_CONFIG.starting_paper_equity)
    cycle = TradingCycle(DEFAULT_CONFIG, DummyLLMClient(), replay, requested_leverage=20.0)

    run_backtest(cycle, replay, broker, "AAPL")

    for pos in broker.positions.values():
        assert pos.leverage <= DEFAULT_CONFIG.risk.max_leverage
