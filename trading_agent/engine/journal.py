"""Automatic trade journal + the bounded feedback loop into `ReflectionMemory`.

`TradeJournal` documents every booked decision — the rationale (why) and
the resulting portfolio state (what changed) — as an append-only JSONL
file, automatically, so nothing needs to be transcribed by hand later.

`record_execution` is the one function every caller (`cli.py`,
`engine/backtest.py`, and the web session layer) should call right after
`PaperBroker.execute(...)`. It journals the decision and, if this
execution closed/reduced/stopped-out a position (i.e. realized a PnL),
appends a short, deterministically-worded reflection. `TradingCycle`
already resurfaces `ReflectionMemory.recent_lessons()` as extra context
for the trader's narration (see `agents/trader.py`) — that's the entire
"adaptation" loop: past outcomes become text a human can read, not a
mechanism that can silently rewrite the trading rules.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from trading_agent.engine.memory import ReflectionEntry, ReflectionMemory
from trading_agent.engine.orchestrator import CycleArtifacts
from trading_agent.engine.paper_broker import PaperBroker


@dataclass
class JournalEntry:
    ts: float
    symbol: str
    action: str
    entry_price: float
    leverage: float
    rationale: str
    analyst_signals: dict
    risk_notes: list
    equity_after: float
    realized_pnl_after: float
    open_positions_after: dict


class TradeJournal:
    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def record(self, entry: JournalEntry) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

    def load_all(self) -> list[dict]:
        if not self._path.exists():
            return []
        return [json.loads(line) for line in self._path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_journal_entry(artifacts: CycleArtifacts, broker: PaperBroker) -> JournalEntry:
    plan = artifacts.decision.trade_plan
    current_price = plan.entry_price
    return JournalEntry(
        ts=time.time(),
        symbol=plan.symbol,
        action=plan.action.value,
        entry_price=plan.entry_price,
        leverage=artifacts.decision.risk_verdict.adjusted_leverage,
        rationale=plan.rationale,
        analyst_signals={r.agent_name: r.signal.value for r in artifacts.analyst_reports},
        risk_notes=list(artifacts.decision.risk_verdict.violations_corrected),
        equity_after=broker.equity({plan.symbol: current_price}),
        realized_pnl_after=broker.realized_pnl,
        open_positions_after={sym: pos.quantity for sym, pos in broker.positions.items()},
    )


def record_execution(
    artifacts: CycleArtifacts,
    broker: PaperBroker,
    journal: TradeJournal | None = None,
    reflection_memory: ReflectionMemory | None = None,
) -> None:
    """Call this immediately after `broker.execute(artifacts.decision)`."""
    if journal is not None:
        journal.record(build_journal_entry(artifacts, broker))

    if reflection_memory is not None and broker.trade_log:
        last = broker.trade_log[-1]
        if last.get("pnl") is not None:
            plan = artifacts.decision.trade_plan
            outcome = "profitable" if last["pnl"] > 0 else "losing"
            lesson = (
                f"{outcome} {last['action']} on {last['symbol']}: pnl={last['pnl']:+.2f} "
                f"(entry rationale: {plan.rationale[:120]})"
            )
            reflection_memory.append(
                ReflectionEntry(
                    symbol=last["symbol"],
                    action=last["action"],
                    entry_price=plan.entry_price,
                    exit_price=last["price"],
                    pnl=last["pnl"],
                    lesson=lesson,
                )
            )
