"""Zero-dependency fallback forecaster.

Used whenever Kronos isn't installed/enabled, and in all tests, so the
package keeps working fully offline with no torch/GPU requirement. It
extrapolates the recent linear drift and scales dispersion off recent
realized volatility — deliberately simple, since its only job is to keep
the pipeline's shape intact when a real forecasting model isn't wired in.
"""
from __future__ import annotations

import math
from statistics import pstdev

from trading_agent.forecast.base import ForecastResult


class HeuristicForecaster:
    def __init__(self, lookback: int = 20) -> None:
        self._lookback = lookback

    def forecast(self, closes: list[float], pred_len: int) -> ForecastResult:
        if len(closes) < 2:
            last = closes[-1] if closes else 0.0
            return ForecastResult([last] * pred_len, 0.0, 0.0, 1, "heuristic")

        window = closes[-self._lookback :]
        # A real data feed occasionally hands back a NaN/zero close (a
        # halted-trading day, a gap in the provider's history) — one bad
        # bar must not crash the whole forecast (and, upstream, the whole
        # daily cycle). Drop any bar pair that can't produce a finite
        # return rather than letting inf/nan poison drift/volatility (and
        # crash statistics.pstdev, which chokes on non-finite input).
        returns = [
            window[i] / window[i - 1] - 1
            for i in range(1, len(window))
            if window[i - 1] != 0 and math.isfinite(window[i]) and math.isfinite(window[i - 1])
        ]
        if not returns:
            last = closes[-1] if closes else 0.0
            return ForecastResult([last] * pred_len, 0.0, 0.0, 1, "heuristic")
        drift = sum(returns) / len(returns)
        volatility = pstdev(returns) if len(returns) > 1 else 0.0

        path: list[float] = []
        price = closes[-1]
        for _ in range(pred_len):
            price = price * (1 + drift)
            path.append(price)

        expected_return = path[-1] / closes[-1] - 1
        # Dispersion of the pred_len-step-ahead return under the recent
        # per-step volatility, assuming independent steps: sigma * sqrt(n).
        dispersion = volatility * (pred_len**0.5)

        return ForecastResult(
            predicted_closes=path,
            expected_return=expected_return,
            dispersion=dispersion,
            sample_count=1,
            source="heuristic",
        )
