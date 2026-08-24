"""Background-thread runner that wraps the existing agent pipeline for
the web UI, without modifying any of its logic — see
`engine/orchestrator.py`, `engine/live_runner.py`, `engine/backtest.py`,
`engine/paper_broker.py`. Emits structured events onto a thread-safe
queue for the WebSocket layer (`server.py`) to relay to the browser, and
exposes start/pause/resume/stop/reset so a person can control a running
session from the page.

Execution is autonomous once started, the same as `cli.py`: there is no
per-decision approval step here either — only Start/Pause/Stop as
process controls, not a trade-by-trade gate. See
`engine/paper_broker.py`'s docstring for why that's fine (no real
brokerage/exchange connection exists anywhere in this codebase).
"""
from __future__ import annotations

import dataclasses
import queue
import threading
import time

from trading_agent.config import DEFAULT_CONFIG
from trading_agent.data.factory import build_market_data_provider
from trading_agent.data.providers import SimulatedFeed
from trading_agent.engine.backtest import ReplayFeed, run_backtest
from trading_agent.engine.journal import TradeJournal, record_execution
from trading_agent.engine.live_runner import run_tick
from trading_agent.engine.orchestrator import TradingCycle
from trading_agent.engine.paper_broker import PaperBroker
from trading_agent.engine.risk_controls import DailyCircuitBreaker
from trading_agent.llm.client import build_llm_client
from trading_agent.webapp.serialization import to_jsonable


class SessionState:
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"
    ERROR = "error"


@dataclasses.dataclass
class SessionConfig:
    mode: str  # "signal" | "watch" | "backtest"
    symbol: str
    leverage: float = 1.0
    tranches: int = 2
    use_live: bool = False
    use_kronos: bool = False
    interval_seconds: float = 15.0
    period: str = "6mo"
    start_date: str | None = None
    end_date: str | None = None
    min_lookback: int = 35
    anthropic_api_key: str | None = None


class SessionRunner:
    def __init__(self, session_id: str, session_config: SessionConfig) -> None:
        self.session_id = session_id
        self.session_config = session_config
        self.state = SessionState.IDLE
        self.broker: PaperBroker | None = None
        self._events: "queue.Queue[dict]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._pause_flag = threading.Event()

    # ---- control surface, called from the WebSocket layer -----------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_flag.clear()
        self._pause_flag.clear()
        self._set_state(SessionState.RUNNING)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        if self.state == SessionState.RUNNING:
            self._pause_flag.set()
            self._set_state(SessionState.PAUSED)

    def resume(self) -> None:
        if self.state == SessionState.PAUSED:
            self._pause_flag.clear()
            self._set_state(SessionState.RUNNING)

    def stop(self) -> None:
        self._stop_flag.set()
        self._pause_flag.clear()
        if self.state in (SessionState.RUNNING, SessionState.PAUSED):
            self._set_state(SessionState.STOPPED)

    def reset(self) -> None:
        self.stop()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._events = queue.Queue()
        self.broker = None
        self._thread = None
        self._set_state(SessionState.IDLE)

    def drain_events(self) -> list[dict]:
        items = []
        try:
            while True:
                items.append(self._events.get_nowait())
        except queue.Empty:
            pass
        return items

    # ---- internals ----------------------------------------------------

    def _set_state(self, state: str) -> None:
        self.state = state
        self._emit("status", {"state": state})

    def _emit(self, kind: str, payload: dict) -> None:
        self._events.put({"kind": kind, "ts": time.time(), "data": to_jsonable(payload)})

    def _build_config(self):
        cfg = DEFAULT_CONFIG
        sc = self.session_config
        if sc.anthropic_api_key:
            cfg = dataclasses.replace(cfg, anthropic_api_key=sc.anthropic_api_key)
        if sc.use_kronos:
            cfg = dataclasses.replace(cfg, kronos=dataclasses.replace(cfg.kronos, enabled=True))
        if sc.use_live:
            live_data = dataclasses.replace(cfg.live_data, enabled=True, period=sc.period)
            cfg = dataclasses.replace(cfg, live_data=live_data)
        return cfg

    def _on_stage(self, name: str, payload: dict) -> None:
        self._emit("thought", {"stage": name, **payload})

    def _wait_while_paused(self) -> None:
        while self._pause_flag.is_set() and not self._stop_flag.is_set():
            time.sleep(0.2)

    def _emit_portfolio(self, broker: PaperBroker, symbol: str, price: float) -> None:
        self._emit(
            "portfolio",
            {
                "equity": broker.equity({symbol: price}),
                "realized_pnl": broker.realized_pnl,
                "positions": {
                    sym: {
                        "quantity": pos.quantity,
                        "avg_entry_price": pos.avg_entry_price,
                        "leverage": pos.leverage,
                        "stop_loss_price": pos.stop_loss_price,
                    }
                    for sym, pos in broker.positions.items()
                },
            },
        )

    def _run(self) -> None:
        try:
            cfg = self._build_config()
            llm = build_llm_client(cfg)
            if self.session_config.mode == "backtest":
                self._run_backtest(cfg, llm)
            elif self.session_config.mode == "watch":
                self._run_watch(cfg, llm)
            else:
                self._run_signal(cfg, llm)
            if self.state == SessionState.RUNNING:
                self._set_state(SessionState.COMPLETED)
        except Exception as exc:  # noqa: BLE001 - surface to the UI, never die silently
            self._emit("error", {"message": str(exc)})
            self._set_state(SessionState.ERROR)

    def _run_signal(self, cfg, llm) -> None:
        sc = self.session_config
        provider = build_market_data_provider(cfg)
        broker = PaperBroker(cash_equity=cfg.starting_paper_equity)
        self.broker = broker
        breaker = DailyCircuitBreaker(
            starting_equity=cfg.starting_paper_equity, limit_pct=cfg.risk.daily_loss_circuit_breaker_pct
        )
        cycle = TradingCycle(cfg, llm, provider, requested_leverage=sc.leverage, requested_tranches=sc.tranches)

        artifacts = cycle.run_cycle(
            sc.symbol, account_equity=broker.equity({}), circuit_breaker=breaker, on_stage=self._on_stage
        )
        booked = artifacts.decision.status == "pending_approval"
        if booked:
            broker.execute(artifacts.decision)
            record_execution(artifacts, broker, TradeJournal(cfg.journal_path), cycle.reflection_memory)
        self._emit("decision", {"artifacts": artifacts, "booked": booked})
        self._emit_portfolio(broker, sc.symbol, artifacts.decision.trade_plan.entry_price)

    def _run_watch(self, cfg, llm) -> None:
        sc = self.session_config
        provider = build_market_data_provider(cfg)
        broker = PaperBroker(cash_equity=cfg.starting_paper_equity)
        self.broker = broker
        breaker = DailyCircuitBreaker(
            starting_equity=cfg.starting_paper_equity, limit_pct=cfg.risk.daily_loss_circuit_breaker_pct
        )
        cycle = TradingCycle(cfg, llm, provider, requested_leverage=sc.leverage, requested_tranches=sc.tranches)
        journal = TradeJournal(cfg.journal_path)

        tick = 0
        while not self._stop_flag.is_set():
            self._wait_while_paused()
            if self._stop_flag.is_set():
                break

            result = run_tick(cycle, broker, sc.symbol, breaker, on_stage=self._on_stage)
            if result.booked:
                record_execution(result.artifacts, broker, journal, cycle.reflection_memory)
            self._emit(
                "tick",
                {
                    "tick": tick,
                    "artifacts": result.artifacts,
                    "stopped_out": result.stopped_out,
                    "booked": result.booked,
                    "equity": result.equity,
                },
            )
            self._emit_portfolio(broker, sc.symbol, result.artifacts.decision.trade_plan.entry_price)
            tick += 1

            slept = 0.0
            while slept < sc.interval_seconds and not self._stop_flag.is_set() and not self._pause_flag.is_set():
                time.sleep(min(0.2, sc.interval_seconds - slept))
                slept += 0.2

    def _run_backtest(self, cfg, llm) -> None:
        sc = self.session_config
        if sc.use_live:
            from trading_agent.data.yfinance_provider import YFinanceFeed

            full_snapshot = YFinanceFeed(
                period=cfg.live_data.period,
                interval=cfg.live_data.interval,
                start=sc.start_date,
                end=sc.end_date,
            ).get_snapshot(sc.symbol)
        else:
            full_snapshot = SimulatedFeed(n_bars=max(200, sc.min_lookback + 50)).get_snapshot(sc.symbol)

        if len(full_snapshot.bars) <= sc.min_lookback:
            raise RuntimeError(
                f"데이터가 {len(full_snapshot.bars)}개 봉밖에 없어 min_lookback({sc.min_lookback})을 채울 수 없습니다."
            )

        replay = ReplayFeed(full_snapshot, min_lookback=sc.min_lookback)
        broker = PaperBroker(cash_equity=cfg.starting_paper_equity)
        self.broker = broker
        breaker = DailyCircuitBreaker(
            starting_equity=cfg.starting_paper_equity, limit_pct=cfg.risk.daily_loss_circuit_breaker_pct
        )
        cycle = TradingCycle(cfg, llm, replay, requested_leverage=sc.leverage, requested_tranches=sc.tranches)
        journal = TradeJournal(cfg.journal_path)

        def on_tick(index, snapshot, artifacts, equity) -> None:
            self._wait_while_paused()
            booked = artifacts.decision.status == "pending_approval"
            if booked:
                record_execution(artifacts, broker, journal, cycle.reflection_memory)
            self._emit(
                "tick",
                {"tick": index, "artifacts": artifacts, "equity": equity, "booked": booked, "stopped_out": []},
            )

        result = run_backtest(
            cycle,
            replay,
            broker,
            sc.symbol,
            breaker,
            on_tick=on_tick,
            should_continue=lambda: not self._stop_flag.is_set(),
        )
        self._emit("final_report", {"performance": result.performance, "num_ticks": result.num_ticks})
