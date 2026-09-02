"""Regression coverage for the report-validation guard in
cli._run_daily_picks: a report that fails its own internal-consistency
checks (report_validation.validate_report) must never be persisted into
state or written to disk, live or dry-run."""
import os

import trading_agent.cli as cli_module
from trading_agent.cli import main


def test_refuses_to_write_a_report_that_fails_validation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "validate_report", lambda report: ["synthetic problem for this test"])

    exit_code = main(["daily-picks", "--date", "2026-09-02"])

    assert exit_code == 1
    assert not os.path.exists("research_team/reports/_dry_run")


def test_proceeds_when_the_report_passes_validation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "validate_report", lambda report: [])

    exit_code = main(["daily-picks", "--date", "2026-09-02"])

    assert exit_code == 0
    assert os.path.exists("research_team/reports/_dry_run")
