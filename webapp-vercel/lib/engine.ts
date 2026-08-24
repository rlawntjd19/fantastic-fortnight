import { runAllAnalysts } from './analysts';
import { applyTrailingStops, checkStopLosses, equity, executeDecision } from './broker';
import { buildSnapshots } from './market';
import { researchDebate } from './research';
import { DailyCircuitBreaker, RISK_LIMITS, enforceHardLimits } from './risk';
import { getCandidateUniverse } from './screening';
import { STRATEGY_KEYS, STRATEGY_PRESETS } from './strategies';
import { buildClosePlan, traderPropose } from './trader';
import type { AnalystReport, DecisionLogEntry, FinalDecision, FirmState, FundState, MarketSnapshot } from './types';

/** Policy knobs for the autonomous screening/rotation loop — distinct from the hard
 * risk ceilings in risk.ts, which nothing here is allowed to touch. These decide
 * *which* candidates get looked at and how convinced a fund must be to act, not how
 * big a position can get once it decides to act. */
export const AUTONOMY = {
  maxHoldingsPerFund: 5,
  entryConfidenceThreshold: 0.35,
  candidatePoolSize: 25,
  fetchConcurrency: 5,
  requestedLeverage: 1.5,
  requestedTranches: 2,
  trailingStopPct: 0.04,
};

const TRADING_GLOBAL_LEVERAGE = AUTONOMY.requestedLeverage;
const TRADING_GLOBAL_TRANCHES = AUTONOMY.requestedTranches;

function recentLessons(fund: FundState, symbol: string, n = 3): string[] {
  return (fund.reflection[symbol] || []).slice(-n);
}

function recordLessonFromLastTrade(fund: FundState, planRationale: string) {
  const last = fund.tradeLog[fund.tradeLog.length - 1];
  if (!last || last.pnl === null || last.pnl === undefined) return;
  const outcome = last.pnl > 0 ? 'profitable' : 'losing';
  const lesson = `${outcome} ${last.action} on ${last.symbol}: pnl=${last.pnl >= 0 ? '+' : ''}${last.pnl.toFixed(2)} (entry rationale: ${planRationale.slice(0, 90)})`;
  const arr = fund.reflection[last.symbol] || [];
  arr.push(lesson);
  if (arr.length > 10) arr.shift();
  fund.reflection[last.symbol] = arr;
}

function pushDecisionLog(fund: FundState, entry: DecisionLogEntry) {
  fund.recentDecisions.unshift(entry);
  if (fund.recentDecisions.length > 200) fund.recentDecisions.length = 200;
}

function ensureCircuitBreakerWindow(fund: FundState, currentEquity: number) {
  const today = new Date().toISOString().slice(0, 10);
  if (fund.circuitBreakerDay !== today) {
    fund.circuitBreakerDay = today;
    fund.circuitBreakerStartEquity = currentEquity;
  }
}

function priceMapFor(fund: FundState, snapshots: Record<string, MarketSnapshot>): Record<string, number> {
  const map: Record<string, number> = {};
  for (const sym of Object.keys(fund.positions)) if (snapshots[sym]) map[sym] = snapshots[sym].lastPrice;
  return map;
}

function decideAndMaybeExecute(
  fund: FundState,
  plan: ReturnType<typeof buildClosePlan>,
  breaker: DailyCircuitBreaker,
  kind: DecisionLogEntry['kind'],
  symbol: string,
  snapshots: Record<string, MarketSnapshot>,
) {
  const acctEquity = equity(fund, priceMapFor(fund, snapshots));
  const verdict = enforceHardLimits(plan, acctEquity, breaker);
  const decision: FinalDecision = {
    trade_plan: plan,
    risk_verdict: verdict,
    status: verdict.approved ? 'pending_approval' : 'blocked',
    blocked_reason: verdict.approved ? null : verdict.notes,
  };
  const booked = decision.status === 'pending_approval';
  if (booked) {
    executeDecision(fund, decision);
    recordLessonFromLastTrade(fund, plan.rationale);
  }
  pushDecisionLog(fund, { ts: Date.now(), symbol, kind: booked ? kind : 'blocked', decision, booked });
}

export interface TickSummary {
  tick: number;
  candidateSource: 'screener' | 'fallback_seed';
  candidatePool: string[];
  snapshotsFetched: number;
  perFund: Record<string, { opened: string[]; closed: string[]; stoppedOut: string[]; equity: number }>;
  errors: string[];
}

/** One full autonomous cycle: screen the market, re-evaluate every held position,
 * and let each fund open/close positions on its own — no human approval anywhere
 * in this path. It is still a paper broker with hard risk limits enforced on every
 * single order; see risk.ts. */
export async function runFirmTick(state: FirmState): Promise<TickSummary> {
  const errors: string[] = [];
  const { symbols: candidatePool, source: candidateSource } = await getCandidateUniverse(AUTONOMY.candidatePoolSize).catch((e) => {
    errors.push(`candidate universe: ${String(e?.message || e)}`);
    return { symbols: [] as string[], source: 'fallback_seed' as const };
  });

  const heldSymbols = new Set<string>();
  for (const key of STRATEGY_KEYS) for (const sym of Object.keys(state.funds[key].positions)) heldSymbols.add(sym);
  const universe = Array.from(new Set([...candidatePool, ...heldSymbols]));

  const snapshots = await buildSnapshots(universe, AUTONOMY.fetchConcurrency);
  const reportsBySymbol = new Map<string, AnalystReport[]>();
  for (const [symbol, snap] of Object.entries(snapshots)) reportsBySymbol.set(symbol, runAllAnalysts(snap));

  const perFund: TickSummary['perFund'] = {};

  for (const key of STRATEGY_KEYS) {
    const fund = state.funds[key];
    const preset = STRATEGY_PRESETS[key];
    const opened: string[] = [];
    const closed: string[] = [];

    const priceMapHeld = priceMapFor(fund, snapshots);
    ensureCircuitBreakerWindow(fund, equity(fund, priceMapHeld));
    const breaker = new DailyCircuitBreaker(fund.circuitBreakerStartEquity, RISK_LIMITS.dailyCircuitBreakerPct);

    const stoppedOut = checkStopLosses(fund, priceMapHeld);
    applyTrailingStops(fund, priceMapHeld, AUTONOMY.trailingStopPct);
    for (const sym of stoppedOut) pushDecisionLog(fund, { ts: Date.now(), symbol: sym, kind: 'stop_out', booked: true, note: 'Hard stop-loss triggered.' });
    closed.push(...stoppedOut);

    // 1) Re-evaluate every symbol still held after stop-loss checks — exit if the
    //    fund's own strategy no longer reads it as bullish/bearish enough to hold.
    for (const symbol of Object.keys(fund.positions)) {
      const snap = snapshots[symbol];
      if (!snap) continue; // no fresh data this tick — leave the position alone rather than act blind
      const reports = reportsBySymbol.get(symbol)!;
      const research = researchDebate(reports, preset.weights);
      if (research.consensus_signal === 'neutral') {
        const plan = buildClosePlan(symbol, snap.lastPrice, `Thesis faded to neutral: ${research.rationale}`);
        decideAndMaybeExecute(fund, plan, breaker, 'close', symbol, snapshots);
        closed.push(symbol);
      } else {
        pushDecisionLog(fund, { ts: Date.now(), symbol, kind: 'hold_existing', booked: false, note: research.rationale });
      }
    }

    // 2) Screen candidates not currently held — open a new position on high-conviction
    //    signals only, and only while under the per-fund holdings cap.
    for (const symbol of candidatePool) {
      if (fund.positions[symbol]) continue;
      if (Object.keys(fund.positions).length >= AUTONOMY.maxHoldingsPerFund) break;
      const snap = snapshots[symbol];
      if (!snap) continue;
      const reports = reportsBySymbol.get(symbol)!;
      const research = researchDebate(reports, preset.weights);
      if (research.consensus_signal !== 'neutral' && research.consensus_confidence >= AUTONOMY.entryConfidenceThreshold) {
        const plan = traderPropose(symbol, snap.lastPrice, research, TRADING_GLOBAL_LEVERAGE, TRADING_GLOBAL_TRANCHES, recentLessons(fund, symbol));
        decideAndMaybeExecute(fund, plan, breaker, 'open', symbol, snapshots);
        if (fund.positions[symbol]) opened.push(symbol);
      } else {
        pushDecisionLog(fund, { ts: Date.now(), symbol, kind: 'skip', booked: false, note: `confidence ${(research.consensus_confidence * 100).toFixed(0)}% below entry threshold` });
      }
    }

    const finalPriceMap = priceMapFor(fund, snapshots);
    const finalEquity = equity(fund, finalPriceMap);
    fund.equityCurve.push(finalEquity);
    if (fund.equityCurve.length > 2000) fund.equityCurve.splice(0, fund.equityCurve.length - 2000);
    perFund[key] = { opened, closed, stoppedOut, equity: finalEquity };
  }

  state.tick += 1;
  state.lastCandidatePool = candidatePool;
  state.lastError = errors.length ? errors.join('; ') : null;

  return { tick: state.tick, candidateSource, candidatePool, snapshotsFetched: Object.keys(snapshots).length, perFund, errors };
}
