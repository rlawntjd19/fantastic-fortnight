"""Historical backtest of the committee's actual selection and conviction/
volatility position-sizing logic — real evidence for whether this
strategy's signals carry forward-return information, instead of trusting
the live design's face value.

Each trial: pick an entry date, screen the universe and select a basket
exactly as `daily_report.run_daily_cycle` does (same `assess_symbol`,
`PortfolioManager.select`, and `performance_tracker`-style conviction/
volatility sizing), hold that basket unrebalanced for a fixed horizon,
then mark it to market and compute alpha vs. SPY over the identical
window. Repeated across many historical dates to build a distribution,
not a single anecdote.

No-lookahead discipline: every trial only ever sees price/macro bars
timestamped at or before its entry date (`SymbolHistory.bars_as_of`,
`TimeSeries.as_of`/`change_over`) — the same "can't leak a future bar"
property `engine/backtest.ReplayFeed` already enforces for the
single-symbol trader, applied here across an entire universe screen.

Known, deliberate simplifications — real, not hidden in a footnote:

* **No point-in-time fundamentals or news.** This project's data source
  (yfinance) only exposes *current* fundamentals/news, not what was known
  on a past date — feeding today's numbers into a historical trial would
  be lookahead bias, so instead `fundamental_analyst` and
  `sentiment_analyst` see an empty snapshot and correctly report
  neutral/no-signal, the exact same graceful degradation those desks
  already use for any missing field live. Composite scores here are
  driven by technical + macro + forecast only. A live run's composite
  score can differ because those two desks *do* contribute when the data
  exists — so this backtest is evidence about the technical/macro/
  momentum portion of the signal, not a perfect replica of live scoring.
* **No point-in-time market cap or ETF AUM.** The universe's cap/AUM
  floor isn't re-verified historically; `UNIVERSE` is already curated to
  mega/large-cap names that were almost certainly above that floor
  throughout the backtest window too. The price floor *is* checked with
  real historical prices.
* **Fixed-horizon hold, not the live rotating basket.** Each trial buys
  the CIO's picks at entry and holds them unrebalanced for exactly
  `hold_bars` trading days — no dynamic thesis-break exit, no ~95-day
  cutoff. This tests the selection+sizing signal's raw forward-return
  efficacy in isolation; it is not a full replay of the live multi-day
  rotation state machine.
* **Overlapping windows are correlated.** `step_bars` defaults to
  `hold_bars` (non-overlapping, closer to independent draws). Passing a
  smaller `step_bars` gives more trials for a denser picture, but they
  will share underlying price history and shouldn't be treated as that
  many independent samples.
"""
from __future__ import annotations

import bisect
import datetime as dt
from dataclasses import dataclass, field

from trading_agent.agents.analysts import (
    FundamentalAnalyst,
    MacroAnalyst,
    SentimentAnalyst,
    TechnicalAnalyst,
    ForecastAnalyst,
)
from trading_agent.agents.researchers import ResearchManager
from trading_agent.committee.daily_report import OKR_TARGET_LOW_PP, assess_symbol
from trading_agent.committee.performance_tracker import compute_weights
from trading_agent.committee.portfolio_manager import PortfolioManager
from trading_agent.committee.schemas import CandidateAssessment
from trading_agent.committee.universe import BENCHMARK_SYMBOL, UNIVERSE, screen_ineligible
from trading_agent.data.indicators import momentum
from trading_agent.data.macro import MacroSnapshot
from trading_agent.data.providers import Bar, MarketSnapshot
from trading_agent.forecast.base import PriceForecaster
from trading_agent.llm.client import LLMClient

# Warm-up bars every analyst needs before its indicators (SMA30, RSI14,
# momentum10, the new volatility20) produce a real number instead of None.
_MIN_WARMUP_BARS = 35


@dataclass
class TimeSeries:
    """A sorted (timestamp, value) series with as-of lookups — the
    no-lookahead primitive for macro data (`HistoricalMacroProvider`)."""

    dates: list[int]
    values: list[float]

    def as_of(self, ts: int) -> float | None:
        idx = bisect.bisect_right(self.dates, ts) - 1
        return self.values[idx] if idx >= 0 else None

    def change_over(self, ts: int, lookback_bars: int = 21) -> float | None:
        idx = bisect.bisect_right(self.dates, ts) - 1
        if idx < lookback_bars:
            return None
        base = self.values[idx - lookback_bars]
        if base == 0:
            return None
        return self.values[idx] / base - 1.0


@dataclass
class MacroHistory:
    ten_year: TimeSeries
    vix: TimeSeries
    dollar: TimeSeries


class HistoricalMacroProvider:
    """`MacroDataProvider` backed by a fixed as-of date into `MacroHistory`
    — a drop-in for `MacroAnalyst`, same protocol `YFinanceMacroProvider`/
    `StaticMacroProvider` implement live."""

    def __init__(self, macro: MacroHistory, as_of_ts: int) -> None:
        self._macro = macro
        self._ts = as_of_ts

    def get_macro_snapshot(self) -> MacroSnapshot:
        return MacroSnapshot(
            ten_year_yield_pct=self._macro.ten_year.as_of(self._ts),
            ten_year_yield_change_pct=self._macro.ten_year.change_over(self._ts),
            vix_level=self._macro.vix.as_of(self._ts),
            dollar_index_change_pct=self._macro.dollar.change_over(self._ts),
        )


@dataclass
class SymbolHistory:
    symbol: str
    security_type: str
    sector: str
    bars: list[Bar]
    timestamps: list[int] = field(init=False)

    def __post_init__(self) -> None:
        self.timestamps = [b.timestamp for b in self.bars]

    def bars_as_of(self, cutoff_ts: int) -> list[Bar]:
        idx = bisect.bisect_right(self.timestamps, cutoff_ts)
        return self.bars[:idx]

    def price_at_or_after(self, ts: int) -> float | None:
        idx = bisect.bisect_left(self.timestamps, ts)
        return self.bars[idx].close if idx < len(self.bars) else None


@dataclass
class BacktestData:
    symbols: dict[str, SymbolHistory]
    macro: MacroHistory


@dataclass
class TrialPick:
    symbol: str
    entry_price: float
    exit_price: float
    weight_pct: float
    return_pct: float


@dataclass
class TrialResult:
    entry_date: str
    exit_date: str
    picks: list[TrialPick]
    basket_return_pct: float
    spy_return_pct: float
    alpha_pct: float
    universe_screened: int


@dataclass
class BacktestReport:
    hold_bars: int
    step_bars: int
    min_picks: int = 2
    max_picks: int = 5
    trials: list[TrialResult] = field(default_factory=list)


def _iso_date(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date().isoformat()


def _weighted_alpha(weighted_returns: list[tuple[float, float]], spy_return: float) -> tuple[float, float]:
    """Pure math, kept separate from the analyst pipeline so it's directly
    unit-testable with exact numbers: basket return = Σ weight·return,
    alpha = basket return − benchmark return."""
    basket_return = sum(weight * ret for weight, ret in weighted_returns)
    return basket_return, basket_return - spy_return


def fetch_backtest_data(period: str = "2y") -> BacktestData:
    """Fetches real historical daily bars for the whole committee universe
    plus macro proxies. Requires `yfinance` and real network access —
    there is no offline/simulated mode here, deliberately: a backtest
    built on fake prices would be evidence about nothing."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError(
            "yfinance가 설치되어 있지 않습니다. 설치하려면:\n  pip install -r requirements-live.txt"
        ) from exc

    symbols: dict[str, SymbolHistory] = {}
    for entry in UNIVERSE:
        history = yf.Ticker(entry.symbol).history(period=period, interval="1d")
        if history.empty:
            continue
        bars = [
            Bar(
                timestamp=int(ts.timestamp()),
                open=float(row.Open),
                high=float(row.High),
                low=float(row.Low),
                close=float(row.Close),
                volume=float(row.Volume),
            )
            for ts, row in history.iterrows()
        ]
        symbols[entry.symbol] = SymbolHistory(entry.symbol, entry.security_type, entry.sector, bars)

    if BENCHMARK_SYMBOL not in symbols:
        raise RuntimeError(f"could not fetch {BENCHMARK_SYMBOL} history; a backtest needs the benchmark")

    macro = _fetch_macro_history(period)
    return BacktestData(symbols=symbols, macro=macro)


def _fetch_macro_history(period: str) -> MacroHistory:
    import yfinance as yf

    def series(ticker: str) -> TimeSeries:
        history = yf.Ticker(ticker).history(period=period, interval="1d")
        return TimeSeries(
            dates=[int(ts.timestamp()) for ts in history.index],
            values=[float(v) for v in history["Close"]],
        )

    return MacroHistory(ten_year=series("^TNX"), vix=series("^VIX"), dollar=series("DX-Y.NYB"))


def _run_trial(
    data: BacktestData,
    entry_index: int,
    exit_index: int,
    llm: LLMClient,
    forecaster: PriceForecaster,
    min_picks: int,
    max_picks: int,
) -> TrialResult | None:
    spy_history = data.symbols[BENCHMARK_SYMBOL]
    if exit_index >= len(spy_history.bars):
        return None
    entry_ts = spy_history.bars[entry_index].timestamp
    exit_ts = spy_history.bars[exit_index].timestamp

    spy_bars_as_of = spy_history.bars_as_of(entry_ts)
    if len(spy_bars_as_of) < _MIN_WARMUP_BARS:
        return None
    spy_snapshot = MarketSnapshot(BENCHMARK_SYMBOL, spy_bars_as_of, {}, [])
    spy_momentum_val = momentum(spy_snapshot.closes, 10)
    spy_entry_price = spy_snapshot.last_price
    spy_exit_price = spy_history.price_at_or_after(exit_ts)
    if spy_exit_price is None:
        return None

    macro_provider = HistoricalMacroProvider(data.macro, entry_ts)
    analysts = {
        "technical": TechnicalAnalyst(llm),
        "fundamental": FundamentalAnalyst(llm),
        "sentiment": SentimentAnalyst(llm),
        "macro": MacroAnalyst(llm, macro_provider),
        "forecast": ForecastAnalyst(llm, forecaster),
    }
    research_manager = ResearchManager(llm)

    candidates: list[CandidateAssessment] = []
    for entry in UNIVERSE:
        history = data.symbols.get(entry.symbol)
        if history is None:
            continue
        bars = history.bars_as_of(entry_ts)
        if len(bars) < _MIN_WARMUP_BARS:
            continue
        snapshot = MarketSnapshot(entry.symbol, bars, {}, [])
        # fundamentals={} -> the cap/AUM/exchange checks can't verify and
        # skip (documented simplification above); the price floor still
        # uses this trial's real historical price.
        if screen_ineligible(entry, {}, snapshot.last_price):
            continue
        candidates.append(assess_symbol(entry, snapshot, spy_momentum_val, analysts, research_manager))

    cio = PortfolioManager(llm, min_picks=min_picks, max_picks=max_picks)
    picks, _rationale = cio.select(candidates, already_held=set(), slots_open=max_picks)
    if not picks:
        return None

    conviction_by_symbol = {c.symbol: c.composite_score for c in candidates}
    volatility_by_symbol = {c.symbol: c.volatility for c in candidates if c.volatility is not None}
    weights = compute_weights([p.symbol for p in picks], conviction_by_symbol, volatility_by_symbol)

    trial_picks: list[TrialPick] = []
    weighted_returns: list[tuple[float, float]] = []
    for pick in picks:
        history = data.symbols[pick.symbol]
        exit_price = history.price_at_or_after(exit_ts)
        if exit_price is None:
            continue
        weight = weights[pick.symbol]
        ret = exit_price / pick.entry_price - 1.0
        trial_picks.append(TrialPick(pick.symbol, pick.entry_price, exit_price, weight, ret))
        weighted_returns.append((weight, ret))

    if not trial_picks:
        return None

    spy_return = spy_exit_price / spy_entry_price - 1.0
    basket_return, alpha = _weighted_alpha(weighted_returns, spy_return)

    return TrialResult(
        entry_date=_iso_date(entry_ts),
        exit_date=_iso_date(exit_ts),
        picks=trial_picks,
        basket_return_pct=basket_return,
        spy_return_pct=spy_return,
        alpha_pct=alpha,
        universe_screened=len(candidates),
    )


def run_backtest(
    data: BacktestData,
    llm: LLMClient,
    forecaster: PriceForecaster,
    hold_bars: int = 63,
    step_bars: int | None = None,
    min_picks: int = 2,
    max_picks: int = 5,
) -> BacktestReport:
    """Runs trials from the earliest date with enough warm-up data through
    the end of `data`'s history minus `hold_bars`. `step_bars` defaults to
    `hold_bars` (non-overlapping trials); pass a smaller value for a
    denser but correlated picture."""
    step_bars = step_bars or hold_bars
    spy_history = data.symbols.get(BENCHMARK_SYMBOL)
    if spy_history is None:
        raise RuntimeError(f"{BENCHMARK_SYMBOL} history is required to run a backtest")

    trials: list[TrialResult] = []
    i = _MIN_WARMUP_BARS
    while i + hold_bars < len(spy_history.bars):
        trial = _run_trial(data, i, i + hold_bars, llm, forecaster, min_picks, max_picks)
        if trial is not None:
            trials.append(trial)
        i += step_bars

    return BacktestReport(
        hold_bars=hold_bars, step_bars=step_bars, min_picks=min_picks, max_picks=max_picks, trials=trials
    )


def summarize(report: BacktestReport) -> dict:
    alphas = [t.alpha_pct for t in report.trials]
    n = len(alphas)
    if n == 0:
        return {"n_trials": 0}

    mean_alpha = sum(alphas) / n
    sorted_alphas = sorted(alphas)
    median_alpha = (
        sorted_alphas[n // 2]
        if n % 2
        else (sorted_alphas[n // 2 - 1] + sorted_alphas[n // 2]) / 2
    )
    variance = sum((a - mean_alpha) ** 2 for a in alphas) / (n - 1) if n > 1 else 0.0

    return {
        "n_trials": n,
        "mean_alpha_pct": mean_alpha,
        "median_alpha_pct": median_alpha,
        "stdev_alpha_pct": variance**0.5,
        "win_rate": sum(1 for a in alphas if a > 0) / n,
        "hit_target_rate": sum(1 for a in alphas if a >= OKR_TARGET_LOW_PP / 100) / n,
        "best_alpha_pct": max(alphas),
        "worst_alpha_pct": min(alphas),
        "mean_basket_return_pct": sum(t.basket_return_pct for t in report.trials) / n,
        "mean_spy_return_pct": sum(t.spy_return_pct for t in report.trials) / n,
    }


def to_markdown(report: BacktestReport, summary: dict) -> str:
    lines: list[str] = []
    lines.append("# Committee backtest — evidence, not priors")
    lines.append("")
    lines.append(
        "> Research/education tool. Not investment advice. Read the methodology notes "
        "at the bottom before trusting any number here — this replays the committee's "
        "real selection and sizing logic, but fundamental/sentiment desks ran with no "
        "point-in-time data (neutral, same as any live run missing that field), and "
        "each trial is a fixed-horizon hold, not the live rotating basket."
    )
    lines.append("")
    lines.append(
        f"Hold horizon: **{report.hold_bars} trading days** (~{report.hold_bars / 21:.1f} months) · "
        f"Trial spacing: **{report.step_bars} trading days** "
        f"({'non-overlapping, independent draws' if report.step_bars >= report.hold_bars else 'overlapping — trials share price history, treat as correlated'}) · "
        f"Basket size: **{report.min_picks}-{report.max_picks} names**"
    )
    lines.append("")

    if summary["n_trials"] == 0:
        lines.append("No trials produced a basket — insufficient history or no eligible candidates.")
        return "\n".join(lines)

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Trials | {summary['n_trials']} |")
    lines.append(f"| Mean alpha vs SPY | {summary['mean_alpha_pct'] * 100:+.2f}pp |")
    lines.append(f"| Median alpha vs SPY | {summary['median_alpha_pct'] * 100:+.2f}pp |")
    lines.append(f"| Stdev of alpha | {summary['stdev_alpha_pct'] * 100:.2f}pp |")
    lines.append(f"| Win rate (alpha > 0) | {summary['win_rate'] * 100:.0f}% |")
    lines.append(f"| Hit +{OKR_TARGET_LOW_PP:.0f}pp target rate | {summary['hit_target_rate'] * 100:.0f}% |")
    lines.append(f"| Best trial | {summary['best_alpha_pct'] * 100:+.2f}pp |")
    lines.append(f"| Worst trial | {summary['worst_alpha_pct'] * 100:+.2f}pp |")
    lines.append(f"| Mean basket return | {summary['mean_basket_return_pct'] * 100:+.2f}% |")
    lines.append(f"| Mean SPY return (same windows) | {summary['mean_spy_return_pct'] * 100:+.2f}% |")
    lines.append("")

    lines.append("## Every trial")
    lines.append("")
    lines.append("| Entry | Exit | Picks | Basket Return | SPY Return | Alpha |")
    lines.append("|---|---|---|---:|---:|---:|")
    for t in report.trials:
        pick_str = ", ".join(f"{p.symbol} ({p.weight_pct * 100:.0f}%)" for p in t.picks)
        lines.append(
            f"| {t.entry_date} | {t.exit_date} | {pick_str} | {t.basket_return_pct * 100:+.2f}% | "
            f"{t.spy_return_pct * 100:+.2f}% | {t.alpha_pct * 100:+.2f}pp |"
        )
    lines.append("")

    lines.append("## Methodology and known simplifications")
    lines.append("")
    lines.append(
        "- **No point-in-time fundamentals/news**: this data source only exposes current "
        "values, so `fundamental_analyst`/`sentiment_analyst` saw an empty snapshot and "
        "reported neutral/no-signal for every trial — composite scores here reflect "
        "technical + macro + forecast only. A live run's score can differ since those two "
        "desks do contribute when the data exists."
    )
    lines.append(
        "- **No point-in-time market cap/AUM**: the universe's cap/AUM floor isn't "
        "re-verified historically (the price floor is, with real historical prices); "
        "`UNIVERSE` is already curated to names that were almost certainly large-cap "
        "throughout this window too."
    )
    lines.append(
        "- **Fixed-horizon hold**: each trial buys at entry and holds unrebalanced for "
        "exactly the hold horizon above — no dynamic thesis-break exit, no ~95-day cutoff. "
        "This measures the selection+sizing signal's raw forward-return efficacy, not a "
        "full replay of the live rotating basket."
    )
    lines.append("")
    return "\n".join(lines)
