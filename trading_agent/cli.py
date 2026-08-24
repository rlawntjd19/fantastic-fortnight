"""Command-line entrypoint.

    python -m trading_agent.cli signal SYMBOL           # show a proposed decision
    python -m trading_agent.cli signal SYMBOL --approve  # then ask to book it in paper broker

This tool never places a real order. `--approve` only affects the local,
in-memory PaperBroker ledger for this process.

Research/education tool. Not investment advice.
"""
from __future__ import annotations

import argparse
import sys

from trading_agent.config import DEFAULT_CONFIG
from trading_agent.data.providers import SimulatedFeed
from trading_agent.engine.orchestrator import TradingCycle
from trading_agent.engine.paper_broker import PaperBroker
from trading_agent.engine.risk_controls import DailyCircuitBreaker
from trading_agent.llm.client import build_llm_client


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trading_agent")
    sub = parser.add_subparsers(dest="command", required=True)

    signal_cmd = sub.add_parser("signal", help="Run one analysis cycle for a symbol.")
    signal_cmd.add_argument("symbol")
    signal_cmd.add_argument("--leverage", type=float, default=1.0)
    signal_cmd.add_argument("--tranches", type=int, default=2)
    signal_cmd.add_argument(
        "--approve",
        action="store_true",
        help="After showing the decision, ask for interactive y/n approval "
        "before booking it into the local paper broker.",
    )

    args = parser.parse_args(argv)

    if args.command == "signal":
        llm = build_llm_client(DEFAULT_CONFIG)
        provider = SimulatedFeed()
        broker = PaperBroker(cash_equity=DEFAULT_CONFIG.starting_paper_equity)
        breaker = DailyCircuitBreaker(
            starting_equity=DEFAULT_CONFIG.starting_paper_equity,
            limit_pct=DEFAULT_CONFIG.risk.daily_loss_circuit_breaker_pct,
        )
        cycle = TradingCycle(
            DEFAULT_CONFIG,
            llm,
            provider,
            requested_leverage=args.leverage,
            requested_tranches=args.tranches,
        )
        artifacts = cycle.run_cycle(
            args.symbol,
            account_equity=broker.equity({}),
            circuit_breaker=breaker,
        )
        _print_decision(artifacts)

        if args.approve and artifacts.decision.status == "pending_approval":
            answer = input("\nBook this into the paper broker? [y/N] ").strip().lower()
            if answer == "y":
                broker.execute(artifacts.decision, human_approved=True)
                print("Booked into paper broker (simulation only).")
            else:
                print("Not booked.")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
