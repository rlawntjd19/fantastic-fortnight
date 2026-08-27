"""Typed data passed between portfolio-construction stages. Mirrors the
shape of `trading_agent/agents/schemas.py` for the single-symbol pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from trading_agent.agents.schemas import AnalystReport, ResearchDebateResult


@dataclass
class CandidateScore:
    symbol: str
    sector: str
    reports: list[AnalystReport]
    debate: ResearchDebateResult
    composite_score: float  # signed, roughly -1..1 (bearish..bullish)
    last_price: float
    closes: list[float]


@dataclass
class SelectionRound:
    round_number: int
    sector_cap: int | None
    score_threshold: float
    considered: list[str]
    selected: list[str]
    notes: str


@dataclass
class OptimizationResult:
    weights: dict[str, float]
    expected_annual_return: float
    annual_volatility: float
    sharpe_ratio: float | None
    portfolio_beta: float | None


@dataclass
class AllocationLine:
    symbol: str
    target_weight: float
    price: float
    shares: int
    dollars: float
    actual_weight: float


@dataclass
class PortfolioBacktestResult:
    starting_equity: float
    ending_equity: float
    total_return_pct: float
    annualized_return_pct: float
    annualized_vol_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float | None
    realized_beta: float | None
    treynor_ratio: float | None
    equity_curve: list[float] = field(default_factory=list)
    benchmark_equity_curve: list[float] | None = None
    num_bars: int = 0


@dataclass
class ForwardSimulationResult:
    horizon_days: int
    num_paths: int
    expected_return_pct: float
    median_return_pct: float
    p5_return_pct: float
    p95_return_pct: float
    prob_positive: float
    expected_ending_value: float
    starting_value: float


@dataclass
class PortfolioReport:
    as_of: str
    data_source: str  # "simulated" | "live"
    budget: float
    risk_free_rate: float
    market_risk_premium: float
    universe: list[CandidateScore]
    selection_rounds: list[SelectionRound]
    selected: list[CandidateScore]
    optimized: OptimizationResult
    equal_weight: OptimizationResult
    allocation: list[AllocationLine]
    leftover_cash: float
    backtest: PortfolioBacktestResult
    forward_simulation: ForwardSimulationResult
    benchmark_symbol: str
