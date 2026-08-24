import json
import os

import pytest

from trading_agent.agents.schemas import Action, FinalDecision, RiskVerdict, TradePlan
from trading_agent.engine.memory import ReflectionMemory
from trading_agent.engine.orchestrator import CycleArtifacts
from trading_agent.engine.paper_broker import PaperBroker


def _artifacts(action=Action.BUY, entry=100.0, rationale="test rationale"):
    plan = TradePlan(
        symbol="TEST",
        action=action,
        entry_price=entry,
        target_price=110.0,
        stop_loss_price=95.0,
        leverage=1.0,
        tranche_sizes=[1.0],
        rationale=rationale,
    )
    verdict = RiskVerdict(
        approved=True, adjusted_leverage=1.0, adjusted_position_pct_of_equity=0.10,
        violations_corrected=[], notes="",
    )
    decision = FinalDecision(trade_plan=plan, risk_verdict=verdict, status="pending_approval")
    return CycleArtifacts(analyst_reports=[], aggressive_take="", conservative_take="", risk_moderator_summary="", decision=decision)


@pytest.fixture
def tmp_paths(tmp_path):
    return str(tmp_path / "journal.jsonl"), str(tmp_path / "memory.json")


def test_record_execution_writes_journal_entry(tmp_paths):
    from trading_agent.engine.journal import TradeJournal, record_execution

    journal_path, _ = tmp_paths
    broker = PaperBroker(cash_equity=1_000_000)
    artifacts = _artifacts()
    broker.execute(artifacts.decision)

    journal = TradeJournal(journal_path)
    record_execution(artifacts, broker, journal=journal, reflection_memory=None)

    entries = journal.load_all()
    assert len(entries) == 1
    assert entries[0]["symbol"] == "TEST"
    assert entries[0]["rationale"] == "test rationale"
    assert entries[0]["action"] == "buy"


def test_record_execution_does_not_reflect_on_an_open(tmp_paths):
    from trading_agent.engine.journal import record_execution

    _, memory_path = tmp_paths
    broker = PaperBroker(cash_equity=1_000_000)
    artifacts = _artifacts()
    broker.execute(artifacts.decision)

    memory = ReflectionMemory(memory_path)
    record_execution(artifacts, broker, journal=None, reflection_memory=memory)

    assert memory.recent_lessons("TEST") == []  # opening a position isn't a "lesson" yet


def test_record_execution_reflects_on_a_close_with_realized_pnl(tmp_paths):
    from trading_agent.engine.journal import record_execution

    _, memory_path = tmp_paths
    broker = PaperBroker(cash_equity=1_000_000)
    open_artifacts = _artifacts(entry=100.0, rationale="opened long on bullish consensus")
    broker.execute(open_artifacts.decision)

    # The lesson should describe *this* closing decision's own rationale
    # (why the trader chose to close here), not the original entry's.
    close_artifacts = _artifacts(action=Action.CLOSE, entry=120.0, rationale="target reached, closing")
    broker.execute(close_artifacts.decision)

    memory = ReflectionMemory(memory_path)
    record_execution(close_artifacts, broker, journal=None, reflection_memory=memory)

    lessons = memory.recent_lessons("TEST")
    assert len(lessons) == 1
    assert "profitable" in lessons[0]
    assert "target reached, closing" in lessons[0]


def test_journal_file_is_append_only_across_calls(tmp_paths):
    from trading_agent.engine.journal import TradeJournal, record_execution

    journal_path, _ = tmp_paths
    broker = PaperBroker(cash_equity=1_000_000)
    journal = TradeJournal(journal_path)

    for i in range(3):
        artifacts = _artifacts(entry=100.0 + i)
        broker.execute(artifacts.decision)
        record_execution(artifacts, broker, journal=journal, reflection_memory=None)

    assert len(journal.load_all()) == 3
