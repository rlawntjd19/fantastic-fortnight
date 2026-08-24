import { getChart, getFundamentals, getMacroSnapshot, getNewsHeadlines } from './yahoo';
import type { MarketSnapshot } from './types';

export async function buildSnapshot(symbol: string, macro: MarketSnapshot['macro']): Promise<MarketSnapshot> {
  const [chart, fundamentals, newsHeadlines] = await Promise.all([
    getChart(symbol, '6mo', '1d'),
    getFundamentals(symbol).catch(() => ({})),
    getNewsHeadlines(symbol).catch(() => [] as string[]),
  ]);
  const closes = chart.bars.map((b) => b.close);
  return {
    symbol,
    bars: chart.bars,
    fundamentals,
    newsHeadlines,
    macro,
    lastPrice: closes[closes.length - 1],
    closes,
  };
}

/** Fetches snapshots for many symbols with bounded concurrency, so one tick doesn't
 * fire dozens of simultaneous requests at Yahoo (and risk getting the deployment's
 * IP rate-limited) and so a handful of bad symbols can't blow the whole tick's time
 * budget. A symbol that fails is dropped from the result, not retried. */
export async function buildSnapshots(symbols: string[], concurrency = 5): Promise<Record<string, MarketSnapshot>> {
  const macro = await getMacroSnapshot().catch(() => ({ ten_year_yield_change_pct: null, vix_level: null, dollar_index_change_pct: null }));
  const out: Record<string, MarketSnapshot> = {};
  let cursor = 0;
  async function worker() {
    while (cursor < symbols.length) {
      const symbol = symbols[cursor++];
      try {
        out[symbol] = await buildSnapshot(symbol, macro);
      } catch {
        // dropped — the candidate pool and held-position logic both tolerate gaps
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, symbols.length) }, worker));
  return out;
}
