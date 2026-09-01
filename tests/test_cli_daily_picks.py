"""Regression coverage for the --live data-integrity guard in
`cli._run_daily_picks`: a dry run (no --live) must never write into the
tracked research_team/ report or state files, since every real pick has to
be priced with live data (see research_team/README.md)."""
import os

from trading_agent.cli import main


def test_dry_run_defaults_never_touch_tracked_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exit_code = main(["daily-picks", "--date", "2026-08-31"])
    assert exit_code == 0

    assert not os.path.exists("research_team/reports/2026-08-31.md")
    assert not os.path.exists("research_team/state/portfolio.json")
    assert os.path.exists("research_team/reports/_dry_run/2026-08-31.md")
    assert os.path.exists("research_team/state/_dry_run_portfolio.json")
    assert os.path.exists("research_team/reports/_dry_run/LATEST_PICKS.md")
    assert not os.path.exists("research_team/LATEST_PICKS.md")


def test_dry_run_refuses_explicit_tracked_out_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exit_code = main(["daily-picks", "--out-dir", "research_team/reports", "--date", "2026-08-31"])
    assert exit_code == 1
    assert not os.path.exists("research_team")


def test_dry_run_refuses_explicit_tracked_state_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exit_code = main(
        [
            "daily-picks",
            "--state-path",
            "research_team/state/portfolio.json",
            "--date",
            "2026-08-31",
        ]
    )
    assert exit_code == 1
    assert not os.path.exists("research_team/state/portfolio.json")
