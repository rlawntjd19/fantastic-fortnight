"""Renders a `CommitteeReport` as a Markdown file and a parallel JSON dump —
Markdown for a human to read, JSON so another program (or a later committee
run) can consume the same data without re-parsing prose."""
from __future__ import annotations

import dataclasses
import json
import os

from trading_agent.committee.schemas import CommitteeReport


def to_markdown(report: CommitteeReport) -> str:
    lines: list[str] = []
    lines.append(f"# Daily Equity Research Committee — {report.run_date}")
    lines.append("")
    lines.append(
        "> Research/education tool. Not investment advice. Every score below is "
        "computed in code from analyst-desk signals; the LLM (when configured) "
        "only adds narrative on top of numbers that are already final."
    )
    lines.append("")
    lines.append("## OKR scoreboard (target: outperform SPY by 5pp+ over each 2-3mo hold)")
    lines.append("")
    lines.append(report.okr_summary)
    lines.append("")
    if report.scoreboard:
        lines.append("| Symbol | Entry | Current | Position Return | SPY Return | Alpha |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for row in report.scoreboard:
            lines.append(
                f"| {row['symbol']} | ${row['entry_price']:.2f} | ${row['current_price']:.2f} | "
                f"{row['position_return_pct'] * 100:+.2f}% | {row['benchmark_return_pct'] * 100:+.2f}% | "
                f"{row['alpha_pct'] * 100:+.2f}pp |"
            )
        lines.append("")

    lines.append("## Portfolio Manager (CIO) decision log — chain of thought")
    lines.append("")
    lines.append(report.cio_rationale)
    lines.append("")

    if report.exits:
        lines.append("## Exits today")
        lines.append("")
        for p in report.exits:
            lines.append(f"- **{p.symbol}** ({p.status}): {p.exit_reason}")
        lines.append("")

    if report.entries:
        lines.append("## New entries today")
        lines.append("")
        for pick in report.entries:
            lines.append(
                f"- **{pick.symbol}** ({pick.security_type}, {pick.sector}) — conviction: "
                f"{pick.conviction}, composite score {pick.composite_score:+.2f}, entry "
                f"${pick.entry_price:.2f}\n  - {pick.thesis}"
            )
        lines.append("")
    else:
        lines.append("## New entries today")
        lines.append("")
        lines.append("None — the existing basket was held unchanged.")
        lines.append("")

    lines.append("## Standing basket")
    lines.append("")
    if report.open_positions:
        lines.append("| Symbol | Type | Entry Date | Entry Price | Thesis |")
        lines.append("|---|---|---|---:|---|")
        for p in report.open_positions:
            lines.append(f"| {p.symbol} | {p.security_type} | {p.entry_date} | ${p.entry_price:.2f} | {p.thesis} |")
    else:
        lines.append("No open positions.")
    lines.append("")

    lines.append(f"## Screening notes ({len(report.screened_out)} excluded, universe size {report.universe_size})")
    lines.append("")
    for note in report.screened_out:
        lines.append(f"- {note}")
    lines.append("")

    lines.append("## Full analyst-desk detail per candidate screened today")
    lines.append("")
    for c in sorted(report.candidates, key=lambda x: x.composite_score, reverse=True):
        lines.append(
            f"### {c.symbol} ({c.security_type}, {c.sector}) — composite {c.composite_score:+.2f}, "
            f"consensus {c.debate.consensus_signal.value} (conf {c.debate.consensus_confidence:.2f})"
        )
        lines.append(f"- Relative strength vs SPY (10-bar): "
                      f"{'n/a' if c.relative_strength_vs_spy is None else f'{c.relative_strength_vs_spy * 100:+.1f}%'}")
        lines.append(f"- Bull case: {c.debate.bull_thesis}")
        lines.append(f"- Bear case: {c.debate.bear_thesis}")
        lines.append(f"- Manager rationale: {c.debate.rationale}")
        for r in c.analyst_reports:
            lines.append(f"  - **{r.agent_name}**: {r.signal.value} (conf {r.confidence:.2f}) — {r.summary}")
        lines.append("")

    return "\n".join(lines)


def _report_to_jsonable(report: CommitteeReport) -> dict:
    def default(obj):
        if hasattr(obj, "value"):  # Signal enum
            return obj.value
        raise TypeError(f"not JSON serializable: {obj!r}")

    return json.loads(json.dumps(dataclasses.asdict(report), default=default))


def write_report(report: CommitteeReport, out_dir: str, latest_path: str | None = None) -> tuple[str, str]:
    """Writes `{out_dir}/{run_date}.md`/`.json` plus a copy at `latest_path`
    (defaults to `{out_dir}/LATEST_PICKS.md`, i.e. fully contained inside
    `out_dir` — callers that want the traditional top-level
    `research_team/LATEST_PICKS.md` location must pass it explicitly, so a
    caller writing into an isolated/dry-run `out_dir` can never leak a file
    out of it by accident)."""
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, f"{report.run_date}.md")
    json_path = os.path.join(out_dir, f"{report.run_date}.json")
    if latest_path is None:
        latest_path = os.path.join(out_dir, "LATEST_PICKS.md")

    markdown = to_markdown(report)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(_report_to_jsonable(report), f, indent=2, ensure_ascii=False)
    os.makedirs(os.path.dirname(latest_path) or ".", exist_ok=True)
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    return md_path, json_path
