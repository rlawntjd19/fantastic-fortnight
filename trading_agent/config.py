"""Central configuration and hard risk ceilings.

These limits are enforced in `engine.risk_controls` in code, not by any
LLM agent. Analysts/researchers/trader agents may propose whatever they
want; the RiskManager can only ever narrow a proposal down to fit inside
these ceilings, never widen it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RiskLimits:
    # Hard ceiling on leverage the system will ever assemble into a trade
    # plan, regardless of what any agent argues for. The transcript this
    # design responds to used 20x; the default here is intentionally far
    # more conservative and must be raised explicitly and knowingly.
    max_leverage: float = 3.0

    # Max fraction of paper account equity allowed in a single symbol's
    # position notional (before leverage).
    max_position_pct_of_equity: float = 0.10

    # Every trade plan must carry a stop loss within this fraction of entry.
    max_stop_loss_pct: float = 0.05

    # Max number of tranches a scaled entry may be split into.
    max_tranches: int = 3

    # Daily circuit breaker: once realized+unrealized PnL for the day drops
    # this fraction below the day's starting equity, no new BUY signals are
    # allowed to reach the human approval stage (closing/reducing positions
    # is still allowed).
    daily_loss_circuit_breaker_pct: float = 0.05

    # Optional trailing stop: once set, an open position's stop-loss is
    # ratcheted toward the current price by this fraction as it moves
    # favorably, and never loosened. None (default) keeps the original
    # fixed stop from the trade plan, unchanged for the life of the position.
    trailing_stop_pct: float | None = None


@dataclass(frozen=True)
class KronosConfig:
    """Settings for the optional Kronos price-forecasting analyst.

    Off by default: Kronos (https://github.com/shiyu-coder/Kronos) is not
    on PyPI, needs torch, and downloads model weights on first use, so it
    must never be a silent hard requirement for the rest of the pipeline.
    Flip `enabled` on only after following the install steps in README.md;
    if construction fails anyway, `forecast.factory.build_price_forecaster`
    falls back to the offline heuristic rather than crashing.
    """

    enabled: bool = os.environ.get("TRADING_AGENT_KRONOS_ENABLED", "false").lower() == "true"
    model_name: str = os.environ.get("TRADING_AGENT_KRONOS_MODEL", "NeoQuasar/Kronos-small")
    tokenizer_name: str = os.environ.get(
        "TRADING_AGENT_KRONOS_TOKENIZER", "NeoQuasar/Kronos-Tokenizer-base"
    )
    max_context: int = int(os.environ.get("TRADING_AGENT_KRONOS_MAX_CONTEXT", "512"))
    device: str = os.environ.get("TRADING_AGENT_KRONOS_DEVICE", "cpu")
    pred_len: int = int(os.environ.get("TRADING_AGENT_KRONOS_PRED_LEN", "10"))
    # Number of forward samples drawn to estimate forecast uncertainty.
    # Kronos is autoregressive-sampling based, so >1 sample gives a cheap
    # ensemble spread instead of a single point forecast.
    sample_count: int = int(os.environ.get("TRADING_AGENT_KRONOS_SAMPLES", "5"))


@dataclass(frozen=True)
class LiveDataConfig:
    """Settings for the optional real-market-data feed (Yahoo Finance via `yfinance`).

    Off by default (`SimulatedFeed` is used instead) since it needs a
    network call and the `yfinance` package. Enable with `--live` on the
    CLI or `TRADING_AGENT_LIVE_DATA_ENABLED=true`. Unlike the Kronos
    forecaster, a failed *fetch* (bad ticker, no network) is never
    silently swapped for fake data — that would be actively misleading
    for a finance tool — it's raised as a clear error instead. Only a
    missing `yfinance` install falls back, the same way Kronos does.
    """

    enabled: bool = os.environ.get("TRADING_AGENT_LIVE_DATA_ENABLED", "false").lower() == "true"
    period: str = os.environ.get("TRADING_AGENT_LIVE_DATA_PERIOD", "6mo")
    interval: str = os.environ.get("TRADING_AGENT_LIVE_DATA_INTERVAL", "1d")
    # A separate, much longer window than `period` above, used only to feed
    # SeasonalityAnalyst real multi-year history for its own-symbol,
    # own-calendar-window win-rate check — the other 5 desks never see this
    # window, only `period`.
    seasonal_period: str = os.environ.get("TRADING_AGENT_SEASONAL_LOOKBACK_PERIOD", "10y")


@dataclass(frozen=True)
class Config:
    model_name: str = os.environ.get("TRADING_AGENT_MODEL", "claude-sonnet-5")
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    starting_paper_equity: float = float(
        os.environ.get("TRADING_AGENT_STARTING_EQUITY", "10_000_000")
    )
    risk: RiskLimits = field(default_factory=RiskLimits)
    kronos: KronosConfig = field(default_factory=KronosConfig)
    live_data: LiveDataConfig = field(default_factory=LiveDataConfig)
    memory_path: str = os.environ.get(
        "TRADING_AGENT_MEMORY_PATH", "trading_agent_memory.json"
    )
    journal_path: str = os.environ.get(
        "TRADING_AGENT_JOURNAL_PATH", "trading_agent_journal.jsonl"
    )


DEFAULT_CONFIG = Config()
