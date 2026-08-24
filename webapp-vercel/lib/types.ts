export interface Bar {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Fundamentals {
  pe_ratio?: number;
  forward_pe?: number;
  revenue_growth_yoy?: number;
  return_on_equity?: number;
  profit_margin?: number;
  debt_to_equity?: number;
}

export interface MacroSnapshot {
  ten_year_yield_change_pct: number | null;
  vix_level: number | null;
  dollar_index_change_pct: number | null;
}

export interface MarketSnapshot {
  symbol: string;
  bars: Bar[];
  fundamentals: Fundamentals;
  newsHeadlines: string[];
  macro: MacroSnapshot;
  lastPrice: number;
  closes: number[];
}

export type Signal = 'bullish' | 'bearish' | 'neutral';
export type Action = 'buy' | 'sell' | 'hold' | 'close';

export interface AnalystReport {
  agent_name: string;
  signal: Signal;
  confidence: number;
  summary: string;
  key_points: string[];
}

export interface ResearchDebateResult {
  bull_thesis: string;
  bear_thesis: string;
  consensus_signal: Signal;
  consensus_confidence: number;
  rationale: string;
}

export interface TradePlan {
  symbol: string;
  action: Action;
  entry_price: number;
  target_price: number;
  stop_loss_price: number;
  leverage: number;
  tranche_sizes: number[];
  rationale: string;
}

export interface RiskVerdict {
  approved: boolean;
  adjusted_leverage: number;
  adjusted_position_pct_of_equity: number;
  violations_corrected: string[];
  notes: string;
}

export interface FinalDecision {
  trade_plan: TradePlan;
  risk_verdict: RiskVerdict;
  status: 'pending_approval' | 'blocked';
  blocked_reason: string | null;
}

export interface Position {
  symbol: string;
  quantity: number;
  avg_entry_price: number;
  leverage: number;
  stop_loss_price: number;
}

export interface TradeLogEntry {
  symbol: string;
  action: string;
  quantity: number;
  price: number;
  pnl: number | null;
  ts: number;
}

export interface StrategyPreset {
  key: string;
  name: string;
  colorVar: string;
  weights: Record<string, number>;
}

export interface DecisionLogEntry {
  ts: number;
  symbol: string;
  kind: 'open' | 'close' | 'hold_existing' | 'skip' | 'stop_out' | 'blocked';
  decision?: FinalDecision;
  booked: boolean;
  note?: string;
}

export interface FundState {
  strategyKey: string;
  cashEquity: number;
  positions: Record<string, Position>;
  realizedPnl: number;
  tradeLog: TradeLogEntry[];
  equityCurve: number[];
  reflection: Record<string, string[]>;
  recentDecisions: DecisionLogEntry[];
  startingEquity: number;
  circuitBreakerStartEquity: number;
  circuitBreakerDay: string;
}

export interface FirmState {
  createdAt: number;
  updatedAt: number;
  tick: number;
  funds: Record<string, FundState>;
  lastCandidatePool: string[];
  lastError: string | null;
}
