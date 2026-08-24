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
TechnicalAnalyst / FundamentalAnalyst / SentimentAnalyst   (agents/analysts.py)
      │  AnalystReport(signal, confidence, summary)
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
