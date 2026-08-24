"""Build the configured price forecaster, falling back safely offline.

Mirrors `llm.client.build_llm_client`. Kronos is opt-in (`config.kronos.enabled`)
because it pulls in torch + a manually-installed repo + downloaded model
weights; everything in this project must keep working with none of that
present, so any failure to construct it falls back to the zero-dependency
heuristic rather than crashing the pipeline.
"""
from __future__ import annotations

import sys

from trading_agent.forecast.heuristic_forecaster import HeuristicForecaster


def build_price_forecaster(config):
    if not config.kronos.enabled:
        return HeuristicForecaster()

    try:
        from trading_agent.forecast.kronos_forecaster import KronosForecaster

        return KronosForecaster(
            model_name=config.kronos.model_name,
            tokenizer_name=config.kronos.tokenizer_name,
            max_context=config.kronos.max_context,
            device=config.kronos.device,
            sample_count=config.kronos.sample_count,
        )
    except Exception as exc:  # noqa: BLE001 - deliberately broad: any setup failure must degrade, not crash
        print(f"[trading_agent] Kronos forecaster unavailable ({exc}); falling back to heuristic.", file=sys.stderr)
        return HeuristicForecaster()
