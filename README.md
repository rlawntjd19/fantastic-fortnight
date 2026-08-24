# AI Investment Research Agent (paper trading)

A multi-agent research assistant that turns market data into a trade
**proposal**, and stops there. Nothing in this repository places a real
order, holds brokerage credentials, or auto-executes anything.

> Research/education tool. Not investment advice. Every decision the
> pipeline produces requires a human to explicitly approve it before it's
> even booked into the local paper-trading ledger.

## Why this shape

This design is a response to a common but risky pattern: a single LLM
call is asked "what should I buy" and its answer is wired directly into
a live, highly leveraged brokerage account. That collapses three things
that should stay separate — market analysis, position sizing, and risk
limits — into one unaccountable step, and removes the human from the
loop entirely.

Instead, this pipeline is a fixed sequence of small, inspectable stages,
loosely modeled on the "specialized analysts → structured bull/bear
debate → risk debate → portfolio decision" pattern from open multi-agent
trading-agent research (e.g. Tauric Research's TradingAgents):

```
MarketDataProvider
      │
      ▼
TechnicalAnalyst / FundamentalAnalyst / SentimentAnalyst / ForecastAnalyst
      │  AnalystReport(signal, confidence, summary)        (agents/analysts.py)
      ▼
ResearchManager (bull case vs. bear case → consensus)      (agents/researchers.py)
      │  ResearchDebateResult
      ▼
Trader (drafts a TradePlan: action/entry/target/stop)      (agents/trader.py)
      │  TradePlan
      ▼
Aggressive / Conservative / Neutral risk debate (narrative) (agents/risk.py)
      │
      ▼
enforce_hard_limits()  ← RiskLimits from config.py, code only, no LLM
      │  RiskVerdict (clamped leverage/size, or blocked)
      ▼
FinalDecision  →  shown to a human  →  only then, optionally,
                                        PaperBroker.execute(human_approved=True)
```

Key properties:

* **The LLM never sets the numbers.** Every analyst computes its
  signal/confidence with a plain deterministic rule (moving averages,
  RSI, P/E, keyword sentiment) first; the LLM only adds a short natural-
  language narrative on top. This also means the whole pipeline runs and
  is unit-tested with zero API calls (`DummyLLMClient`).
* **Risk limits are enforced in code, once, at the end**
  (`engine/risk_controls.py`), regardless of what the trader or the risk
  debate agents argued for. `RiskLimits` in `config.py` defaults to a
  3x leverage ceiling, a 10% of equity per-position cap, a required
  stop-loss, and a 5% daily-loss circuit breaker that blocks new entries
  (but never blocks closing a position).
* **Execution always requires a human.** `PaperBroker.execute()` raises
  unless called with `human_approved=True`; the CLI is the only caller,
  and only after printing the full decision and asking `y/N`.
* **No live brokerage integration is included.** `PaperBroker` is an
  in-memory ledger for a single process. Wiring a real broker/exchange
  API is a deliberate, separate decision outside this repo's scope.

## Usage

```bash
pip install -r requirements.txt
cp .env.example .env   # optional: add ANTHROPIC_API_KEY for real narratives

python -m trading_agent.cli signal SK_HYNIX --leverage 5 --tranches 2
```

Note the requested `--leverage 5` above is only ever a *request*; the
printed "risk-clamped verdict" section shows what it was actually cut
down to under `RiskLimits.max_leverage` (default 3x), with the
correction spelled out.

Add `--approve` to be asked, after seeing the full breakdown, whether to
book the (already clamped) decision into the local paper broker.

## Kronos (optional price-forecasting analyst)

[Kronos](https://github.com/shiyu-coder/Kronos) (MIT license) is an
open-source decoder-only foundation model pretrained on OHLCV
"candlestick" data from 45+ exchanges. Given a lookback window it
forecasts future OHLCV bars, and its own paper is explicit that it
forecasts *prices*, not profitable trading decisions — portfolio
construction and risk management are left to the caller. That's exactly
this repo's existing separation of concerns, so it plugs in as a fourth
analyst (`ForecastAnalyst` in `agents/analysts.py`) rather than anywhere
closer to sizing or execution:

* `forecast/base.py` defines the `PriceForecaster` protocol (mirrors
  `llm.client.LLMClient`).
* `forecast/heuristic_forecaster.py` is the zero-dependency default: a
  linear-drift extrapolation used everywhere Kronos isn't installed,
  including all tests.
* `forecast/kronos_forecaster.py` adapts `KronosPredictor` to that same
  protocol, sampling it `sample_count` times to turn its autoregressive
  sampling into a cheap uncertainty estimate (wide disagreement across
  samples lowers the analyst's confidence, same idea as a wide
  confidence interval).
* `forecast/factory.py` builds whichever one is configured, and **always
  falls back to the heuristic** if Kronos is enabled but its (separately
  installed) `model` package or weights aren't available — a forecaster
  failing to load must never crash the pipeline.

Kronos is off by default (`KronosConfig.enabled = False` in `config.py`)
because it isn't on PyPI, needs `torch`, and downloads model weights on
first use — it must stay opt-in, never a silent hard requirement. To try
it:

```bash
git clone https://github.com/shiyu-coder/Kronos.git
pip install -r Kronos/requirements.txt -r requirements-kronos.txt
export PYTHONPATH=$PYTHONPATH:$(pwd)/Kronos

python -m trading_agent.cli signal SK_HYNIX --kronos
# or: TRADING_AGENT_KRONOS_ENABLED=true python -m trading_agent.cli signal SK_HYNIX
```

Two things this integration deliberately does **not** do:

* It doesn't feed Kronos's forecast into `Trader`'s target/stop
  calculation — it only becomes one more `AnalystReport` the
  `ResearchManager` weighs alongside the other three. Wiring the
  predicted path into target-price estimation is a reasonable next step,
  but it should stay behind the same hard risk ceilings, not bypass them.
* It only passes close prices into Kronos (`ForecastAnalyst` reads
  `MarketSnapshot.closes`, same as `TechnicalAnalyst`), synthesizing
  flat open/high/low from that. Kronos performs meaningfully better on
  real OHLCV bars; a `MarketDataProvider` that exposes full bars to
  analysts should pass those through instead — see the comment in
  `kronos_forecaster.py`.

## Tests

```bash
pytest
```

Tests run fully offline against `DummyLLMClient` and `SimulatedFeed` (a
deterministic pseudo-random-walk price generator) — no network or API
key required.

## Extending this

* Swap `SimulatedFeed` for a real market-data vendor by implementing
  `MarketDataProvider.get_snapshot()` against that vendor's API.
* Adjust `RiskLimits` in `config.py` deliberately and explicitly if a
  higher ceiling is truly intended — do not raise it to make a specific
  trade plan pass.
* `engine/memory.py` gives closed trades a place to leave a short
  reflection; wiring `ReflectionMemory.recent_lessons()` into the
  analyst/trader prompts is the natural next step for a learning loop.
* Any other forecasting backend can replace Kronos the same way it
  replaces the heuristic: implement `forecast.base.PriceForecaster`
  and pass it into `TradingCycle(..., forecaster=...)`.
