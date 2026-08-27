"""Renders a `PortfolioReport` as a Markdown investment-committee memo."""
from __future__ import annotations

from trading_agent.portfolio.schemas import PortfolioReport


def _pct(x: float | None, plus: bool = False) -> str:
    if x is None:
        return "n/a"
    fmt = "{:+.2%}" if plus else "{:.2%}"
    return fmt.format(x)


def _num(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def render_markdown_report(report: PortfolioReport) -> str:
    lines: list[str] = []
    w = lines.append

    w("# Investment Committee Memo — Long-Only US Equity Portfolio")
    w("")
    w("**Research/education tool output. Not investment advice.**")
    w("")
    w(f"- As of: {report.as_of}")
    w(f"- Data source: {'live market data (Yahoo Finance)' if report.data_source == 'live' else 'offline simulated feed (demo mode — see caveat below)'}")
    w(f"- Budget: ${report.budget:,.2f}")
    w(f"- Assumptions: risk-free rate {report.risk_free_rate:.2%}, equity market risk premium {report.market_risk_premium:.2%}")
    w("")

    n_names = len(report.universe)
    n_sectors = len({c.sector for c in report.universe})
    w("## 1. Workflow")
    w("")
    w("```")
    w(f"Universe ({n_names} names, {n_sectors} sectors incl. ETFs)")
    w("   |")
    w("   v")
    w("Screening Desk: Technical / Fundamental / Sentiment / Macro / Forecast analysts")
    w("   |            -> Research Manager bull/bear debate -> composite score per stock")
    w("   v")
    w("Portfolio Manager: iterative diversified selection (2-5 stocks)   [selection.py]")
    w("   v")
    w("Quant Desk: CAPM expected returns + historical covariance          [optimizer.py]")
    w("            -> long-only max-Sharpe grid search")
    w("   v")
    w("Trading Desk: whole-share allocation of the cash budget          [allocation.py]")
    w("   v")
    w("Risk Desk: trailing-history backtest + 3-month Monte Carlo      [backtest.py,")
    w("           forward projection                              forward_simulation.py]")
    w("```")
    w("")

    w("## 2. Universe screened")
    w("")
    w("| Symbol | Sector | Composite score | Consensus | Confidence |")
    w("|---|---|---:|---|---:|")
    for c in sorted(report.universe, key=lambda c: c.composite_score, reverse=True):
        w(f"| {c.symbol} | {c.sector} | {c.composite_score:+.2f} | {c.debate.consensus_signal.value} | {c.debate.consensus_confidence:.2f} |")
    w("")

    w("## 3. Selection trace (Portfolio Manager)")
    w("")
    for r in report.selection_rounds:
        w(f"- {r.notes}")
    w("")

    w("## 4. Selected portfolio & rationale")
    w("")
    for c in report.selected:
        w(f"### {c.symbol} ({c.sector})")
        w(f"- Composite score: {c.composite_score:+.2f} | Consensus: **{c.debate.consensus_signal.value}** (confidence {c.debate.consensus_confidence:.2f})")
        for rpt in c.reports:
            w(f"  - *{rpt.agent_name}* ({rpt.signal.value}, conf {rpt.confidence:.2f}): {rpt.summary}")
        w(f"- Bull case: {c.debate.bull_thesis}")
        w(f"- Bear case: {c.debate.bear_thesis}")
        w(f"- Manager's reconciled view: {c.debate.rationale}")
        w("")

    w("## 5. Portfolio construction (Modern Portfolio Theory)")
    w("")
    w("Expected returns use CAPM (`risk_free_rate + beta * market_risk_premium`) rather than")
    w("historical sample means, which are a much noisier estimate of *future* expected return;")
    w("volatility and correlation still come from realized historical daily closes, which is")
    w("empirically the more stable half of the mean-variance inputs (a Black-Litterman-style split).")
    w("")
    w("| | Max-Sharpe (optimized) | Equal-weight (baseline) |")
    w("|---|---:|---:|")
    w(f"| Expected annual return | {_pct(report.optimized.expected_annual_return, plus=True)} | {_pct(report.equal_weight.expected_annual_return, plus=True)} |")
    w(f"| Annual volatility | {_pct(report.optimized.annual_volatility)} | {_pct(report.equal_weight.annual_volatility)} |")
    w(f"| Sharpe ratio | {_num(report.optimized.sharpe_ratio)} | {_num(report.equal_weight.sharpe_ratio)} |")
    w(f"| Portfolio beta vs {report.benchmark_symbol} | {_num(report.optimized.portfolio_beta)} | {_num(report.equal_weight.portfolio_beta)} |")
    w("")
    w("Target weights (max-Sharpe):")
    w("")
    w("| Symbol | Weight |")
    w("|---|---:|")
    for s, wt in sorted(report.optimized.weights.items(), key=lambda kv: -kv[1]):
        w(f"| {s} | {wt:.1%} |")
    w("")
    w("> Note on Treynor ratio: under CAPM, a portfolio's *expected* Treynor ratio")
    w("> `(E[r] - rf) / beta` collapses to exactly the market risk premium for every")
    w("> beta — it can't discriminate between CAPM-priced portfolios by construction.")
    w("> That's why Sharpe (which reflects diversification/total risk, not just")
    w("> systematic risk) drives the optimization; the *realized* Treynor ratio from")
    w("> the historical backtest below is the more informative Treynor number here.")
    w("")

    w("## 6. Capital allocation")
    w("")
    w(f"Budget: ${report.budget:,.2f}")
    w("")
    w("| Symbol | Target weight | Price | Shares | Dollars | Actual weight |")
    w("|---|---:|---:|---:|---:|---:|")
    for a in report.allocation:
        w(f"| {a.symbol} | {a.target_weight:.1%} | ${a.price:,.2f} | {a.shares} | ${a.dollars:,.2f} | {a.actual_weight:.1%} |")
    w(f"| **Cash (unallocated)** | | | | ${report.leftover_cash:,.2f} | {(report.leftover_cash / report.budget if report.budget else 0):.1%} |")
    w("")

    b = report.backtest
    w("## 7. Historical backtest (trailing window, fixed weights, monthly rebalance)")
    w("")
    w("Replays already-realized history under the optimized weights above.")
    w("**Past performance does not indicate or guarantee future results.**")
    w("")
    w(f"- Window: {b.num_bars} trading days")
    w(f"- Starting / ending value: ${b.starting_equity:,.2f} -> ${b.ending_equity:,.2f}")
    w(f"- Total return: {_pct(b.total_return_pct, plus=True)}")
    w(f"- Annualized return: {_pct(b.annualized_return_pct, plus=True)}")
    w(f"- Annualized volatility: {_pct(b.annualized_vol_pct)}")
    w(f"- Max drawdown: {_pct(b.max_drawdown_pct)}")
    w(f"- Realized Sharpe ratio: {_num(b.sharpe_ratio)}")
    w(f"- Realized beta vs {report.benchmark_symbol}: {_num(b.realized_beta)}")
    w(f"- Realized Treynor ratio: {_num(b.treynor_ratio)}")
    w("")

    f = report.forward_simulation
    w("## 8. Forward-looking 3-month projection (Monte Carlo)")
    w("")
    w(f"{f.num_paths:,} simulated paths over {f.horizon_days} trading days (~3 months),")
    w("correlated per-asset shocks from historical covariance, CAPM-implied drift.")
    w("**This is a probabilistic projection, not a forecast or a guarantee.**")
    w("")
    w(f"- Expected return: {_pct(f.expected_return_pct, plus=True)} (median {_pct(f.median_return_pct, plus=True)})")
    w(f"- 5th-95th percentile range: {_pct(f.p5_return_pct, plus=True)} to {_pct(f.p95_return_pct, plus=True)}")
    w(f"- Probability of a positive 3-month return: {f.prob_positive:.1%}")
    w(f"- Expected ending value: ${f.expected_ending_value:,.2f} (from ${f.starting_value:,.2f})")
    w("")

    w("## 9. Caveats")
    w("")
    if report.data_source != "live":
        w("- **This run used the offline simulated feed, not real market data** — prices,")
        w("  fundamentals and history here are a deterministic demo walk, not today's actual")
        w("  market. Re-run with `--live` (needs `pip install -r requirements-live.txt` and")
        w("  network access to Yahoo Finance) for a selection grounded in real prices/fundamentals.")
        w("- **Beta/Treynor are not economically meaningful in this offline mode**: the")
        w(f"  \"{report.benchmark_symbol}\" benchmark here is *also* an independently-seeded synthetic")
        w("  random walk, uncorrelated with the selected names by construction — a near-zero beta")
        w("  (and a Treynor ratio that blows up when it's divided by that near-zero beta) is an")
        w("  artifact of the demo data, not a real risk read. Only trust these under `--live`.")
    w("- CAPM/beta/Sharpe/Treynor are standard finance heuristics, not guarantees; realized")
    w("  markets frequently violate CAPM's assumptions (normal returns, stable beta, etc).")
    w("- The Monte Carlo projection assumes returns are drawn i.i.d. from the recent historical")
    w("  covariance structure with a constant CAPM drift — it does not know about any specific")
    w("  upcoming event (earnings, Fed meetings, etc).")
    w("- Allocation assumes whole-share orders (no fractional shares); a high-priced name can")
    w("  end up under- or un-funded relative to its target weight purely from share-price")
    w("  rounding — a broker that supports fractional shares would remove this gap.")
    w("- No system can guarantee profit. This is a research/education tool.")
    w("")

    return "\n".join(lines)
