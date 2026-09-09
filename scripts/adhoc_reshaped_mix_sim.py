"""One-off: Monte Carlo simulation of the reshaped 5-asset mix proposed to
the user (QQQM 35% / SPYG 20% / NBIS 15% / CRWV 15% / SMH 15%) over a
3-month (63 trading day) horizon, matching the mandate's hold window.

Uses a joint bootstrap: each simulated day resamples one *actual* historical
trading day's returns across all five tickers simultaneously (not each
ticker independently), so real historical cross-asset correlation is
preserved rather than assumed away. Never fabricates a return distribution
-- every input number is a real daily close-to-close return pulled from
yfinance. Not a permanent part of the pipeline; prints results to the job
log for a human to read, then this script and its workflow get deleted.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import numpy as np
import pandas as pd
import yfinance as yf

WEIGHTS = {
    "QQQM": 0.35,
    "SPYG": 0.20,
    "NBIS": 0.15,
    "CRWV": 0.15,
    "SMH": 0.15,
}
HORIZON_DAYS = 63  # ~3 trading months, matching the mandate's hold window
N_SIMULATIONS = 20_000
HISTORY_PERIOD = "2y"
SEED = 42


def fetch_daily_returns() -> pd.DataFrame:
    frames = {}
    for symbol in WEIGHTS:
        hist = yf.Ticker(symbol).history(period=HISTORY_PERIOD, interval="1d")
        if hist.empty:
            raise RuntimeError(f"no history returned for {symbol}")
        frames[symbol] = hist["Close"].pct_change().dropna()
    # Align on shared trading days only, so each row is one real joint day.
    df = pd.DataFrame(frames).dropna()
    return df


def main() -> None:
    returns = fetch_daily_returns()
    symbols = list(WEIGHTS.keys())
    weights = np.array([WEIGHTS[s] for s in symbols])

    print("=" * 60)
    print(f"Real daily-return history: {len(returns)} shared trading days "
          f"({returns.index[0].date()} to {returns.index[-1].date()})")
    print("=" * 60)

    print("\nPer-asset real stats over that window:")
    for s in symbols:
        ann_return = returns[s].mean() * 252
        ann_vol = returns[s].std() * np.sqrt(252)
        print(f"  {s}: weight={WEIGHTS[s]:.0%}  ann.return={ann_return:+.1%}  ann.vol={ann_vol:.1%}")

    corr = returns.corr()
    print("\nReal correlation matrix:")
    print(corr.round(2).to_string())

    rng = np.random.default_rng(SEED)
    n_days = len(returns)
    returns_matrix = returns[symbols].to_numpy()

    # Joint bootstrap: for each simulated path, draw HORIZON_DAYS actual
    # historical day-indices (with replacement) and apply that day's *real*
    # joint return vector across all five assets -- preserves real
    # cross-asset correlation structure instead of sampling each
    # asset independently (which would erase it).
    day_indices = rng.integers(0, n_days, size=(N_SIMULATIONS, HORIZON_DAYS))
    sampled_returns = returns_matrix[day_indices]  # (N_SIMULATIONS, HORIZON_DAYS, n_assets)

    asset_growth = np.prod(1.0 + sampled_returns, axis=1)  # (N_SIMULATIONS, n_assets)
    portfolio_growth = asset_growth @ weights  # (N_SIMULATIONS,)
    portfolio_return = portfolio_growth - 1.0

    percentiles = [5, 10, 25, 50, 75, 90, 95]
    pct_values = np.percentile(portfolio_return, percentiles)

    print("\n" + "=" * 60)
    print(f"Portfolio Monte Carlo: {N_SIMULATIONS:,} trials, {HORIZON_DAYS}-trading-day "
          f"(~3 month) horizon, joint historical bootstrap")
    print("=" * 60)
    print(f"\nExpected (mean) return: {portfolio_return.mean():+.2%}")
    print(f"Median return:          {np.median(portfolio_return):+.2%}")
    print(f"Std dev of return:      {portfolio_return.std():.2%}")
    print(f"P(loss):                {(portfolio_return < 0).mean():.1%}")
    print(f"P(return < -10%):       {(portfolio_return < -0.10).mean():.1%}")
    print(f"P(return < -20%):       {(portfolio_return < -0.20).mean():.1%}")
    print(f"P(return > +10pp vs 0): {(portfolio_return > 0.10).mean():.1%}")

    print("\nPercentile distribution of 3-month portfolio return:")
    for p, v in zip(percentiles, pct_values):
        print(f"  p{p:>2}: {v:+.2%}")

    # Also report the un-reshaped 40/30/30-style comparison isn't needed;
    # instead report per-asset contribution to variance for context.
    print("\nPer-asset marginal contribution (weight x annualized vol, for context):")
    for s in symbols:
        ann_vol = returns[s].std() * np.sqrt(252)
        print(f"  {s}: {WEIGHTS[s]:.0%} x {ann_vol:.1%} = {WEIGHTS[s] * ann_vol:.1%}")


if __name__ == "__main__":
    main()
