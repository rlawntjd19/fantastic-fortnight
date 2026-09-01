# Daily equity research committee

A team of AI equity-research-analyst agents that runs every US market
weekday and maintains a standing shortlist of **2-5 US stocks and/or
broad-market index ETFs**, sized for a **2-3 month holding horizon**, with
the explicit (if admittedly very ambitious) OKR of **beating SPY by
10-15 percentage points** over that horizon. Code lives in
`trading_agent/committee/`; this file is the design write-up, parallel to
the main [README.md](../README.md) for the rest of the repo.

> Research/education tool. Not investment advice. No system can guarantee
> outperformance — a 10-15pp-over-SPY OKR is a stretch target to aim the
> process at, not a promise this process (or any process) can deliver.

## Why a committee, not one model call

Same reasoning as the rest of this repo (see the main README's "Why this
shape"): a single LLM call guessing "buy this" collapses market analysis,
screening, and portfolio construction into one unaccountable step. This
module keeps them separate and, critically, **keeps every score
code-computed** — the LLM (when `ANTHROPIC_API_KEY` is set) only narrates
numbers that are already final; with no key set it runs the exact same
pipeline against `DummyLLMClient`'s offline stub text, same as everywhere
else in this project.

## The team

| Role | Class | Scope |
|---|---|---|
| Technical analyst | `agents.analysts.TechnicalAnalyst` | SMA trend, RSI, 10-bar momentum |
| Fundamental analyst | `agents.analysts.FundamentalAnalyst` | P/E, growth, ROE, margins, leverage, analyst consensus |
| Sentiment analyst | `agents.analysts.SentimentAnalyst` | Recent headlines |
| Macro analyst | `agents.analysts.MacroAnalyst` | 10Y yield, VIX, dollar index |
| Forecast analyst | `agents.analysts.ForecastAnalyst` | Heuristic (or Kronos, if installed) price-path forecast |
| Research manager | `agents.researchers.ResearchManager` | Bull/bear debate → one consensus signal per symbol |
| **Portfolio manager (CIO)** | `committee.portfolio_manager.PortfolioManager` | Ranks every symbol's consensus into the final 2-5 name basket |

The first six are reused unchanged from `trading_agent/agents/` — this
module is a portfolio-level layer on top of the same per-symbol research
pipeline the rest of the repo uses for single-symbol trade decisions,
not a rewrite of it.

## Chain of thought: how the CIO picks

Every day's `PortfolioManager.select()` call runs the exact same six-step
sequence, logged verbatim into that day's report so the reasoning is
auditable, not just the output:

1. **Universe screen** (upstream, `committee/universe.py`) — every
   candidate must already be a NYSE/AMEX/NASDAQ-listed stock, ADR, or ETF;
   not an open-end mutual fund (5-letter ticker ending in `X`); not a raw
   index ticker; priced above $5.00/share; and above $2B market cap for
   stocks (well above the $500M rubric floor, in line with the mandate's
   "no small-cap" instruction) or $500M AUM for ETFs.
2. **Exclude already-held names** — the committee rotates the standing
   basket, it doesn't double up on a symbol already open.
3. **Directional filter** — only candidates with a net-**bullish**
   committee consensus survive.
4. **Rank by composite conviction** — see scoring below.
5. **Diversification cap** — at most 2 new picks per sector per run, so
   the basket isn't one sector's beta in disguise.
6. **Floor relaxation** — if fewer than 2 bullish names exist basket-wide,
   the floor is filled with the highest-scoring *non-bearish* names
   instead, explicitly flagged `low` conviction rather than silently
   promoted to look the same as a real bullish call.

## Scoring (code, not the LLM)

```
composite_score = 0.6 * desk_consensus_component + 0.4 * relative_strength_component
```

* `desk_consensus_component` = consensus direction × consensus confidence ×
  (0.5 + 0.5 × cross-desk agreement fraction) — the same weighted-vote math
  `ResearchManager` already uses, with an extra bonus/penalty for how many
  of the five desks actually agree with the consensus direction.
* `relative_strength_component` = the symbol's 10-bar momentum minus SPY's
  10-bar momentum, clamped to ±1 at a ±10pp spread — this is what points
  the whole process at *outperformance* specifically, not just "is this
  going up."

## Tracking the OKR

Every open position is persisted in `research_team/state/portfolio.json`
(`committee/performance_tracker.py`) with its entry price **and** SPY's
price on the same entry date. Each day's run:

1. Marks every open position and SPY to the latest price.
2. Computes `alpha_pct = position_return − SPY_return` since entry, per
   position and averaged across the basket.
3. Re-underwrites every held symbol with the full analyst desk; a name
   whose consensus flips bearish is closed immediately with the reason
   logged (`exit_reason`), not held out of inertia.
4. Closes any position held past ~95 days (past the 2-3 month mandate)
   even with no bearish signal, on schedule rather than indefinitely.

That scoreboard is the first table in every day's report — it's the
running, checkable answer to "are we actually beating SPY by 10-15pp," not
a one-time backtest number.

## The 9/7 window

`committee/daily_report.RESEARCH_WINDOW_END = 2026-09-07`. On or before
that date, the committee screens the full universe for new/replacement
picks every run. After it, `run_daily_cycle` stops screening for new
entries but keeps marking the existing basket to market — the OKR needs
tracking to continue after picking stops, so mark-to-market doesn't turn
off just because the pick-selection mandate's window has closed.

## Running it

```bash
# One offline dry run (SimulatedFeed, no network, no API key) — same
# pattern the rest of this repo uses for tests/demos:
python -m trading_agent.cli daily-picks

# Real market data:
pip install -r requirements-live.txt
python -m trading_agent.cli daily-picks --live
```

**Every real pick must be priced with live data** — so `daily-picks`
without `--live` never writes into the tracked `research_team/reports/`
or `research_team/state/portfolio.json`: it's automatically redirected to
`research_team/reports/_dry_run/` and `research_team/state/_dry_run_portfolio.json`
instead (both gitignored), and refuses outright if you explicitly point
`--out-dir`/`--state-path` at the real ones without `--live`. This repo's
own history briefly had a real bug from this exact mistake — an early
offline dry run got committed into the tracked state with fake prices,
which would have silently corrupted the alpha-vs-SPY math once live runs
started layering on top of it — hence the hard guard now, not just a
docs warning.

Offline mode is still useful for a fast dry run/CI smoke test, but it's
worth knowing what it can't check: `SimulatedFeed` doesn't expose
`market_cap`/`exchange`/`total_assets`, so the exclusion rules in
`committee/universe.screen_ineligible` that key off those fields never
trigger offline — every candidate passes screening (a missing field is
"can't verify, don't block", the same defensive pattern the rest of this
repo's analysts use for fundamentals). The eligibility rubric is only
actually enforced once `--live` data is flowing, which is what the GitHub
Actions runner below uses.

A `--live` run writes `research_team/reports/YYYY-MM-DD_HHMMZ.md` (+ a
parallel `.json`, timestamped since the pipeline runs 5x a day now, not
once) and overwrites `research_team/LATEST_PICKS.md` with the same
content, and persists the standing basket to
`research_team/state/portfolio.json`. A dry run (no `--live`) uses the
plain `YYYY-MM-DD.md` name instead, inside the gitignored `_dry_run/`
path — see the guard described above.

## Keeping it running, 5x a day, without a live session

`.github/workflows/daily_research.yml` runs `daily-picks --live` five
times across every US market weekday — 9:35am, 11:00am, 12:30pm, 2:00pm,
and 3:45pm ET, spread across the trading session rather than one snapshot
at the open — and commits each report back to this branch. This is what
actually satisfies "run 5x a day," rather than relying on any one chat
session staying open, and every run is real data or nothing:
`cli._run_daily_picks` refuses outright (no report written) if `--live`
was requested but the live market-data provider couldn't actually be
built, instead of silently falling back to simulated prices. It works
with **no** `ANTHROPIC_API_KEY` secret configured (offline narrative
stub, same deterministic scoring); add that secret in the repo's Settings
→ Secrets if real narrative text is wanted. Trigger it manually any time
from the Actions tab (`workflow_dispatch`) instead of waiting for the
next scheduled run.

## Tests

```bash
pytest tests/test_committee.py
```

Fully offline (`SimulatedFeed` + `DummyLLMClient` + `StaticMacroProvider` +
`HeuristicForecaster`), same as the rest of this repo's test suite.
