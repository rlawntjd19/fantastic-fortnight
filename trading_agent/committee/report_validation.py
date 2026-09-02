"""Internal-consistency sanity checks on a `CommitteeReport`, run before it's
written to disk or turned into a dashboard artifact.

This is deliberately narrow: it does not (and cannot) verify the underlying
market data is real — that's `cli._run_daily_picks`'s hard --live guard.
What it catches is the report contradicting its own numbers: weights that
don't sum to 1, an alpha figure that doesn't match the position/benchmark
returns it was computed from, an OKR summary string that states a different
average than the scoreboard it was built from — the kind of bug a human
skimming a table of numbers would miss but arithmetic won't.
"""
from __future__ import annotations

import re

from trading_agent.committee.schemas import CommitteeReport

_WEIGHT_SUM_TOLERANCE = 0.01  # scoreboard weights should sum to 1.0 +/- 1pp
_ALPHA_MATH_TOLERANCE = 0.0005  # 0.05pp, matches okr_summary's 2-decimal-pp formatting
_ALLOCATED_VALUE_TOLERANCE = 1.0  # $1, covers whole-share rounding


def validate_report(report: CommitteeReport) -> list[str]:
    """Returns a list of human-readable problems found; empty means the
    report is internally consistent (not a guarantee it's *correct* — a
    consistent report can still be built on bad inputs)."""
    problems: list[str] = []

    open_symbols = [p.symbol for p in report.open_positions]
    if len(open_symbols) != len(set(open_symbols)):
        problems.append(f"Duplicate symbol(s) in open_positions: {open_symbols}")

    exit_symbols = {p.symbol for p in report.exits}
    still_open_overlap = exit_symbols & set(open_symbols)
    if still_open_overlap:
        problems.append(f"Symbol(s) both exited and still listed open this run: {sorted(still_open_overlap)}")

    weight_total = 0.0
    for row in report.scoreboard:
        symbol = row.get("symbol")
        if symbol not in open_symbols:
            problems.append(f"Scoreboard row for {symbol!r} has no matching open position")

        position_return = row.get("position_return_pct")
        benchmark_return = row.get("benchmark_return_pct")
        alpha = row.get("alpha_pct")
        if None not in (position_return, benchmark_return, alpha):
            expected_alpha = position_return - benchmark_return
            if abs(expected_alpha - alpha) > _ALPHA_MATH_TOLERANCE:
                problems.append(
                    f"{symbol}: reported alpha_pct={alpha:.4f} doesn't match "
                    f"position_return-benchmark_return={expected_alpha:.4f}"
                )

        weight = row.get("weight_pct")
        if weight is not None:
            if weight < 0:
                problems.append(f"{symbol}: negative weight_pct={weight}")
            weight_total += weight

        current_price = row.get("current_price")
        if current_price is not None and current_price <= 0:
            problems.append(f"{symbol}: non-positive current_price={current_price}")

        shares = row.get("shares")
        allocated_value = row.get("allocated_value")
        if None not in (shares, current_price, allocated_value):
            expected_value = shares * current_price
            if abs(expected_value - allocated_value) > _ALLOCATED_VALUE_TOLERANCE:
                problems.append(
                    f"{symbol}: allocated_value={allocated_value:.2f} doesn't match "
                    f"shares*current_price={expected_value:.2f}"
                )

    if report.scoreboard and abs(weight_total - 1.0) > _WEIGHT_SUM_TOLERANCE:
        problems.append(f"Scoreboard weights sum to {weight_total:.4f}, expected ~1.0")

    if report.scoreboard:
        match = re.search(r"across \d+ open position\(s\): ([+-]?\d+\.\d+)pp", report.okr_summary)
        if match:
            stated_avg = float(match.group(1)) / 100
            actual_avg = sum(r["alpha_pct"] for r in report.scoreboard) / len(report.scoreboard)
            if abs(stated_avg - actual_avg) > _ALPHA_MATH_TOLERANCE:
                problems.append(
                    f"okr_summary states avg alpha {stated_avg * 100:+.2f}pp but the scoreboard "
                    f"itself computes {actual_avg * 100:+.2f}pp"
                )

    return problems
