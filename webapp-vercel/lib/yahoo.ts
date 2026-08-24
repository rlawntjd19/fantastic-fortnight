import type { Bar, Fundamentals, MacroSnapshot } from './types';

/**
 * Thin client for Yahoo Finance's unofficial, undocumented endpoints — the same ones
 * the `yfinance` Python package (already used elsewhere in this repo) talks to. There
 * is no official contract here: Yahoo can rate-limit, reshape, or block this without
 * notice. See README-DEPLOY.md for what that means operationally.
 */

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36';

let cachedCrumb: { crumb: string; cookie: string; fetchedAt: number } | null = null;

async function getCrumb(): Promise<{ crumb: string; cookie: string }> {
  if (cachedCrumb && Date.now() - cachedCrumb.fetchedAt < 30 * 60 * 1000) return cachedCrumb;
  const cookieRes = await fetch('https://fc.yahoo.com', { headers: { 'User-Agent': UA } });
  const setCookie = cookieRes.headers.get('set-cookie') || '';
  const cookie = setCookie.split(';')[0] || '';
  const crumbRes = await fetch('https://query2.finance.yahoo.com/v1/test/getcrumb', {
    headers: { 'User-Agent': UA, Cookie: cookie },
  });
  const crumb = (await crumbRes.text()).trim();
  cachedCrumb = { crumb, cookie, fetchedAt: Date.now() };
  return cachedCrumb;
}

async function yahooFetch(url: string): Promise<Response> {
  const { cookie } = await getCrumb().catch(() => ({ cookie: '' }));
  return fetch(url, { headers: { 'User-Agent': UA, Cookie: cookie }, cache: 'no-store' });
}

export interface ChartResult {
  bars: Bar[];
  currency: string | null;
}

export async function getChart(symbol: string, range = '6mo', interval = '1d'): Promise<ChartResult> {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=${range}&interval=${interval}`;
  const res = await yahooFetch(url);
  if (!res.ok) throw new Error(`Yahoo chart fetch failed for ${symbol}: HTTP ${res.status}`);
  const json = await res.json();
  const result = json?.chart?.result?.[0];
  if (!result) {
    const err = json?.chart?.error?.description || 'no result in response';
    throw new Error(`Yahoo chart fetch failed for ${symbol}: ${err}`);
  }
  const timestamps: number[] = result.timestamp || [];
  const quote = result.indicators?.quote?.[0] || {};
  const bars: Bar[] = [];
  for (let i = 0; i < timestamps.length; i++) {
    const close = quote.close?.[i];
    if (close == null) continue;
    bars.push({
      timestamp: timestamps[i],
      open: quote.open?.[i] ?? close,
      high: quote.high?.[i] ?? close,
      low: quote.low?.[i] ?? close,
      close,
      volume: quote.volume?.[i] ?? 0,
    });
  }
  if (!bars.length) throw new Error(`Yahoo chart fetch for ${symbol} returned no usable bars`);
  return { bars, currency: result.meta?.currency ?? null };
}

export async function getFundamentals(symbol: string): Promise<Fundamentals> {
  const modules = 'defaultKeyStatistics,financialData,summaryDetail';
  const { crumb, cookie } = await getCrumb();
  const url = `https://query2.finance.yahoo.com/v10/finance/quoteSummary/${encodeURIComponent(symbol)}?modules=${modules}&crumb=${encodeURIComponent(crumb)}`;
  const res = await fetch(url, { headers: { 'User-Agent': UA, Cookie: cookie }, cache: 'no-store' });
  if (!res.ok) return {};
  const json = await res.json();
  const result = json?.quoteSummary?.result?.[0];
  if (!result) return {};
  const stats = result.defaultKeyStatistics || {};
  const fin = result.financialData || {};
  const summary = result.summaryDetail || {};
  const raw = (v: any): number | undefined => (typeof v?.raw === 'number' ? v.raw : undefined);
  return {
    pe_ratio: raw(summary.trailingPE),
    forward_pe: raw(summary.forwardPE) ?? raw(stats.forwardPE),
    revenue_growth_yoy: raw(fin.revenueGrowth),
    return_on_equity: raw(fin.returnOnEquity),
    profit_margin: raw(fin.profitMargins),
    debt_to_equity: raw(fin.debtToEquity),
  };
}

export async function getNewsHeadlines(symbol: string): Promise<string[]> {
  try {
    const url = `https://query1.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(symbol)}&newsCount=6&quotesCount=0`;
    const res = await yahooFetch(url);
    if (!res.ok) return [];
    const json = await res.json();
    const items: any[] = json?.news || [];
    return items.map((n) => String(n.title || '')).filter(Boolean).slice(0, 6);
  } catch {
    return [];
  }
}

async function pctChange(symbol: string): Promise<number | null> {
  try {
    const { bars } = await getChart(symbol, '5d', '1d');
    if (bars.length < 2) return null;
    const prev = bars[bars.length - 2].close;
    const last = bars[bars.length - 1].close;
    if (!prev) return null;
    return (last - prev) / prev;
  } catch {
    return null;
  }
}

export async function getMacroSnapshot(): Promise<MacroSnapshot> {
  const [tenYearChange, vixBars, dollarChange] = await Promise.all([
    pctChange('^TNX'),
    getChart('^VIX', '5d', '1d').catch(() => null),
    pctChange('DX-Y.NYB'),
  ]);
  const vixLevel = vixBars && vixBars.bars.length ? vixBars.bars[vixBars.bars.length - 1].close : null;
  return { ten_year_yield_change_pct: tenYearChange, vix_level: vixLevel, dollar_index_change_pct: dollarChange };
}

const SCREENER_IDS = ['day_gainers', 'day_losers', 'most_actives', 'undervalued_large_caps', 'growth_technology_stocks'];

/** Free "scan the whole market" source: Yahoo's predefined screener buckets, pooled
 * and deduplicated. This is the candidate universe the autonomous loop picks from —
 * nothing here is a fixed, human-curated watchlist. */
export async function getScreenerUniverse(maxSymbols = 25): Promise<string[]> {
  const { crumb, cookie } = await getCrumb().catch(() => ({ crumb: '', cookie: '' }));
  const symbols = new Set<string>();
  await Promise.all(
    SCREENER_IDS.map(async (scrId) => {
      try {
        const url = `https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=${scrId}&count=10&crumb=${encodeURIComponent(crumb)}`;
        const res = await fetch(url, { headers: { 'User-Agent': UA, Cookie: cookie }, cache: 'no-store' });
        if (!res.ok) return;
        const json = await res.json();
        const quotes: any[] = json?.finance?.result?.[0]?.quotes || [];
        for (const q of quotes) if (q.symbol) symbols.add(String(q.symbol));
      } catch {
        // one screener bucket failing shouldn't take down the whole candidate pool
      }
    }),
  );
  return Array.from(symbols).slice(0, maxSymbols);
}
