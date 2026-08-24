import { sampleStdev } from './indicators';

export interface PerformanceReport {
  starting_equity: number;
  ending_equity: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  win_rate: number | null;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  num_closed_trades: number;
}

export function computePerformance(equityCurve: number[], tradePnls: number[]): PerformanceReport {
  if (!equityCurve.length) throw new Error('equityCurve must have at least one point');
  const starting = equityCurve[0];
  const ending = equityCurve[equityCurve.length - 1];
  const totalReturnPct = starting ? ending / starting - 1 : 0;
  let peak = equityCurve[0], maxDrawdown = 0;
  for (const e of equityCurve) {
    peak = Math.max(peak, e);
    if (peak > 0) maxDrawdown = Math.max(maxDrawdown, (peak - e) / peak);
  }
  const periodReturns: number[] = [];
  for (let i = 1; i < equityCurve.length; i++) if (equityCurve[i - 1] !== 0) periodReturns.push(equityCurve[i] / equityCurve[i - 1] - 1);
  let winRate: number | null = null;
  if (tradePnls.length) winRate = tradePnls.filter((p) => p > 0).length / tradePnls.length;

  function sharpe(returns: number[]): number | null {
    if (returns.length < 2) return null;
    const sd = sampleStdev(returns);
    if (sd === 0) return null;
    const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
    return (mean / sd) * Math.sqrt(returns.length);
  }
  function sortino(returns: number[]): number | null {
    if (returns.length < 2) return null;
    const downside = returns.map((r) => Math.min(0, r));
    const dsd = Math.sqrt(downside.reduce((s, d) => s + d * d, 0) / (downside.length - 1));
    if (dsd === 0) return null;
    const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
    return (mean / dsd) * Math.sqrt(returns.length);
  }

  return {
    starting_equity: starting, ending_equity: ending, total_return_pct: totalReturnPct, max_drawdown_pct: maxDrawdown,
    win_rate: winRate, sharpe_ratio: sharpe(periodReturns), sortino_ratio: sortino(periodReturns), num_closed_trades: tradePnls.length,
  };
}
