"""Command-line entrypoint.

    python -m trading_agent.cli signal SYMBOL              # one cycle, books immediately if approved by risk checks
    python -m trading_agent.cli watch SYMBOL --dashboard    # runs continuously, booking every tick, with a live browser dashboard
    python -m trading_agent.cli backtest SYMBOL --live      # replays real historical data through the same pipeline

Every decision that clears risk controls (`engine/risk_controls.py`)
books immediately into the local, in-memory `PaperBroker` — there is no
per-decision prompt. This is safe only because nothing in this codebase
connects to a real brokerage or exchange; see `engine/paper_broker.py`
for why that reasoning does not extend to a real-money connector.
Nothing here promises or can guarantee profit.

Research/education tool. Not investment advice.
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
import time

from trading_agent.committee.daily_report import run_daily_cycle
from trading_agent.committee.performance_tracker import DEFAULT_STATE_PATH, load_state, save_state
from trading_agent.committee.render import write_report
from trading_agent.config import DEFAULT_CONFIG
from trading_agent.dashboard import DashboardState, start_dashboard_server
from trading_agent.data.factory import build_macro_provider, build_market_data_provider
from trading_agent.data.providers import SimulatedFeed
from trading_agent.engine.backtest import ReplayFeed, run_backtest
from trading_agent.engine.journal import TradeJournal, record_execution
from trading_agent.engine.live_runner import TickResult, run_loop
from trading_agent.engine.orchestrator import TradingCycle
from trading_agent.engine.paper_broker import PaperBroker
from trading_agent.engine.risk_controls import DailyCircuitBreaker
from trading_agent.forecast.factory import build_price_forecaster
from trading_agent.llm.client import build_llm_client


def _build_config(args):
    config = DEFAULT_CONFIG
    if getattr(args, "kronos", False):
        config = dataclasses.replace(config, kronos=dataclasses.replace(config.kronos, enabled=True))
    if getattr(args, "live", False):
        live_data = dataclasses.replace(config.live_data, enabled=True)
        if getattr(args, "period", None):
            live_data = dataclasses.replace(live_data, period=args.period)
        config = dataclasses.replace(config, live_data=live_data)
    return config


def _add_common_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("symbol", help="For --live, a real Yahoo Finance ticker (e.g. 000660.KS, AAPL).")
    parser.add_argument("--leverage", type=float, default=1.0)
    parser.add_argument("--tranches", type=int, default=2)
    parser.add_argument(
        "--kronos",
        action="store_true",
        help="Use the Kronos price-forecasting analyst instead of the offline "
        "heuristic fallback. Requires Kronos to be installed separately — "
        "see README.md. Falls back automatically if unavailable.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use real market data (Yahoo Finance via yfinance) instead of the "
        "simulated feed. Requires `pip install -r requirements-live.txt`. "
        "Unlike --kronos, a failed fetch (bad ticker, no network) is a hard "
        "error here, never a silent fallback to fake data.",
    )


def _print_decision(artifacts) -> None:
    decision = artifacts.decision
    plan = decision.trade_plan
    print("=" * 60)
    print("DISCLAIMER: research/education tool output, not investment advice.")
    print("=" * 60)
    for r in artifacts.analyst_reports:
        print(f"[{r.agent_name}] {r.signal.value} (conf {r.confidence:.2f}) — {r.summary}")
    print(f"\nAggressive view : {artifacts.aggressive_take}")
    print(f"Conservative view: {artifacts.conservative_take}")
    print(f"Moderator        : {artifacts.risk_moderator_summary}")
    print("\n--- Proposed trade plan (draft, pre risk-clamp) ---")
    print(
        f"{plan.action.value.upper()} {plan.symbol} @ {plan.entry_price:.2f} | "
        f"target {plan.target_price:.2f} | stop {plan.stop_loss_price:.2f} | "
        f"tranches {plan.tranche_sizes}"
    )
    print("\n--- Risk-clamped verdict (hard limits enforced in code) ---")
    print(f"approved={decision.risk_verdict.approved} status={decision.status}")
    print(
        f"leverage={decision.risk_verdict.adjusted_leverage}x "
        f"position_pct_of_equity={decision.risk_verdict.adjusted_position_pct_of_equity:.1%}"
    )
    if decision.risk_verdict.violations_corrected:
        print("corrections:")
        for v in decision.risk_verdict.violations_corrected:
            print(f"  - {v}")
    if decision.blocked_reason:
        print(f"BLOCKED: {decision.blocked_reason}")
    print("=" * 60)


def _run_signal(args) -> int:
    config = _build_config(args)
    llm = build_llm_client(config)
    provider = build_market_data_provider(config)
    broker = PaperBroker(cash_equity=config.starting_paper_equity)
    breaker = DailyCircuitBreaker(
        starting_equity=config.starting_paper_equity,
        limit_pct=config.risk.daily_loss_circuit_breaker_pct,
    )
    cycle = TradingCycle(
        config, llm, provider, requested_leverage=args.leverage, requested_tranches=args.tranches
    )

    try:
        artifacts = cycle.run_cycle(args.symbol, account_equity=broker.equity({}), circuit_breaker=breaker)
    except RuntimeError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    _print_decision(artifacts)

    if artifacts.decision.status == "pending_approval":
        broker.execute(artifacts.decision)
        record_execution(artifacts, broker, TradeJournal(config.journal_path), cycle.reflection_memory)
        print("Booked into paper broker (simulation only — no real order was placed).")
        print(f"Journaled to {config.journal_path}")
    return 0


def _decision_summary(symbol: str, result: TickResult) -> dict:
    decision = result.artifacts.decision
    plan = decision.trade_plan
    return {
        "ts": time.time(),
        "action": plan.action.value,
        "entry_price": plan.entry_price,
        "leverage": decision.risk_verdict.adjusted_leverage,
        "status": decision.status,
        "booked": result.booked,
        "stopped_out": result.stopped_out,
    }


def _positions_as_dict(broker: PaperBroker) -> dict:
    return {
        sym: {
            "quantity": pos.quantity,
            "avg_entry_price": pos.avg_entry_price,
            "leverage": pos.leverage,
            "stop_loss_price": pos.stop_loss_price,
        }
        for sym, pos in broker.positions.items()
    }


def _run_watch(args) -> int:
    config = _build_config(args)
    llm = build_llm_client(config)
    provider = build_market_data_provider(config)
    broker = PaperBroker(cash_equity=config.starting_paper_equity)
    breaker = DailyCircuitBreaker(
        starting_equity=config.starting_paper_equity,
        limit_pct=config.risk.daily_loss_circuit_breaker_pct,
    )
    cycle = TradingCycle(
        config, llm, provider, requested_leverage=args.leverage, requested_tranches=args.tranches
    )

    print("=" * 60)
    print("DISCLAIMER: paper trading only. No system can guarantee profit —")
    print("this loop can lose simulated money just as easily as make it.")
    print("Every decision that clears risk checks books immediately, every tick.")
    print("=" * 60)

    dashboard_server = None
    dashboard_state = None
    if args.dashboard:
        dashboard_state = DashboardState()
        dashboard_server = start_dashboard_server(dashboard_state, port=args.dashboard_port)
        print(f"Dashboard: http://127.0.0.1:{args.dashboard_port}")

    journal = TradeJournal(config.journal_path)

    def on_tick(i: int, result: TickResult) -> None:
        plan = result.artifacts.decision.trade_plan
        print(
            f"\n[tick {i} | {time.strftime('%H:%M:%S')}] {plan.action.value.upper()} {plan.symbol} "
            f"@ {plan.entry_price:.2f} | status={result.artifacts.decision.status} "
            f"leverage={result.artifacts.decision.risk_verdict.adjusted_leverage}x"
        )
        if result.stopped_out:
            print(f"  stopped out: {result.stopped_out}")
        if result.booked:
            print("  -> booked")
            record_execution(result.artifacts, broker, journal, cycle.reflection_memory)
        print(f"  paper equity={result.equity:,.0f}  realized_pnl={broker.realized_pnl:,.0f}")

        if dashboard_state is not None:
            dashboard_state.record_tick(
                symbol=args.symbol,
                equity=result.equity,
                decision_summary=_decision_summary(args.symbol, result),
                positions=_positions_as_dict(broker),
                realized_pnl=broker.realized_pnl,
            )

    try:
        run_loop(
            cycle,
            broker,
            args.symbol,
            breaker,
            args.interval,
            args.max_iterations,
            on_tick,
        )
    except RuntimeError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n중단했습니다 (Ctrl+C). 최종 상태:")
        print(
            f"paper equity={broker.equity({}):,.0f}  realized_pnl={broker.realized_pnl:,.0f}  "
            f"open positions={list(broker.positions)}"
        )
    finally:
        if dashboard_server is not None:
            dashboard_server.shutdown()
    return 0


def _run_backtest(args) -> int:
    config = _build_config(args)
    llm = build_llm_client(config)

    if args.live:
        from trading_agent.data.yfinance_provider import YFinanceFeed

        try:
            full_snapshot = YFinanceFeed(
                period=config.live_data.period,
                interval=config.live_data.interval,
                start=args.start,
                end=args.end,
            ).get_snapshot(args.symbol)
        except RuntimeError as exc:
            print(f"오류: {exc}", file=sys.stderr)
            return 1
    else:
        full_snapshot = SimulatedFeed(n_bars=max(200, args.min_lookback + 50)).get_snapshot(args.symbol)

    if len(full_snapshot.bars) <= args.min_lookback:
        print(
            f"오류: 데이터가 {len(full_snapshot.bars)}개 봉밖에 없어 "
            f"--min-lookback({args.min_lookback})을 채울 수 없습니다. --period를 늘려보세요.",
            file=sys.stderr,
        )
        return 1

    replay = ReplayFeed(full_snapshot, min_lookback=args.min_lookback)
    broker = PaperBroker(cash_equity=config.starting_paper_equity)
    breaker = DailyCircuitBreaker(
        starting_equity=config.starting_paper_equity,
        limit_pct=config.risk.daily_loss_circuit_breaker_pct,
    )
    cycle = TradingCycle(
        config, llm, replay, requested_leverage=args.leverage, requested_tranches=args.tranches
    )

    journal = TradeJournal(config.journal_path)

    def on_tick(index, snapshot, artifacts, equity) -> None:
        if artifacts.decision.status == "pending_approval":
            record_execution(artifacts, broker, journal, cycle.reflection_memory)

    print(f"백테스트 실행 중: {args.symbol} ({len(full_snapshot.bars)}개 봉, 워밍업 {args.min_lookback}봉)...")
    result = run_backtest(cycle, replay, broker, args.symbol, breaker, on_tick=on_tick)

    p = result.performance
    print("=" * 60)
    print(f"BACKTEST REPORT — {args.symbol}  ({result.num_ticks} ticks)")
    print("과거 데이터를 재생한 결과입니다. 미래 수익을 보장하지 않습니다.")
    print("=" * 60)
    print(f"시작 자산      : {p.starting_equity:,.0f}")
    print(f"종료 자산      : {p.ending_equity:,.0f}")
    print(f"총 수익률      : {p.total_return_pct:+.2%}")
    print(f"최대 낙폭(MDD) : {p.max_drawdown_pct:.2%}")
    print(f"청산된 거래 수 : {p.num_closed_trades}")
    if p.win_rate is not None:
        print(f"승률           : {p.win_rate:.1%}")
    if p.sharpe_ratio is not None:
        print(f"Sharpe-like    : {p.sharpe_ratio:.2f}  (per-tick, 무위험수익률=0 가정, 연율화 아님)")
    if p.sortino_ratio is not None:
        print(f"Sortino-like   : {p.sortino_ratio:.2f}  (per-tick, 무위험수익률=0 가정, 연율화 아님)")
    print("=" * 60)
    return 0


def _run_daily_picks(args) -> int:
    import datetime as dt

    config = _build_config(args)
    llm = build_llm_client(config)
    provider = build_market_data_provider(config)
    macro_provider = build_macro_provider(config)
    forecaster = build_price_forecaster(config)

    if args.live:
        # build_market_data_provider() falls back to SimulatedFeed if
        # yfinance failed to import (see data/factory.py) — reasonable for
        # the general-purpose signal/watch/backtest commands, but a report
        # published as "live" must never actually be simulated prices. Fail
        # loudly here instead of silently producing a fake-data report.
        from trading_agent.data.yfinance_provider import YFinanceFeed

        if not isinstance(provider, YFinanceFeed):
            print(
                "[trading_agent] --live was requested but the live market-data provider could not "
                "be built (yfinance missing or failed to import) — refusing to produce a report "
                "against simulated prices under a --live run. Fix the yfinance install and retry; "
                "no report was written.",
                file=sys.stderr,
            )
            return 1

    real_out_dir = "research_team/reports"
    out_dir = args.out_dir
    state_path = args.state_path
    if args.live:
        out_dir = out_dir or real_out_dir
        state_path = state_path or DEFAULT_STATE_PATH
    else:
        # Every real pick must be priced with live data, so a run without
        # --live never silently lands in the tracked report/state files —
        # it's redirected to a clearly-separate dry-run path instead, and
        # refused outright if the caller explicitly pointed at the real one.
        if out_dir is None:
            out_dir = f"{real_out_dir}/_dry_run"
        elif out_dir == real_out_dir:
            print(
                f"[trading_agent] refusing to write dry-run (non --live) output into {real_out_dir!r}: "
                "every real pick must be priced with live data. Pass --live, or point --out-dir "
                "somewhere other than the tracked report directory.",
                file=sys.stderr,
            )
            return 1
        if state_path is None:
            state_path = "research_team/state/_dry_run_portfolio.json"
        elif state_path == DEFAULT_STATE_PATH:
            print(
                f"[trading_agent] refusing to write dry-run (non --live) state into {DEFAULT_STATE_PATH!r}: "
                "every real pick must be priced with live data. Pass --live, or point --state-path "
                "somewhere other than the tracked state file.",
                file=sys.stderr,
            )
            return 1

    state = load_state(state_path)
    run_date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    # Live runs fire multiple times per trading day, so the report filename
    # carries a timestamp (not just the date) to avoid one run overwriting
    # another's report; dry runs keep the plain date-only name unchanged.
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d_%H%MZ") if args.live else run_date.isoformat()

    print("=" * 60)
    print("DISCLAIMER: research/education tool output, not investment advice.")
    print(f"Equity research committee — {run_id}")
    print("=" * 60)

    report = run_daily_cycle(config, llm, provider, macro_provider, forecaster, state, run_date=run_date)
    save_state(state, state_path)
    # Live runs keep the traditional top-level research_team/LATEST_PICKS.md;
    # dry runs stay fully contained inside out_dir (see write_report's docstring).
    latest_path = "research_team/LATEST_PICKS.md" if args.live else None
    md_path, json_path = write_report(report, out_dir, latest_path=latest_path, run_id=run_id)

    print(report.okr_summary)
    print(f"\nEntries today: {[p.symbol for p in report.entries]}")
    print(f"Exits today  : {[p.symbol for p in report.exits]}")
    print(f"Open basket  : {[p.symbol for p in report.open_positions]}")
    print(f"\nWrote {md_path}\nWrote {json_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trading_agent")
    sub = parser.add_subparsers(dest="command", required=True)

    signal_cmd = sub.add_parser("signal", help="Run one analysis cycle for a symbol.")
    _add_common_run_args(signal_cmd)

    watch_cmd = sub.add_parser(
        "watch", help="Continuously run cycles for a symbol (paper trading only)."
    )
    _add_common_run_args(watch_cmd)
    watch_cmd.add_argument("--interval", type=float, default=60.0, help="Seconds between cycles.")
    watch_cmd.add_argument(
        "--max-iterations", type=int, default=None, help="Stop after this many ticks (default: run until Ctrl+C)."
    )
    watch_cmd.add_argument("--dashboard", action="store_true", help="Serve a live local dashboard in your browser.")
    watch_cmd.add_argument("--dashboard-port", type=int, default=8787)

    backtest_cmd = sub.add_parser(
        "backtest",
        help="Replay historical bars through the pipeline bar-by-bar and report performance. "
        "Past performance does not indicate or guarantee future results.",
    )
    _add_common_run_args(backtest_cmd)
    backtest_cmd.add_argument(
        "--period",
        default="6mo",
        help="History window when --live is set (yfinance period string, e.g. 1y, 2y). "
        "Ignored if --start/--end are given, or if --live isn't set.",
    )
    backtest_cmd.add_argument(
        "--start",
        default=None,
        help="Reproduce a specific historical window: start date (e.g. 2025-01-01). "
        "Requires --live; overrides --period when set.",
    )
    backtest_cmd.add_argument(
        "--end",
        default=None,
        help="End date for --start (e.g. 2025-02-28). Requires --live.",
    )
    backtest_cmd.add_argument(
        "--min-lookback",
        type=int,
        default=35,
        help="Bars of warm-up history before the first decision (needs enough for e.g. SMA30/RSI14).",
    )

    daily_picks_cmd = sub.add_parser(
        "daily-picks",
        help="Run the daily equity research committee: screen the universe, mark the "
        "standing basket to market against SPY, and pick 2-5 names for a 2-3mo horizon.",
    )
    daily_picks_cmd.add_argument(
        "--live",
        action="store_true",
        help="Use real market data (Yahoo Finance via yfinance) instead of the simulated feed. "
        "Every real pick must be priced with live data, so without this flag the run writes to a "
        "'_dry_run' path instead of research_team/'s tracked report/state files, unless --out-dir "
        "/--state-path is given explicitly.",
    )
    daily_picks_cmd.add_argument("--period", default="6mo", help="History window when --live is set.")
    daily_picks_cmd.add_argument(
        "--kronos", action="store_true", help="Use the Kronos price-forecasting analyst if installed."
    )
    daily_picks_cmd.add_argument(
        "--out-dir",
        default=None,
        help="Directory to write the day's report into. Defaults to research_team/reports when --live "
        "is set, or research_team/reports/_dry_run otherwise — see --live's help for why.",
    )
    daily_picks_cmd.add_argument(
        "--state-path",
        default=None,
        help="Where the standing basket is persisted between runs. Same --live-dependent default as --out-dir.",
    )
    daily_picks_cmd.add_argument(
        "--date", default=None, help="Override the run date (YYYY-MM-DD); defaults to today."
    )

    args = parser.parse_args(argv)

    if args.command == "signal":
        return _run_signal(args)
    if args.command == "watch":
        return _run_watch(args)
    if args.command == "backtest":
        return _run_backtest(args)
    if args.command == "daily-picks":
        return _run_daily_picks(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
