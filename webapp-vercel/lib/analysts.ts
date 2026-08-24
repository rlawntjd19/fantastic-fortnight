import { sma, rsi, momentum, sampleStdev } from './indicators';
import type { AnalystReport, MarketSnapshot } from './types';

function scoreToSignal(score: number, maxAbsScore: number) {
  const confidence = maxAbsScore ? Math.min(1.0, Math.abs(score) / maxAbsScore) : 0.0;
  if (score > 0.25) return { signal: 'bullish' as const, confidence };
  if (score < -0.25) return { signal: 'bearish' as const, confidence };
  return { signal: 'neutral' as const, confidence };
}

export function technicalAnalyst(snapshot: MarketSnapshot): AnalystReport {
  const closes = snapshot.closes;
  const fast = sma(closes, 10), slow = sma(closes, 30), rsiV = rsi(closes, 14), mom = momentum(closes, 10);
  const points: string[] = [];
  let score = 0;
  if (fast !== null && slow !== null) {
    if (fast > slow) { score += 1; points.push(`SMA10 (${fast.toFixed(2)}) above SMA30 (${slow.toFixed(2)}): uptrend`); }
    else { score -= 1; points.push(`SMA10 (${fast.toFixed(2)}) below SMA30 (${slow.toFixed(2)}): downtrend`); }
  }
  if (rsiV !== null) {
    if (rsiV >= 70) { score -= 0.5; points.push(`RSI ${rsiV.toFixed(1)}: overbought, pullback risk`); }
    else if (rsiV <= 30) { score += 0.5; points.push(`RSI ${rsiV.toFixed(1)}: oversold, bounce potential`); }
    else points.push(`RSI ${rsiV.toFixed(1)}: neutral`);
  }
  if (mom !== null) { score += mom > 0 ? 0.5 : -0.5; points.push(`10-bar momentum ${(mom * 100).toFixed(1)}%`); }
  const { signal, confidence } = scoreToSignal(score, 2.0);
  return { agent_name: 'technical_analyst', signal, confidence, summary: points[0] || 'No indicator data available.', key_points: points };
}

export function fundamentalAnalyst(snapshot: MarketSnapshot): AnalystReport {
  const f = snapshot.fundamentals;
  const points: string[] = [];
  let score = 0;
  const pe = f.pe_ratio;
  if (pe !== undefined) {
    if (pe < 15) { score += 1; points.push(`P/E ${pe.toFixed(1)}: reasonably valued or cheap`); }
    else if (pe > 30) { score -= 1; points.push(`P/E ${pe.toFixed(1)}: richly valued`); }
    else points.push(`P/E ${pe.toFixed(1)}: fair value`);
  }
  const growth = f.revenue_growth_yoy;
  if (growth !== undefined) {
    score += growth > 0.10 ? 1 : growth < 0 ? -0.5 : 0;
    points.push(`YoY revenue growth ${(growth * 100).toFixed(1)}%`);
  }
  const fpe = f.forward_pe;
  if (fpe !== undefined && pe !== undefined && pe > 0) {
    if (fpe < pe) { score += 0.5; points.push(`Forward P/E ${fpe.toFixed(1)} < trailing ${pe.toFixed(1)}: earnings expected to grow`); }
    else if (fpe > pe) { score -= 0.5; points.push(`Forward P/E ${fpe.toFixed(1)} > trailing ${pe.toFixed(1)}: earnings expected to shrink`); }
  }
  const roe = f.return_on_equity;
  if (roe !== undefined) { score += roe > 0.15 ? 0.5 : roe < 0.05 ? -0.5 : 0; points.push(`Return on equity ${(roe * 100).toFixed(1)}%`); }
  const margin = f.profit_margin;
  if (margin !== undefined) { score += margin > 0.15 ? 0.5 : margin < 0 ? -1 : 0; points.push(`Profit margin ${(margin * 100).toFixed(1)}%`); }
  const dte = f.debt_to_equity;
  if (dte !== undefined) { score += dte > 200 ? -0.5 : dte < 50 ? 0.5 : 0; points.push(`Debt/Equity ${dte.toFixed(0)}%`); }
  const { signal, confidence } = scoreToSignal(score, 5.0);
  return { agent_name: 'fundamental_analyst', signal, confidence, summary: points[0] || 'No fundamental data available.', key_points: points };
}

const POSITIVE_WORDS = ['buy', 'upgrade', 'beat', 'rally', 'surge', 'gain', 'record', 'growth', 'strong', 'outperform', 'raise'];
const NEGATIVE_WORDS = ['sell', 'downgrade', 'miss', 'plunge', 'slump', 'loss', 'warning', 'lawsuit', 'weak', 'underperform', 'cut', 'fall'];

export function sentimentAnalyst(snapshot: MarketSnapshot): AnalystReport {
  const headlines = snapshot.newsHeadlines;
  let score = 0;
  const points: string[] = [];
  for (const h of headlines) {
    const low = h.toLowerCase();
    const pos = POSITIVE_WORDS.some((w) => low.includes(w));
    const neg = NEGATIVE_WORDS.some((w) => low.includes(w));
    if (pos && !neg) { score += 1; points.push(`+ ${h}`); }
    else if (neg && !pos) { score -= 1; points.push(`- ${h}`); }
    else points.push(`= ${h}`);
  }
  const { signal, confidence } = scoreToSignal(score, Math.max(1.0, headlines.length));
  return { agent_name: 'sentiment_analyst', signal, confidence, summary: headlines[0] || 'No headlines available.', key_points: points };
}

export function macroAnalyst(snapshot: MarketSnapshot): AnalystReport {
  const m = snapshot.macro;
  const points: string[] = [];
  let score = 0;
  if (m.ten_year_yield_change_pct !== null) {
    if (m.ten_year_yield_change_pct > 0.05) { score -= 0.5; points.push(`10Y yield up ${(m.ten_year_yield_change_pct * 100).toFixed(1)}%: tightening headwind`); }
    else if (m.ten_year_yield_change_pct < -0.05) { score += 0.5; points.push(`10Y yield down ${(m.ten_year_yield_change_pct * 100).toFixed(1)}%: easier conditions`); }
  }
  if (m.vix_level !== null) {
    if (m.vix_level > 25) { score -= 1; points.push(`VIX ${m.vix_level.toFixed(1)}: elevated fear, risk-off`); }
    else if (m.vix_level < 15) { score += 0.5; points.push(`VIX ${m.vix_level.toFixed(1)}: calm, risk-on`); }
    else points.push(`VIX ${m.vix_level.toFixed(1)}: normal range`);
  }
  if (m.dollar_index_change_pct !== null) {
    if (m.dollar_index_change_pct > 0.02) { score -= 0.5; points.push(`Dollar index up ${(m.dollar_index_change_pct * 100).toFixed(1)}%: headwind`); }
    else if (m.dollar_index_change_pct < -0.02) { score += 0.5; points.push(`Dollar index down ${(m.dollar_index_change_pct * 100).toFixed(1)}%: tailwind`); }
  }
  const { signal, confidence } = scoreToSignal(score, 2.0);
  return { agent_name: 'macro_analyst', signal, confidence, summary: points[0] || 'No macro data available.', key_points: points };
}

const FULL_CONFIDENCE_MOVE = 0.05;
const NEUTRAL_BAND = 0.2 * FULL_CONFIDENCE_MOVE;

export function forecastAnalyst(snapshot: MarketSnapshot): AnalystReport {
  const closes = snapshot.closes;
  const predLen = 10, lookback = 20;
  let expectedReturn = 0, dispersion = 0;
  if (closes.length >= 2) {
    const window = closes.slice(-lookback);
    const returns: number[] = [];
    for (let i = 1; i < window.length; i++) returns.push(window[i] / window[i - 1] - 1);
    const drift = returns.reduce((a, b) => a + b, 0) / (returns.length || 1);
    const vol = sampleStdev(returns);
    let price = closes[closes.length - 1];
    for (let i = 0; i < predLen; i++) price *= 1 + drift;
    expectedReturn = price / closes[closes.length - 1] - 1;
    dispersion = vol * Math.sqrt(predLen);
  }
  const rawConfidence = Math.min(1.0, Math.abs(expectedReturn) / FULL_CONFIDENCE_MOVE);
  let signal: 'bullish' | 'bearish' | 'neutral' = 'neutral';
  if (expectedReturn > NEUTRAL_BAND) signal = 'bullish';
  else if (expectedReturn < -NEUTRAL_BAND) signal = 'bearish';
  const uncertaintyPenalty = 1.0 / (1.0 + dispersion / FULL_CONFIDENCE_MOVE);
  const confidence = rawConfidence * uncertaintyPenalty;
  const summary = `heuristic ${predLen}-bar forecast: ${(expectedReturn * 100).toFixed(1)}% expected move (dispersion ${(dispersion * 100).toFixed(1)}%)`;
  return { agent_name: 'forecast_analyst', signal, confidence, summary, key_points: [summary] };
}

export function runAllAnalysts(snapshot: MarketSnapshot): AnalystReport[] {
  return [technicalAnalyst(snapshot), fundamentalAnalyst(snapshot), sentimentAnalyst(snapshot), macroAnalyst(snapshot), forecastAnalyst(snapshot)];
}
