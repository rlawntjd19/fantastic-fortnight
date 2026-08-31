"""Typed data passed between committee stages.

Mirrors `trading_agent/agents/schemas.py`'s style: plain dataclasses, no
behavior. `CandidateAssessment` is the per-symbol research packet the
`PortfolioManager` ranks from; `Position`/`PortfolioState` are the
persisted, day-over-day standing basket the committee marks to market and
rotates, so alpha-vs-benchmark can be measured across days, not just
computed once.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from trading_agent.agents.schemas import AnalystReport, ResearchDebateResult


@dataclass
class CandidateAssessment:
    symbol: str
    security_type: str  # "stock" | "index_etf"
    sector: str | None
    market_cap: float | None
    last_price: float
    analyst_reports: list[AnalystReport]
    debate: ResearchDebateResult
    relative_strength_vs_spy: float | None  # 10-bar momentum spread vs SPY
    composite_score: float  # -1..1, code-computed, never LLM-set
    notes: list[str] = field(default_factory=list)


@dataclass
class CommitteePick:
    symbol: str
    security_type: str
    sector: str | None
    composite_score: float
    entry_price: float
    thesis: str
    conviction: str  # "high" | "medium" | "low"


@dataclass
class Position:
    symbol: str
    security_type: str
    entry_date: str
    entry_price: float
    benchmark_entry_price: float  # SPY price the same day, for alpha tracking
    thesis: str
    status: str = "open"  # "open" | "closed_thesis_broke" | "closed_horizon"
    exit_date: str | None = None
    exit_price: float | None = None
    benchmark_exit_price: float | None = None
    exit_reason: str | None = None


@dataclass
class PortfolioState:
    positions: list[Position] = field(default_factory=list)
    closed: list[Position] = field(default_factory=list)

    @property
    def open_positions(self) -> list[Position]:
        return [p for p in self.positions if p.status == "open"]


@dataclass
class CommitteeReport:
    run_date: str
    universe_size: int
    screened_out: list[str]
    candidates: list[CandidateAssessment]
    exits: list[Position]
    entries: list[CommitteePick]
    open_positions: list[Position]
    scoreboard: list[dict]  # per-position running alpha vs SPY
    cio_rationale: str
    okr_summary: str
