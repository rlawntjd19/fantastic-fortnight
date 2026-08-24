import type { StrategyPreset } from './types';

/**
 * Every strategy sees the exact same 5 analysts, the exact same market data, and the
 * exact same hard risk limits (see risk.ts). The only thing a "strategy" controls is
 * how much each analyst's vote counts toward the consensus signal fed to the trader.
 */
export const STRATEGY_PRESETS: Record<string, StrategyPreset> = {
  balanced: {
    key: 'balanced', name: '균형 · 멀티팩터', colorVar: '--muted',
    weights: { technical_analyst: 1, fundamental_analyst: 1, sentiment_analyst: 1, macro_analyst: 1, forecast_analyst: 1 },
  },
  momentum: {
    key: 'momentum', name: '모멘텀 · 추세추종', colorVar: '--strategy-momentum',
    weights: { technical_analyst: 2.0, fundamental_analyst: 0.3, sentiment_analyst: 0.6, macro_analyst: 0.4, forecast_analyst: 1.6 },
  },
  value: {
    key: 'value', name: '가치 · 펀더멘털', colorVar: '--strategy-value',
    weights: { technical_analyst: 0.4, fundamental_analyst: 2.2, sentiment_analyst: 0.5, macro_analyst: 0.6, forecast_analyst: 0.5 },
  },
  macro: {
    key: 'macro', name: '매크로 · 거시경제', colorVar: '--strategy-macro',
    weights: { technical_analyst: 0.6, fundamental_analyst: 0.5, sentiment_analyst: 0.8, macro_analyst: 2.2, forecast_analyst: 0.6 },
  },
};

export const STRATEGY_KEYS = Object.keys(STRATEGY_PRESETS);
