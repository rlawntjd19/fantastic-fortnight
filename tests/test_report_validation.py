from trading_agent.committee.report_validation import validate_report
from trading_agent.committee.schemas import CommitteeReport, Position


def _position(symbol: str) -> Position:
    return Position(
        symbol=symbol,
        security_type="stock",
        entry_date="2026-08-31",
        entry_price=100.0,
        benchmark_entry_price=500.0,
        thesis="test",
    )


def _clean_report() -> CommitteeReport:
    open_positions = [_position("AAA"), _position("BBB")]
    scoreboard = [
        {
            "symbol": "AAA",
            "current_price": 110.0,
            "position_return_pct": 0.10,
            "benchmark_return_pct": 0.05,
            "alpha_pct": 0.05,
            "weight_pct": 0.6,
            "shares": 500,
            "allocated_value": 55000.0,
        },
        {
            "symbol": "BBB",
            "current_price": 90.0,
            "position_return_pct": -0.10,
            "benchmark_return_pct": 0.05,
            "alpha_pct": -0.15,
            "weight_pct": 0.4,
            "shares": 400,
            "allocated_value": 36000.0,
        },
    ]
    avg_alpha = sum(r["alpha_pct"] for r in scoreboard) / len(scoreboard)
    return CommitteeReport(
        run_date="2026-09-02",
        universe_size=40,
        screened_out=[],
        candidates=[],
        exits=[],
        entries=[],
        open_positions=open_positions,
        scoreboard=scoreboard,
        cio_rationale="n/a",
        okr_summary=f"Basket-average alpha vs SPY across {len(scoreboard)} open position(s): {avg_alpha * 100:+.2f}pp (OKR target: +10-15pp or better over each position's 2-3 month hold).",
    )


def test_clean_report_has_no_problems():
    assert validate_report(_clean_report()) == []


def test_catches_duplicate_open_symbol():
    report = _clean_report()
    report.open_positions.append(_position("AAA"))
    problems = validate_report(report)
    assert any("Duplicate symbol" in p for p in problems)


def test_catches_symbol_both_exited_and_open():
    report = _clean_report()
    report.exits.append(_position("AAA"))
    problems = validate_report(report)
    assert any("both exited and still listed open" in p for p in problems)


def test_catches_alpha_math_mismatch():
    report = _clean_report()
    report.scoreboard[0]["alpha_pct"] = 0.99  # doesn't match position/benchmark return
    problems = validate_report(report)
    assert any("doesn't match position_return-benchmark_return" in p for p in problems)


def test_catches_weights_not_summing_to_one():
    report = _clean_report()
    report.scoreboard[0]["weight_pct"] = 0.9  # now sums to 1.3
    problems = validate_report(report)
    assert any("sum to" in p for p in problems)


def test_catches_negative_weight():
    report = _clean_report()
    report.scoreboard[0]["weight_pct"] = -0.1
    problems = validate_report(report)
    assert any("negative weight_pct" in p for p in problems)


def test_catches_non_positive_price():
    report = _clean_report()
    report.scoreboard[0]["current_price"] = 0.0
    problems = validate_report(report)
    assert any("non-positive current_price" in p for p in problems)


def test_catches_allocated_value_mismatch():
    report = _clean_report()
    report.scoreboard[0]["allocated_value"] = 999999.0
    problems = validate_report(report)
    assert any("doesn't match shares*current_price" in p for p in problems)


def test_catches_okr_summary_mismatching_scoreboard():
    report = _clean_report()
    report.okr_summary = (
        "Basket-average alpha vs SPY across 2 open position(s): +50.00pp "
        "(OKR target: +10-15pp or better over each position's 2-3 month hold)."
    )
    problems = validate_report(report)
    assert any("okr_summary states avg alpha" in p for p in problems)


def test_scoreboard_row_with_no_matching_open_position_is_flagged():
    report = _clean_report()
    report.scoreboard[0]["symbol"] = "ZZZ"
    problems = validate_report(report)
    assert any("no matching open position" in p for p in problems)


def test_empty_report_has_no_problems():
    report = CommitteeReport(
        run_date="2026-09-02",
        universe_size=40,
        screened_out=[],
        candidates=[],
        exits=[],
        entries=[],
        open_positions=[],
        scoreboard=[],
        cio_rationale="n/a",
        okr_summary="No open, price-verified positions yet — nothing to score against the OKR this run.",
    )
    assert validate_report(report) == []
