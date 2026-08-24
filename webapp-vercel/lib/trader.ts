import type { ResearchDebateResult, TradePlan } from './types';

export function traderPropose(
  symbol: string,
  currentPrice: number,
  research: ResearchDebateResult,
  requestedLeverage: number,
  requestedTranches: number,
  recentLessons: string[],
): TradePlan {
  let action: TradePlan['action'], targetPrice: number, stopLossPrice: number;
  if (research.consensus_signal === 'bullish') {
    action = 'buy';
    targetPrice = currentPrice * (1 + 0.03 + 0.05 * research.consensus_confidence);
    stopLossPrice = currentPrice * (1 - 0.02 - 0.02 * (1 - research.consensus_confidence));
  } else if (research.consensus_signal === 'bearish') {
    action = 'sell';
    targetPrice = currentPrice * (1 - 0.03 - 0.05 * research.consensus_confidence);
    stopLossPrice = currentPrice * (1 + 0.02 + 0.02 * (1 - research.consensus_confidence));
  } else {
    action = 'hold';
    targetPrice = currentPrice;
    stopLossPrice = currentPrice;
  }
  const n = Math.max(1, requestedTranches);
  const trancheSizes = action !== 'hold' ? new Array(n).fill(1 / n) : [1.0];
  let rationale = research.rationale;
  if (recentLessons.length) rationale += ` (참고: ${recentLessons[recentLessons.length - 1]})`;
  return { symbol, action, entry_price: currentPrice, target_price: targetPrice, stop_loss_price: stopLossPrice, leverage: requestedLeverage, tranche_sizes: trancheSizes, rationale };
}

export function buildClosePlan(symbol: string, currentPrice: number, rationale: string): TradePlan {
  return { symbol, action: 'close', entry_price: currentPrice, target_price: currentPrice, stop_loss_price: currentPrice, leverage: 0, tranche_sizes: [], rationale };
}
