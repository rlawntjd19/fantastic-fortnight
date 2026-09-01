"""Regression coverage for research_team/dashboard/build_payload.py — the
transform that turns a CommitteeReport JSON into the dashboard's embedded
data payload. Run as a subprocess (mirrors how the daily automation will
invoke it) since research_team/ isn't a Python package."""
import json
import subprocess
import sys

from trading_agent.committee.daily_report import OKR_TARGET_HIGH_PP, OKR_TARGET_LOW_PP
from trading_agent.committee.render import _report_to_jsonable
from trading_agent.committee.schemas import CommitteeReport


def _run_build_payload(report_dict: dict, tmp_path) -> dict:
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report_dict), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "research_team/dashboard/build_payload.py", str(report_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_build_payload_matches_okr_target_constants(tmp_path):
    report = CommitteeReport(
        run_date="2026-09-01",
        universe_size=1,
        screened_out=[],
        candidates=[],
        exits=[],
        entries=[],
        open_positions=[],
        scoreboard=[],
        cio_rationale="- Step 1 (Test): nothing to do.\n\nCIO summary: nothing today.",
        okr_summary="No open, price-verified positions yet.",
    )
    payload = _run_build_payload(_report_to_jsonable(report), tmp_path)

    assert payload["targetLow"] == OKR_TARGET_LOW_PP
    assert payload["targetHigh"] == OKR_TARGET_HIGH_PP
    assert payload["runDate"] == "2026-09-01"
    assert payload["basket"] == []
    assert payload["avgAlphaPct"] == 0
    assert payload["steps"] == ["Step 1 (Test): nothing to do."]
    assert payload["cioSummary"] == "nothing today."
