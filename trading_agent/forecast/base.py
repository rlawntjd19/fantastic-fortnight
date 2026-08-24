"""Price forecaster abstraction.

Mirrors `llm.client.LLMClient`: agents depend only on this narrow
protocol, never on a specific forecasting backend, so Kronos can be
swapped for the offline heuristic fallback (or any other model) without
touching agent code.

A forecaster predicts a *price path*, nothing more. It never proposes a
position size, leverage, or stop-loss — those stay the Trader's and
RiskManager's job, same as every other analyst's output.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Protocol


@dataclass
class ForecastResult:
    predicted_closes: list[float]  # one path (mean across samples if ensembled)
    expected_return: float  # (last predicted close / last known close) - 1
    dispersion: float  # stdev of sampled final-close returns; 0.0 if single-sample
    sample_count: int
    source: str  # e.g. "kronos:NeoQuasar/Kronos-small" or "heuristic"


class PriceForecaster(Protocol):
    def forecast(self, closes: list[float], pred_len: int) -> ForecastResult:
        ...


def summarize_sampled_returns(
    last_known_close: float, sampled_final_closes: list[float], source: str, predicted_path: list[float]
) -> ForecastResult:
    """Shared helper: turn N sampled final-close predictions into a ForecastResult."""
    returns = [c / last_known_close - 1 for c in sampled_final_closes]
    return ForecastResult(
        predicted_closes=predicted_path,
        expected_return=mean(returns),
        dispersion=pstdev(returns) if len(returns) > 1 else 0.0,
        sample_count=len(sampled_final_closes),
        source=source,
    )
