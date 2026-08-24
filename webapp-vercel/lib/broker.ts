import { trailingStopPrice } from './risk';
import type { FinalDecision, FundState } from './types';

export function equity(fund: FundState, currentPrices: Record<string, number>): number {
  let unrealized = 0;
  for (const sym of Object.keys(fund.positions)) {
    const pos = fund.positions[sym];
    const price = currentPrices[sym] !== undefined ? currentPrices[sym] : pos.avg_entry_price;
    unrealized += (price - pos.avg_entry_price) * pos.quantity;
  }
  return fund.cashEquity + unrealized;
}

function logTrade(fund: FundState, symbol: string, action: string, quantity: number, price: number, pnl: number | null) {
  fund.tradeLog.push({ symbol, action, quantity, price, pnl, ts: Date.now() });
  if (fund.tradeLog.length > 500) fund.tradeLog.splice(0, fund.tradeLog.length - 500);
}

/** Executes an already risk-approved decision immediately — no human approval step.
 * Safe only because this broker never touches a real brokerage or moves real money;
 * see README-DEPLOY.md. */
export function executeDecision(fund: FundState, decision: FinalDecision): void {
  if (!decision.risk_verdict.approved || decision.status !== 'pending_approval') {
    throw new Error('Cannot execute a decision that was blocked by risk controls.');
  }
  const plan = decision.trade_plan;
  if (plan.action === 'close') {
    const existing = fund.positions[plan.symbol];
    if (existing) {
      const pnl = (plan.entry_price - existing.avg_entry_price) * existing.quantity;
      fund.realizedPnl += pnl;
      fund.cashEquity += pnl;
      logTrade(fund, plan.symbol, 'close', existing.quantity, plan.entry_price, pnl);
      delete fund.positions[plan.symbol];
    }
    return;
  }
  if (plan.action === 'hold') return;

  const notional = equity(fund, { [plan.symbol]: plan.entry_price }) * decision.risk_verdict.adjusted_position_pct_of_equity * decision.risk_verdict.adjusted_leverage;
  let orderQty = plan.entry_price ? notional / plan.entry_price : 0;
  if (plan.action === 'sell') orderQty = -orderQty;

  const existing = fund.positions[plan.symbol];
  const sameDir = !existing || (existing.quantity >= 0) === (orderQty >= 0);

  if (sameDir) {
    let newQty: number, newAvg: number;
    if (!existing) {
      newQty = orderQty;
      newAvg = plan.entry_price;
    } else {
      newQty = existing.quantity + orderQty;
      newAvg = newQty !== 0 ? (existing.quantity * existing.avg_entry_price + orderQty * plan.entry_price) / newQty : plan.entry_price;
    }
    fund.positions[plan.symbol] = { symbol: plan.symbol, quantity: newQty, avg_entry_price: newAvg, leverage: decision.risk_verdict.adjusted_leverage, stop_loss_price: plan.stop_loss_price };
    logTrade(fund, plan.symbol, plan.action, orderQty, plan.entry_price, null);
    return;
  }

  const closingQty = Math.min(Math.abs(orderQty), Math.abs(existing.quantity));
  const closedSigned = existing.quantity > 0 ? closingQty : -closingQty;
  const pnl = (plan.entry_price - existing.avg_entry_price) * closedSigned;
  fund.realizedPnl += pnl;
  fund.cashEquity += pnl;
  const remaining = existing.quantity + orderQty;
  if (remaining === 0) {
    delete fund.positions[plan.symbol];
    logTrade(fund, plan.symbol, 'close', -closedSigned, plan.entry_price, pnl);
  } else if ((remaining >= 0) === (existing.quantity >= 0)) {
    existing.quantity = remaining;
    existing.leverage = decision.risk_verdict.adjusted_leverage;
    existing.stop_loss_price = plan.stop_loss_price;
    logTrade(fund, plan.symbol, 'reduce', -closedSigned, plan.entry_price, pnl);
  } else {
    fund.positions[plan.symbol] = { symbol: plan.symbol, quantity: remaining, avg_entry_price: plan.entry_price, leverage: decision.risk_verdict.adjusted_leverage, stop_loss_price: plan.stop_loss_price };
    logTrade(fund, plan.symbol, 'flip', remaining, plan.entry_price, pnl);
  }
}

export function checkStopLosses(fund: FundState, currentPrices: Record<string, number>): string[] {
  const closed: string[] = [];
  for (const symbol of Object.keys(fund.positions)) {
    const pos = fund.positions[symbol];
    const price = currentPrices[symbol];
    if (price === undefined) continue;
    const longHit = pos.quantity > 0 && price <= pos.stop_loss_price;
    const shortHit = pos.quantity < 0 && price >= pos.stop_loss_price;
    if (longHit || shortHit) {
      const pnl = (price - pos.avg_entry_price) * pos.quantity;
      fund.realizedPnl += pnl;
      fund.cashEquity += pnl;
      logTrade(fund, symbol, 'stop_out', pos.quantity, price, pnl);
      delete fund.positions[symbol];
      closed.push(symbol);
    }
  }
  return closed;
}

export function applyTrailingStops(fund: FundState, currentPrices: Record<string, number>, pct: number): void {
  for (const symbol of Object.keys(fund.positions)) {
    const pos = fund.positions[symbol];
    const price = currentPrices[symbol];
    if (price === undefined) continue;
    pos.stop_loss_price = trailingStopPrice(pos.quantity, pos.stop_loss_price, price, pct);
  }
}
