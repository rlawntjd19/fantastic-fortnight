"""Typed data passed between pipeline stages."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Signal(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CLOSE = "close"


@dataclass
class AnalystReport:
    agent_name: str
    signal: Signal
    confidence: float  # 0..1
    summary: str
    key_points: list[str] = field(default_factory=list)


@dataclass
class ResearchDebateResult:
    bull_thesis: str
    bear_thesis: str
    consensus_signal: Signal
    consensus_confidence: float
    rationale: str


@dataclass
class TradePlan:
    symbol: str
    action: Action
    entry_price: float
    target_price: float
    stop_loss_price: float
    leverage: float
    tranche_sizes: list[float]  # fractions of proposed notional, sums to 1.0
    rationale: str


@dataclass
class RiskVerdict:
    approved: bool
    adjusted_leverage: float
    adjusted_position_pct_of_equity: float
    violations_corrected: list[str]
    notes: str


@dataclass
class FinalDecision:
    trade_plan: TradePlan
    risk_verdict: RiskVerdict
    requires_human_approval: bool
    status: str  # "pending_approval" | "blocked"
    blocked_reason: str | None = None
