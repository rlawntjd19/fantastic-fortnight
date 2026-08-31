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

from trading_agent.config import DEFAULT_CONFIG
from trading_agent.dashboard import DashboardState, start_dashboard_server
from trading_agent.data.factory import build_market_data_provider
from trading_agent.data.providers import SimulatedFeed
from trading_agent.engine.backtest import ReplayFeed, run_backtest
from trading_agent.engine.journal import TradeJournal, record_execution
from trading_agent.engine.live_runner import TickResult, run_loop
from trading_agent.engine.orchestrator import TradingCycle
from trading_agent.engine.paper_broker import PaperBroker
from trading_agent.engine.risk_controls import DailyCircuitBreaker
from trading_agent.llm.client import build_llm_client
from trading_agent.portfolio.dashboard import PortfolioDashboardState
from trading_agent.portfolio.dashboard import start_dashboard_server as start_portfolio_dashboard_server
from trading_agent.portfolio.pipeline import run_portfolio_research
from trading_agent.portfolio.report import render_markdown_report
from trading_agent.portfolio.watch import PortfolioWatcher
from trading_agent.portfolio.watch import run_loop as run_portfolio_watch_loop


def _build_config(args):
    config = DEFAULT_CONFIG
    if getattr(args, "kronos", False):
        config = dataclasses.replace(config, kronos=dataclasses.replace(config.kronos, enabled=True))
    if getattr(args, "live", False):
        live_data = dataclasses.replace(config.live_data, enabled=True)
        if getattr(args, "period", None):
            live_data = dataclasses.replace(live_data, period=args.period)
        if getattr(args, "data_provider", None):
            live_data = dataclasses.replace(live_data, provider=args.data_provider)
        config = dataclasses.replace(config, live_data=live_data)
    return config


def _add_common_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("symbol", help="For --live, a real ticker (e.g. 000660.KS, AAPL).")
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
        help="Use real market data instead of the simulated feed (backend picked by "
        "--data-provider). Requires `pip install -r requirements-live.txt` for the "
        "yfinance backend. A failed fetch (bad ticker, no network) is a hard error "
        "here, never a silent fallback to fake data.",
    )
    parser.add_argument(
        "--data-provider",
        choices=["yfinance", "alphavantage"],
        default="yfinance",
        help="Live data backend for --live. 'yfinance' (default, Yahoo Finance) or "
        "'alphavantage' (needs ALPHAVANTAGE_API_KEY; useful when yfinance's TLS "
        "fingerprinting doesn't survive a network's TLS-intercepting proxy).",
    )


def _add_portfolio_research_args(parser: argparse.ArgumentParser) -> None:
    """Shared by `portfolio` and `portfolio-watch` — the args that drive the
    one-shot screen/selection/allocation pass both commands start from."""
    parser.add_argument("--budget", type=float, default=25_000.0, help="Total cash to allocate.")
    parser.add_argument("--min-stocks", type=int, default=2)
    parser.add_argument("--max-stocks", type=int, default=5)
    parser.add_argument("--risk-free-rate", type=float, default=0.045, help="Annual, e.g. 0.045 = 4.5%%.")
    parser.add_argument("--market-risk-premium", type=float, default=0.05, help="Annual equity risk premium.")
    parser.add_argument("--weight-cap", type=float, default=0.60, help="Max weight for any single name.")
    parser.add_argument("--min-weight", type=float, default=0.05, help="Min weight for each selected name.")
    parser.add_argument("--optimizer-steps", type=int, default=25, help="Weight-grid resolution (1/steps).")
    parser.add_argument("--forward-paths", type=int, default=2000, help="Monte Carlo path count.")
    parser.add_argument("--min-lookback", type=int, default=260, help="Offline-mode history length (bars).")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use real market data instead of the simulated feed (backend picked by --data-provider).",
    )
    parser.add_argument(
        "--data-provider",
        choices=["yfinance", "alphavantage"],
        default="yfinance",
        help="Live data backend for --live. 'yfinance' (default, Yahoo Finance) or "
        "'alphavantage' (needs ALPHAVANTAGE_API_KEY; useful when yfinance's TLS "
        "fingerprinting doesn't survive a network's TLS-intercepting proxy). Alpha "
        "Vantage's free tier has a tight request quota — expect slow, throttled "
        "screening across this command's ~19-name universe.",
    )
    parser.add_argument(
        "--period",
        default="1y",
        help="History window when --live is set with --data-provider yfinance. Ignored "
        "for alphavantage, which always fetches full daily history.",
    )
    parser.add_argument("--kronos", action="store_true", help="Use the Kronos forecaster if available.")


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
        try:
            if config.live_data.provider == "alphavantage":
                from trading_agent.data.alphavantage_provider import AlphaVantageFeed

                av = config.alphavantage
                full_snapshot = AlphaVantageFeed(
                    api_key=av.api_key,
                    requests_per_minute=av.requests_per_minute,
                    include_fundamentals=av.include_fundamentals,
                    include_news=av.include_news,
                    include_realtime_quote=av.include_realtime_quote,
                ).get_snapshot(args.symbol)
                if args.start or args.end:
                    # Alpha Vantage has no start/end window param — filter the
                    # already-fetched full history client-side instead.
                    import datetime as _dt

                    lo = _dt.datetime.strptime(args.start, "%Y-%m-%d").timestamp() if args.start else float("-inf")
                    hi = _dt.datetime.strptime(args.end, "%Y-%m-%d").timestamp() if args.end else float("inf")
                    full_snapshot = dataclasses.replace(
                        full_snapshot, bars=[b for b in full_snapshot.bars if lo <= b.timestamp <= hi]
                    )
            else:
                from trading_agent.data.yfinance_provider import YFinanceFeed

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


def _build_portfolio_config_and_provider(args):
    """Shared by `portfolio` and `portfolio-watch`: builds the Config and
    the market-data provider used for the one-shot screen/selection/
    allocation pass both commands start from."""
    config = DEFAULT_CONFIG
    if args.kronos:
        config = dataclasses.replace(config, kronos=dataclasses.replace(config.kronos, enabled=True))

    if args.live:
        # Also flips config.live_data.enabled on, which build_macro_provider()
        # (called inside run_portfolio_research) reads too — without this,
        # --live only made the price feed real and macro stayed static.
        config = dataclasses.replace(
            config,
            live_data=dataclasses.replace(
                config.live_data, enabled=True, provider=args.data_provider, period=args.period
            ),
        )
        provider = build_market_data_provider(config)
        data_source = "live"
    else:
        # More history than the single-symbol commands' default (120 bars):
        # mean-variance optimization and the trailing backtest both want a
        # full-year-ish window, not just enough for a warm-up indicator.
        provider = SimulatedFeed(n_bars=max(260, args.min_lookback))
        data_source = "simulated"

    return config, provider, data_source


def _run_portfolio_research(args):
    """Shared by `portfolio` and `portfolio-watch`: runs the one-shot
    screen/selection/allocation/backtest/forward-simulation pass."""
    import datetime

    config, provider, data_source = _build_portfolio_config_and_provider(args)
    llm = build_llm_client(config)

    report = run_portfolio_research(
        config,
        llm,
        provider,
        budget=args.budget,
        min_stocks=args.min_stocks,
        max_stocks=args.max_stocks,
        risk_free_rate=args.risk_free_rate,
        market_risk_premium=args.market_risk_premium,
        weight_cap=args.weight_cap,
        min_weight=args.min_weight,
        optimizer_steps=args.optimizer_steps,
        forward_paths=args.forward_paths,
        as_of=datetime.date.today().isoformat(),
        data_source=data_source,
    )
    return report, data_source, provider


def _run_portfolio(args) -> int:
    try:
        report, _data_source, _provider = _run_portfolio_research(args)
    except RuntimeError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    memo = render_markdown_report(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(memo)
        print(f"Wrote {args.out}")
        print(f"Selected: {', '.join(c.symbol for c in report.selected)}")
    else:
        print(memo)
    return 0


def _build_watch_price_provider(args, screening_provider):
    """A lighter-weight provider for portfolio-watch's per-tick refresh:
    only `last_price` is read each tick, so there's no reason to re-fetch
    a full year of history or fundamentals/news on every single tick the
    way the initial screen needs to. Offline, the screening provider
    itself is reused so `SimulatedFeed`'s per-symbol walk keeps advancing
    tick to tick instead of resetting."""
    if not args.live:
        return screening_provider

    if args.data_provider == "alphavantage":
        from trading_agent.data.alphavantage_provider import AlphaVantageFeed

        av = DEFAULT_CONFIG.alphavantage
        return AlphaVantageFeed(
            api_key=av.api_key,
            requests_per_minute=av.requests_per_minute,
            include_fundamentals=False,
            include_news=False,
            include_realtime_quote=True,
        )

    from trading_agent.data.yfinance_provider import YFinanceFeed

    return YFinanceFeed(period="5d", interval="1d")


def _run_portfolio_watch(args) -> int:
    try:
        report, data_source, screening_provider = _run_portfolio_research(args)
    except RuntimeError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    print("=" * 60)
    print("DISCLAIMER: read-only price tracking. No trades are placed by this command.")
    print(f"Selected: {', '.join(c.symbol for c in report.selected)}")
    print(f"Budget: ${report.budget:,.2f}  |  Data source: {data_source}")
    print("=" * 60)

    watch_provider = _build_watch_price_provider(args, screening_provider)
    watcher = PortfolioWatcher(report.allocation, report.leftover_cash, watch_provider)

    dashboard_server = None
    dashboard_state = None
    if args.dashboard:
        dashboard_state = PortfolioDashboardState(
            data_source=data_source,
            budget=report.budget,
            benchmark_symbol=report.benchmark_symbol,
            selection_summary=[
                {
                    "symbol": c.symbol,
                    "sector": c.sector,
                    "composite_score": c.composite_score,
                    "signal": c.debate.consensus_signal.value,
                }
                for c in report.selected
            ],
        )
        dashboard_server = start_portfolio_dashboard_server(dashboard_state, port=args.dashboard_port)
        print(f"Dashboard: http://127.0.0.1:{args.dashboard_port}")

    def on_tick(i, tick) -> None:
        print(
            f"\n[tick {i} | {time.strftime('%H:%M:%S')}] value=${tick.total_value:,.2f} "
            f"pnl={tick.total_pnl_dollars:+,.2f} ({tick.total_pnl_pct:+.2%})"
        )
        if tick.errors:
            print(f"  fetch errors (showing last-known price instead): {', '.join(tick.errors)}")
        if dashboard_state is not None:
            dashboard_state.record_tick(tick)

    try:
        run_portfolio_watch_loop(watcher, args.interval, args.max_iterations, on_tick)
    except KeyboardInterrupt:
        print("\nStopped (Ctrl+C).")
    finally:
        if dashboard_server is not None:
            dashboard_server.shutdown()
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

    portfolio_cmd = sub.add_parser(
        "portfolio",
        help="Run the multi-agent research workflow to build a 2-5 stock, long-only "
        "US-equity portfolio from a fixed cash budget, with MPT-based sizing, a "
        "trailing backtest, and a 3-month forward Monte Carlo projection.",
    )
    _add_portfolio_research_args(portfolio_cmd)
    portfolio_cmd.add_argument("--out", default=None, help="Write the full Markdown memo to this path instead of stdout.")

    portfolio_watch_cmd = sub.add_parser(
        "portfolio-watch",
        help="Run the same selection/allocation as `portfolio` once, then continuously "
        "re-price the resulting positions and serve a live local dashboard. Read-only: "
        "this never re-screens, re-optimizes, or places any order.",
    )
    _add_portfolio_research_args(portfolio_watch_cmd)
    portfolio_watch_cmd.add_argument("--interval", type=float, default=60.0, help="Seconds between price refreshes.")
    portfolio_watch_cmd.add_argument(
        "--max-iterations", type=int, default=None, help="Stop after this many ticks (default: run until Ctrl+C)."
    )
    portfolio_watch_cmd.add_argument("--dashboard", action="store_true", help="Serve a live local dashboard in your browser.")
    portfolio_watch_cmd.add_argument("--dashboard-port", type=int, default=8788)

    args = parser.parse_args(argv)

    if args.command == "signal":
        return _run_signal(args)
    if args.command == "watch":
        return _run_watch(args)
    if args.command == "backtest":
        return _run_backtest(args)
    if args.command == "portfolio":
        return _run_portfolio(args)
    if args.command == "portfolio-watch":
        return _run_portfolio_watch(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
