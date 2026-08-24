"""Command-line entrypoint.

    python -m trading_agent.cli signal SYMBOL            # show a proposed decision, once
    python -m trading_agent.cli signal SYMBOL --approve   # then ask to book it in paper broker
    python -m trading_agent.cli watch SYMBOL --auto-approve --dashboard
        # run cycles continuously on an interval, auto-booking decisions
        # that clear risk checks into the paper broker, with a local
        # browser dashboard to watch equity/positions/decisions live.

This tool never places a real order — `--approve` and `--auto-approve`
only ever affect the local, in-memory PaperBroker ledger for this
process. Nothing here promises or can guarantee profit.

Research/education tool. Not investment advice.
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
import time

from trading_agent.config import DEFAULT_CONFIG
from trading_agent.dashboard import DashboardState, start_dashboard_server
from trading_agent.data.factory import build_market_data_provider
from trading_agent.data.providers import SimulatedFeed
from trading_agent.engine.backtest import ReplayFeed, run_backtest
from trading_agent.engine.live_runner import TickResult, run_loop
from trading_agent.engine.orchestrator import TradingCycle
from trading_agent.engine.paper_broker import PaperBroker
from trading_agent.engine.risk_controls import DailyCircuitBreaker
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

    if args.approve and artifacts.decision.status == "pending_approval":
        answer = input("\nBook this into the paper broker? [y/N] ").strip().lower()
        if answer == "y":
            broker.execute(artifacts.decision, human_approved=True)
            print("Booked into paper broker (simulation only).")
        else:
            print("Not booked.")
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
    print("=" * 60)
    if not args.auto_approve:
        print("(--auto-approve is off: this will only preview decisions, nothing is booked.)")

    dashboard_server = None
    dashboard_state = None
    if args.dashboard:
        dashboard_state = DashboardState()
        dashboard_server = start_dashboard_server(dashboard_state, port=args.dashboard_port)
        print(f"Dashboard: http://127.0.0.1:{args.dashboard_port}")

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
            print("  -> booked automatically (--auto-approve)")
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
            args.auto_approve,
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
                period=config.live_data.period, interval=config.live_data.interval
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

    print(f"백테스트 실행 중: {args.symbol} ({len(full_snapshot.bars)}개 봉, 워밍업 {args.min_lookback}봉)...")
    result = run_backtest(cycle, replay, broker, args.symbol, breaker)

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trading_agent")
    sub = parser.add_subparsers(dest="command", required=True)

    signal_cmd = sub.add_parser("signal", help="Run one analysis cycle for a symbol.")
    _add_common_run_args(signal_cmd)
    signal_cmd.add_argument(
        "--approve",
        action="store_true",
        help="After showing the decision, ask for interactive y/n approval "
        "before booking it into the local paper broker.",
    )

    watch_cmd = sub.add_parser(
        "watch", help="Continuously run cycles for a symbol (paper trading only)."
    )
    _add_common_run_args(watch_cmd)
    watch_cmd.add_argument("--interval", type=float, default=60.0, help="Seconds between cycles.")
    watch_cmd.add_argument(
        "--max-iterations", type=int, default=None, help="Stop after this many ticks (default: run until Ctrl+C)."
    )
    watch_cmd.add_argument(
        "--auto-approve",
        action="store_true",
        help="Book every decision that clears risk checks into the paper broker "
        "automatically, with no per-tick prompt. Paper broker only, never a "
        "real order — this flag is the one explicit opt-in for that, made "
        "once when you start the loop.",
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
        help="History window when --live is set (yfinance period string, e.g. 1y, 2y). Ignored otherwise.",
    )
    backtest_cmd.add_argument(
        "--min-lookback",
        type=int,
        default=35,
        help="Bars of warm-up history before the first decision (needs enough for e.g. SMA30/RSI14).",
    )

    args = parser.parse_args(argv)

    if args.command == "signal":
        return _run_signal(args)
    if args.command == "watch":
        return _run_watch(args)
    if args.command == "backtest":
        return _run_backtest(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
