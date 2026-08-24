"""tool_math.py — math/quant helpers, re-exported under one name.

Thin re-export only: the actual implementations live in
`data/indicators.py` (technical indicators) and `engine/performance.py`
(equity-curve performance metrics). Nothing here duplicates logic.
"""
from __future__ import annotations

from trading_agent.data.indicators import momentum, rsi, sma
from trading_agent.engine.performance import PerformanceReport, compute_performance

__all__ = ["sma", "rsi", "momentum", "compute_performance", "PerformanceReport"]
