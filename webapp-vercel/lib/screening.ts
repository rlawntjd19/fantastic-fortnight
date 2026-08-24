import { getScreenerUniverse } from './yahoo';

/** Used only if every Yahoo screener bucket fails on a given tick (e.g. the
 * unofficial endpoint is down or blocked) — keeps the autonomous loop from
 * having literally nothing to evaluate. Large, liquid, well-known names only;
 * this is a fallback seed, not a curated "always trade these" list. */
const FALLBACK_SEED_SYMBOLS = [
  'AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'META', 'TSLA', 'AVGO', 'JPM', 'V',
  'UNH', 'XOM', 'PG', 'JNJ', 'HD', 'COST', 'AMD', 'NFLX', 'CRM', 'ORCL',
];

export async function getCandidateUniverse(maxSymbols = 25): Promise<{ symbols: string[]; source: 'screener' | 'fallback_seed' }> {
  try {
    const symbols = await getScreenerUniverse(maxSymbols);
    if (symbols.length >= 5) return { symbols, source: 'screener' };
  } catch {
    // fall through to the static seed
  }
  return { symbols: FALLBACK_SEED_SYMBOLS.slice(0, maxSymbols), source: 'fallback_seed' };
}
