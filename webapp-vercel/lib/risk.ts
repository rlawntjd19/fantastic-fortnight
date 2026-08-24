import type { RiskVerdict, TradePlan } from './types';

/**
 * Hard risk ceilings. Identical for every fund, every strategy, every tick — nothing
 * in this file is adjustable by an analyst, a strategy weight, or the autonomous
 * screening loop. This is the one place "autonomy" stops.
 */
export const RISK_LIMITS = {
  maxLeverage: 3.0,
  maxPositionPct: 0.10,
  maxStopLossPct: 0.05,
  maxTranches: 3,
  dailyCircuitBreakerPct: 0.05,
};

export class DailyCircuitBreaker {
  constructor(private startingEquity: number, private limitPct: number) {}
  tripped(currentEquity: number): boolean {
    if (this.startingEquity <= 0) return false;
    return (this.startingEquity - currentEquity) / this.startingEquity >= this.limitPct;
  }
}

export function trailingStopPrice(quantity: number, currentStop: number, currentPrice: number, pct: number): number {
  if (quantity > 0) return Math.max(currentStop, currentPrice * (1 - pct));
  return Math.min(currentStop, currentPrice * (1 + pct));
}

export function enforceHardLimits(plan: TradePlan, accountEquity: number, circuitBreaker: DailyCircuitBreaker | null): RiskVerdict {
  if (plan.action === 'hold') {
    return { approved: true, adjusted_leverage: 0, adjusted_position_pct_of_equity: 0, violations_corrected: [], notes: 'No position change proposed.' };
  }
  if (plan.action === 'close') {
    return { approved: true, adjusted_leverage: 0, adjusted_position_pct_of_equity: 0, violations_corrected: [], notes: 'Closing an existing position is always allowed, including while the circuit breaker is tripped.' };
  }
  if (circuitBreaker && circuitBreaker.tripped(accountEquity)) {
    return {
      approved: false, adjusted_leverage: 0, adjusted_position_pct_of_equity: 0,
      violations_corrected: ['daily_circuit_breaker'],
      notes: 'Daily loss circuit breaker is tripped; only closing existing positions is allowed until it resets.',
    };
  }
  const violations: string[] = [];
  let adjustedLeverage = plan.leverage;
  if (adjustedLeverage > RISK_LIMITS.maxLeverage) {
    violations.push(`leverage ${adjustedLeverage}x > max ${RISK_LIMITS.maxLeverage}x, clamped`);
    adjustedLeverage = RISK_LIMITS.maxLeverage;
  }
  const requestedPct = plan.tranche_sizes.length ? 1 / plan.tranche_sizes.length : 1.0;
  let adjustedPct = Math.min(1.0, requestedPct * plan.tranche_sizes.length);
  if (adjustedPct > RISK_LIMITS.maxPositionPct) {
    violations.push(`position size ${(adjustedPct * 100).toFixed(1)}% of equity > max ${(RISK_LIMITS.maxPositionPct * 100).toFixed(1)}%, clamped`);
    adjustedPct = RISK_LIMITS.maxPositionPct;
  }
  if (plan.tranche_sizes.length > RISK_LIMITS.maxTranches) {
    violations.push(`${plan.tranche_sizes.length} tranches > max ${RISK_LIMITS.maxTranches}, will be truncated`);
  }
  const stopPct = Math.abs(plan.entry_price - plan.stop_loss_price) / plan.entry_price;
  if (stopPct > RISK_LIMITS.maxStopLossPct) violations.push(`stop distance ${(stopPct * 100).toFixed(1)}% > max ${(RISK_LIMITS.maxStopLossPct * 100).toFixed(1)}%`);
  if (stopPct === 0) violations.push('no stop loss set on a directional trade');
  const approved = !violations.some((v) => v.startsWith('no stop loss'));
  return {
    approved, adjusted_leverage: adjustedLeverage, adjusted_position_pct_of_equity: adjustedPct,
    violations_corrected: violations, notes: 'Hard limits enforced in code; the trade plan is clamped to fit.',
  };
}
