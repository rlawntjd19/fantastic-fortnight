"""Transforms one day's CommitteeReport JSON (research_team/reports/*.json)
into the compact payload the dashboard template embeds and renders.

    python research_team/dashboard/build_payload.py research_team/reports/2026-09-01.json

Prints the payload as a single-line JSON object to stdout — swap it in for
`__DATA_PLACEHOLDER__` in template.html to produce that day's dashboard.
Kept separate from template.html so the two can be regenerated
independently: the transform changes if CommitteeReport's shape changes,
the template changes if the dashboard's design changes.
"""
from __future__ import annotations

import json
import re
import sys

# Mirrors trading_agent/committee/universe.py's static sector labels.
# Held positions aren't re-screened against the universe every run (see
# daily_report.run_daily_cycle), so their sector isn't in the report JSON;
# this fills that in for display only, never for scoring.
_SECTOR_MAP = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology", "GOOGL": "Technology",
    "META": "Technology", "AVGO": "Technology", "CRM": "Technology", "ADBE": "Technology",
    "AMD": "Technology", "ORCL": "Technology",
    "AMZN": "Consumer", "COST": "Consumer", "WMT": "Consumer", "HD": "Consumer",
    "MCD": "Consumer", "NKE": "Consumer",
    "UNH": "Healthcare", "LLY": "Healthcare", "JNJ": "Healthcare", "ABBV": "Healthcare", "MRK": "Healthcare",
    "JPM": "Financials", "V": "Financials", "MA": "Financials", "GS": "Financials", "BRK-B": "Financials",
    "CAT": "Industrials", "HON": "Industrials", "GE": "Industrials",
    "XOM": "Energy", "CVX": "Energy",
    "NFLX": "Communication", "DIS": "Communication",
    "PG": "Staples", "KO": "Staples",
    "SPY": "Broad Market", "VOO": "Broad Market", "VTI": "Broad Market",
    "QQQ": "Large-Cap Growth", "DIA": "Broad Market",
}

_MAX_CANDIDATES_SHOWN = 16

# Mirrors trading_agent/committee/daily_report.OKR_TARGET_LOW_PP/_HIGH_PP.
_OKR_TARGET_LOW_PP = 10.0
_OKR_TARGET_HIGH_PP = 15.0


def build_payload(report: dict) -> dict:
    scoreboard = report["scoreboard"]
    avg_alpha = sum(r["alpha_pct"] for r in scoreboard) / len(scoreboard) if scoreboard else 0.0
    sb_by_symbol = {r["symbol"]: r for r in scoreboard}
    held_symbols = {p["symbol"] for p in report["open_positions"]}

    basket = []
    for p in report["open_positions"]:
        sb = sb_by_symbol.get(p["symbol"], {})
        basket.append(
            {
                "symbol": p["symbol"],
                "type": p["security_type"],
                "sector": _SECTOR_MAP.get(p["symbol"], "—"),
                "entryDate": p["entry_date"],
                "entryPrice": round(p["entry_price"], 2),
                "currentPrice": round(sb.get("current_price", p["entry_price"]), 2),
                "returnPct": round(sb.get("position_return_pct", 0) * 100, 2),
                "alphaPct": round(sb.get("alpha_pct", 0) * 100, 2),
                "thesis": p["thesis"].replace("[offline-stub] ", ""),
            }
        )

    top_candidates = sorted(report["candidates"], key=lambda c: c["composite_score"], reverse=True)
    candidates = [
        {
            "symbol": c["symbol"],
            "type": c["security_type"],
            "sector": c["sector"],
            "score": round(c["composite_score"], 2),
            "signal": c["debate"]["consensus_signal"],
            "confidence": round(c["debate"]["consensus_confidence"], 2),
            "relStrength": None
            if c["relative_strength_vs_spy"] is None
            else round(c["relative_strength_vs_spy"] * 100, 1),
            "held": c["symbol"] in held_symbols,
        }
        for c in top_candidates[:_MAX_CANDIDATES_SHOWN]
    ]

    steps = [s.strip() for s in re.findall(r"- (Step \d+.*?)(?=\n- Step|\n\nCIO summary|$)", report["cio_rationale"], re.S)]
    summary_match = re.search(r"CIO summary: (.*)", report["cio_rationale"], re.S)
    cio_summary = (summary_match.group(1).strip() if summary_match else "").replace("[offline-stub] ", "")

    return {
        "runDate": report["run_date"],
        "universeSize": report["universe_size"],
        "screenedOutCount": len(report["screened_out"]),
        "avgAlphaPct": round(avg_alpha * 100, 2),
        "targetLow": _OKR_TARGET_LOW_PP,
        "targetHigh": _OKR_TARGET_HIGH_PP,
        "basket": basket,
        "scoreboard": [
            {
                "symbol": r["symbol"],
                "alphaPct": round(r["alpha_pct"] * 100, 2),
                "returnPct": round(r["position_return_pct"] * 100, 2),
                "benchPct": round(r["benchmark_return_pct"] * 100, 2),
            }
            for r in scoreboard
        ],
        "entriesToday": [e["symbol"] for e in report["entries"]],
        "exitsToday": [{"symbol": e["symbol"], "reason": e.get("exit_reason", "")} for e in report["exits"]],
        "steps": steps,
        "cioSummary": cio_summary,
        "candidates": candidates,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: build_payload.py <path to research_team/reports/YYYY-MM-DD.json>", file=sys.stderr)
        return 1
    with open(sys.argv[1], encoding="utf-8") as f:
        report = json.load(f)
    print(json.dumps(build_payload(report), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
