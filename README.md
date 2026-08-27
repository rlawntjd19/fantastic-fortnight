# AI Investment Research Agent (paper trading)

A multi-agent research assistant that autonomously researches, decides,
and books paper trades into a local, in-memory ledger. Nothing in this
repository connects to a real brokerage or exchange — every execution
here only ever mutates `PaperBroker`'s in-process state.

> Research/education tool. Not investment advice. Autonomous execution
> here is safe only because there is no real-money connector anywhere in
> this codebase — see "Why this shape" below for what that does and
> doesn't mean if one is ever added on top.

New here? [USAGE.md](USAGE.md) is a step-by-step walkthrough (Korean) for
running this for the first time. This README covers the design instead.

No Python installed, or don't want to install anything? [Open the Colab
quickstart](https://colab.research.google.com/github/rlawntjd19/fantastic-fortnight/blob/claude/ai-investment-agent-design-et70s0/colab_quickstart.ipynb)
notebook and run it from the browser — nothing to install locally.

Prefer a point-and-click control panel over the terminal? See "Web UI"
below (`pip install -r requirements-web.txt && python -m trading_agent.webapp`) —
or, in the Colab notebook above, run its "브라우저 제어판(웹 UI) 열기" cell
to open the same panel in a new tab with nothing installed locally.

## Why this shape

This design responds to a common, risky pattern: a single LLM call is
asked "what should I buy" and its answer is wired directly into a live,
highly leveraged brokerage account with no human anywhere in the loop.
That collapses three things that should stay separate — market
analysis, position sizing, and risk limits — into one unaccountable
step. This project draws the same separation, but does **not** insist a
human click "approve" on every decision — instead it moves the human
decision to a different, more durable place: the hard ceilings in
`config.py` and the fact that nothing here can reach a real account.

Instead, this pipeline is a fixed sequence of small, inspectable stages,
loosely modeled on the "specialized analysts → structured bull/bear
debate → risk debate → portfolio decision" pattern from open multi-agent
trading-agent research (e.g. Tauric Research's TradingAgents, HKUDS's
AI-Trader):

```
MarketDataProvider ─────────────┐  MacroDataProvider
      │                         │        │
      ▼                         ▼        ▼
TechnicalAnalyst / FundamentalAnalyst / SentimentAnalyst / MacroAnalyst / ForecastAnalyst
      │  AnalystReport(signal, confidence, summary)        (agents/analysts.py)
      ▼
ResearchManager (bull case vs. bear case → consensus)      (agents/researchers.py)
      │  ResearchDebateResult
      ▼
Trader (drafts a TradePlan: action/entry/target/stop;      (agents/trader.py)
        recent ReflectionMemory lessons add narration
        context only — see "Journal & reflection" below)
      │  TradePlan
      ▼
Aggressive / Conservative / Neutral risk debate (narrative) (agents/risk.py)
      │
      ▼
enforce_hard_limits()  ← RiskLimits from config.py, code only, no LLM
      │  RiskVerdict (clamped leverage/size, or blocked)
      ▼
FinalDecision  →  PaperBroker.execute(decision)  →  booked immediately
                                                     if it cleared risk controls
```

Key properties:

* **The LLM never sets the numbers.** Every analyst computes its
  signal/confidence with a plain deterministic rule (moving averages,
  RSI, P/E, debt/margins/analyst consensus, VIX/rates/dollar, forecast
  return) first; the LLM only adds a short natural-language narrative on
  top. This also means the whole pipeline runs and is unit-tested with
  zero API calls (`DummyLLMClient`).
* **Risk limits are enforced in code, once, at the end**
  (`engine/risk_controls.py`), regardless of what the trader or the risk
  debate agents argued for. `RiskLimits` in `config.py` defaults to a
  3x leverage ceiling, a 10% of equity per-position cap, a required
  stop-loss, and a 5% daily-loss circuit breaker that blocks new entries
  (but never blocks closing a position). No agent, narration, or
  "adaptation" mechanism can widen these — only editing `config.py` can.
* **Execution is autonomous and immediate.** `PaperBroker.execute()`
  books any decision that cleared risk controls right away — there is no
  per-decision prompt anywhere in this codebase (CLI, `watch` loop,
  backtest). This is deliberately safe only because `PaperBroker` is an
  in-memory ledger with no connection to any brokerage or exchange. If
  real execution is ever added on top, **that integration must implement
  its own explicit human-approval gate independently** — this class's
  autonomy must not be assumed to carry over to it (see
  `engine/paper_broker.py`'s docstring).
* **"Adaptation" is bounded to narration text, never to the rules.**
  Closed trades leave a reflection (`engine/memory.py`) that gets
  resurfaced as extra context in the trader's narration prompt — see
  "Journal & reflection" below. It cannot and does not change
  `RiskLimits`, the analysts' scoring, or the trade math.

## Usage

```bash
pip install -r requirements.txt
cp .env.example .env   # optional: add ANTHROPIC_API_KEY for real narratives

python -m trading_agent.cli signal SK_HYNIX --leverage 5 --tranches 2
```

Note the requested `--leverage 5` above is only ever a *request*; the
printed "risk-clamped verdict" section shows what it was actually cut
down to under `RiskLimits.max_leverage` (default 3x), with the
correction spelled out. If the decision clears risk controls, it's
booked into the paper broker immediately — no prompt.

## Live data, continuous trading, and the dashboard

By default `SimulatedFeed` gives each symbol its own deterministic
pseudo-random walk (seeded from `(seed, symbol)`, so different tickers
actually look different, and calling it again for the same symbol
advances the walk instead of repeating it — that's what lets `watch`
below see prices move between ticks).

**Real market data** — `--live` swaps in Yahoo Finance via `yfinance`:

```bash
pip install -r requirements-live.txt
python -m trading_agent.cli signal 000660.KS --live   # a real ticker, not a placeholder
```

Unlike Kronos, a failed *fetch* (bad ticker, no network) is never
silently swapped for fake data — `YFinanceFeed.get_snapshot` raises a
clear error instead, since quietly substituting simulated prices under
a real ticker's name would be actively misleading for a finance tool.
Only a missing `yfinance` install falls back (`data/factory.py`), the
same pattern as `forecast/factory.py`.

**Continuous paper trading** — `watch` runs `TradingCycle` on a loop,
marking positions to market, checking stop-losses, and booking every
decision that clears risk controls, every tick, with no prompt:

```bash
python -m trading_agent.cli watch 000660.KS --live --interval 60 --dashboard
```

**No system can guarantee profit** — this loop can lose paper money as
easily as make it; what it provides is the fixed multi-agent decision
process (`engine/live_runner.py`) running repeatedly, not an edge.

`--dashboard` serves a live dashboard at `http://127.0.0.1:8787`
(`trading_agent/dashboard.py`, stdlib `http.server` only, no new
dependency, bound to localhost) — an equity curve, open positions, and
a recent-decisions log, polling `/api/state` every few seconds.

## Kronos (optional price-forecasting analyst)

[Kronos](https://github.com/shiyu-coder/Kronos) (MIT license) is an
open-source decoder-only foundation model pretrained on OHLCV
"candlestick" data from 45+ exchanges. Given a lookback window it
forecasts future OHLCV bars, and its own paper is explicit that it
forecasts *prices*, not profitable trading decisions — portfolio
construction and risk management are left to the caller. That's exactly
this repo's existing separation of concerns, so it plugs in as one more
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

## Trailing stops, performance metrics, and backtesting

`RiskLimits.trailing_stop_pct` (`config.py`, off by default) ratchets an
open position's stop-loss toward the current price as it moves favorably
and never loosens it — still entirely code-decided
(`engine/risk_controls.trailing_stop_price`), the same way every other
hard limit is. `watch` and `backtest` both apply it every tick when set.

`engine/performance.py` turns an equity curve and closed-trade PnLs into
total return, max drawdown, win rate, and per-tick Sharpe/Sortino-style
ratios (explicitly **not** annualized or risk-free-rate-adjusted — a
relative diagnostic, not a number to compare against a fund's reported
Sharpe). The dashboard and `backtest`'s report both use it.

`backtest` replays historical bars through the exact same pipeline
bar-by-bar via `engine/backtest.ReplayFeed`, which only ever hands back
bars up to its current cursor — structurally unable to leak a future bar
into a decision, the same "no look-ahead" discipline dedicated
backtesting frameworks enforce:

```bash
python -m trading_agent.cli backtest 000660.KS --live --period 1y --leverage 2
python -m trading_agent.cli backtest 000660.KS --live --start 2025-01-01 --end 2025-02-28  # exact window
python -m trading_agent.cli backtest AAPL --min-lookback 40   # offline, SimulatedFeed
```

`--start`/`--end` reproduce a specific historical window exactly (the
same idea AI-Trader's "time control framework" replays a fixed past
period from), taking priority over `--period` when given. Every decision
that clears risk controls books immediately, same as everywhere else —
there's no live market a backtest could affect either way. **Past
performance in that report does not indicate or guarantee future
results** — treat a good backtest number as "worth investigating
further," never as evidence the strategy has a real edge.

**A correctness fix worth calling out:** `PaperBroker.execute` used to
*replace* a symbol's position on every fill, resetting `avg_entry_price`
to that tick's price — which silently forced unrealized PnL to exactly
zero on every single tick. A `watch` session or `backtest` run that kept
re-confirming the same signal (the common case) would show a perfectly
flat equity curve no matter what the market actually did, making the
loop, the dashboard, and any backtest report meaningless. It now nets
into the existing position instead: same-direction fills blend into a
weighted-average entry price, opposite-direction fills close/reduce the
position and realize PnL first, and only flip to the other side if the
order was larger than what was needed to flatten it.

## Portfolio construction (2-5 stock, $25k long-only allocator)

Everything above analyzes and paper-trades **one symbol at a time**.
`python -m trading_agent.cli portfolio` is a separate workflow
(`trading_agent/portfolio/`) that fans the same analyst pool out across a
14-name universe (large-cap US stocks plus a handful of broad/sector
ETFs — no mutual funds, no derivatives — see `portfolio/universe.py`) to
build one long-only, multi-name portfolio from a cash budget:

```
Universe (stocks + ETFs, 8+ sectors)
   |
   v
Screening Desk: Technical / Fundamental / Sentiment / Macro / Forecast     (screening.py,
                analysts -> bull/bear debate -> composite score            reusing agents/analysts.py)
   v
Portfolio Manager: iterative, sector-diversified selection (2-5 names)     (selection.py)
   v
Quant Desk: CAPM expected returns + historical covariance                 (optimizer.py)
            -> long-only max-Sharpe grid search
   v
Trading Desk: whole-share allocation of the cash budget                   (allocation.py)
   v
Risk Desk: trailing-history backtest + 3-month-ahead Monte Carlo          (backtest.py,
           projection                                              forward_simulation.py)
```

```bash
python -m trading_agent.cli portfolio --budget 25000 --out portfolio_memo.md
python -m trading_agent.cli portfolio --live --period 1y   # real Yahoo Finance data
```

Design choices worth calling out:

* **Selection is an explicit, logged iteration, not one opaque cutoff.**
  `selection.select_portfolio` tries a strict round first (at most one
  pick per sector, real conviction required), and only relaxes the
  sector cap or the score threshold — one knob at a time — if that round
  can't fill the minimum stock count. Every round's reasoning is kept as
  a `SelectionRound` and shown in the memo's "Selection trace" section,
  so *why* these names and not others is inspectable, not just the
  answer. If every round still comes up short, a clearly-flagged fallback
  takes the least-bad names rather than silently returning nothing.
* **Expected return comes from CAPM, not the historical sample mean.**
  Historical mean daily return is a notoriously noisy estimator of
  *future* expected return (a handful of unusual days swings it a lot) —
  a standard critique of naive Markowitz optimization. Historical
  covariance, by contrast, is empirically far more stable. So
  `optimizer.py` uses `risk_free_rate + beta * market_risk_premium`
  (CAPM) for expected return and the realized historical covariance
  matrix for risk — the same "replace the noisy return input with a
  model-implied prior, keep the empirical risk model" spirit as
  Black-Litterman, without needing a full Black-Litterman implementation.
* **Long-only max-Sharpe via exact grid search, not a solver dependency.**
  With only 2-5 assets, an exhaustive search over the weight simplex at a
  fixed step size is exact (not an approximation of a continuous
  optimizer) and needs no `scipy`, matching the project's existing
  zero-dependency style (`data/indicators.py`). A `weight_cap` bounds any
  single name's concentration; a `min_weight` floor is the mirror-image
  guardrail — plain mean-variance optimization is notorious for
  all-or-nothing corner solutions when candidates have similar estimated
  returns, and a floor keeps the Portfolio Manager's already-screened
  picks from being zeroed out by noise in the return estimate.
* **Two separate, clearly-labeled backward/forward numbers.** The
  historical backtest (`backtest.py`) replays the trailing window under
  the fixed optimized weights with a periodic rebalance — it can only
  ever describe what already happened. The 3-month projection
  (`forward_simulation.py`) is a genuinely forward-looking Monte Carlo
  simulation: thousands of correlated price paths (via a Cholesky
  factorization of the historical covariance matrix) drawn forward from
  today, reported as a return distribution (expected/median, a 5th-95th
  percentile band, probability of a positive return) rather than one
  falsely precise point forecast.
* **Treynor's a known blind spot under CAPM, and the memo says so.** A
  CAPM-priced portfolio's expected Treynor ratio `(E[r]-rf)/beta`
  algebraically collapses to the market risk premium for *any* beta —
  it can't discriminate between CAPM-consistent portfolios by
  construction. That's why Sharpe (which reflects total risk, i.e.
  diversification, not just systematic risk) drives the optimizer; the
  *realized* Treynor ratio from the historical backtest is the
  informative Treynor number this workflow reports.
* **Same fully-offline default as everything else.** Without `--live`,
  `SimulatedFeed` (with a longer, ~1-year window than the single-symbol
  commands' default) stands in for real prices/fundamentals — useful for
  exercising the whole pipeline with zero network/API dependencies, but
  the resulting picks are a demo of the *mechanism*, not a real
  recommendation; the rendered memo says so explicitly in its own
  caveats section. `tests/test_portfolio_*.py` cover every stage
  offline and deterministically.

**Research/education tool. Not investment advice.** No system here can
guarantee profit; see the memo's own "Caveats" section for what this
number, specifically, cannot promise.

## Macro & deeper fundamentals

`FundamentalAnalyst` (`agents/analysts.py`) reads far more than P/E and
revenue growth when `YFinanceFeed` supplies it: forward P/E, return on
equity, profit margin, debt/equity, dividend yield, sector, and — when
Yahoo exposes it for a ticker — sell-side analyst recommendation counts.
Every field is optional and independently scored; a missing one is
simply skipped, not an error.

`MacroAnalyst` is a fifth analyst reading market-wide context instead of
anything company-specific: the 10-year Treasury yield (rate regime),
VIX (risk-on/risk-off), and the dollar index — the same separation a
trading desk draws between a stock analyst and a macro/rates desk. These
are market-based *proxies*, not official releases (CPI/GDP/unemployment
data isn't wired in). `data/macro.py`'s `StaticMacroProvider` (all-None,
"no signal") is the offline default; `YFinanceMacroProvider` supplies
real values once `--live` is set — same optional/graceful-fallback
pattern as everything else.

## Journal & reflection (bounded feedback, not self-modifying strategy)

Every booked decision is automatically documented — the rationale (why)
and the resulting portfolio state (what changed) — via
`engine/journal.TradeJournal`, an append-only JSONL file
(`trading_agent_journal.jsonl` by default, `TRADING_AGENT_JOURNAL_PATH`
to change it). Nothing needs to be transcribed by hand.

When a booked decision closes/reduces/stops out a position (realizes a
PnL), `engine/journal.record_execution` also appends a short,
deterministically-worded note to `engine/memory.ReflectionMemory`
(`trading_agent_memory.json`). `TradingCycle` resurfaces the most recent
few of these for the symbol being analyzed as extra context in the
trader's LLM narration (`agents/trader.py`'s `recent_lessons` param) —
"here's how this symbol's last few closed trades went." That's the
entire adaptation loop this project implements, and deliberately the
only kind: it can only ever change *narrated text*, never the actual
action/target/stop/tranche math, `RiskLimits`, or any analyst's scoring.
An LLM-in-the-loop mechanism that let recent outcomes silently retune the
hard-coded rules would be a much riskier, unsupervised thing this
project does not do.

## Tools (`trading_agent/tools/`)

`tool_math.py` / `tool_trade.py` / `tool_get_price_local.py` /
`tool_jina_search.py` mirror the tool-chain naming from
[AI-Trader](https://github.com/HKUDS/AI-Trader), the multi-model-
competition project this design was asked to draw ideas from. **One
deliberate difference:** in AI-Trader an LLM calls these kinds of tools
itself, autonomously, via MCP. Nothing here is exposed to an LLM as a
callable function — each module is a plain function other *code* (CLI,
loops, scripts) calls. Giving a model direct tool-calling authority over
`tool_trade.py` would collapse this project's core separation (analysts
compute scores, code decides execution) back into the exact "AI decides
and executes with no oversight" pattern its guardrails exist to prevent.
`tool_jina_search.py` is optional (needs `JINA_API_KEY`, stdlib
`urllib` only, no new dependency) — `SentimentAnalyst` already has a
working, keyless news source via `YFinanceFeed`'s own `ticker.news`.

## Web UI (`trading_agent/webapp/`)

A browser control panel over the same three modes the CLI has
(signal/watch/backtest) — nothing in `agents/`, `engine/`, or `data/`
was changed to build it; it's a new layer on top:

```bash
pip install -r requirements-web.txt
python -m trading_agent.webapp
# → http://127.0.0.1:8000
```

* **Backend**: FastAPI + a WebSocket per session (`server.py`).
  `session.SessionRunner` runs the pipeline in a background thread and
  emits typed events (`status`, `thought`, `tick`/`decision`,
  `portfolio`, `final_report`, `error`) onto a thread-safe queue; the
  WebSocket relays them to the browser and accepts
  `{"action": "start"|"pause"|"resume"|"stop"|"reset"}` control
  messages. Chose FastAPI/WebSocket over Streamlit/Gradio because the
  interactive requirement here — pause a running loop, watch a
  multi-stage pipeline stream in real time — needs a real bidirectional
  connection, not a rerun-the-whole-script model.
* **Frontend**: one dependency-free HTML/CSS/JS page
  (`static/index.html`, no build step) — reasonable for a single-
  operator internal tool; React/Next.js would be the natural upgrade if
  this ever needs to be a multi-user product.
* **Non-breaking integration**: `TradingCycle.run_cycle_with_snapshot`
  gained an optional `on_stage(name, payload)` hook (default `None`,
  zero behavior change for every existing caller) so the session layer
  can stream each analyst report / debate stage / risk verdict as it's
  actually computed, rather than faking progress after the fact.
* **Execution stays autonomous**, same as the CLI: Start/Pause/Stop are
  process controls, not a trade-by-trade approval gate — see
  `engine/paper_broker.py` for why that's fine here.
* **Export**: JSON/CSV/Markdown via REST endpoints
  (`/api/sessions/{id}/export.{json,csv,md}`); PDF via the browser's own
  print dialog (a print stylesheet hides the control panel) rather than
  a new PDF-generation dependency.
* Tests: `tests/test_webapp_session.py` runs `SessionRunner` directly
  (no server, no browser); `tests/test_webapp_server.py` drives the
  REST + WebSocket endpoints with FastAPI's `TestClient`. Both skip
  cleanly if `requirements-web.txt` isn't installed. The full flow
  (create → start → pause → resume → stop, all three modes, exports)
  was also verified with a real headless-browser pass during
  development.

## Tests

```bash
pytest
```

Tests run fully offline against `DummyLLMClient` and `SimulatedFeed` (a
deterministic pseudo-random-walk price generator) — no network or API
key required.

## Extending this

* Any market-data vendor beyond Yahoo Finance can be added the same way
  `YFinanceFeed` was: implement `MarketDataProvider.get_snapshot()`. Same
  for macro data via `MacroDataProvider`.
* Adjust `RiskLimits` in `config.py` deliberately and explicitly if a
  higher ceiling is truly intended — do not raise it to make a specific
  trade plan pass.
* Any other forecasting backend can replace Kronos the same way it
  replaces the heuristic: implement `forecast.base.PriceForecaster`
  and pass it into `TradingCycle(..., forecaster=...)`.
* Other reasonable additions not built here: a multi-symbol watchlist
  (`watch`/`backtest` currently follow one symbol each), desktop/webhook
  alerts on new pending decisions or stop-outs, exporting
  `PaperBroker.trade_log`/the journal to CSV, and running several
  LLM/forecaster configurations side by side to compare their equity
  curves (a same-capital, same-data, same-tools comparison, the way
  AI-Trader pits different models against each other) — worth building
  only if it stays a comparison of the *analysis*, never a reason to let
  any of them reach a real brokerage connection unsupervised.
