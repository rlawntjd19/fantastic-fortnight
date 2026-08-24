import { NextRequest, NextResponse } from 'next/server';
import { computePerformance } from '@/lib/performance';
import { loadState, resetState } from '@/lib/state';
import { STRATEGY_KEYS } from '@/lib/strategies';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const state = await loadState();
    const performance: Record<string, ReturnType<typeof computePerformance>> = {};
    for (const key of STRATEGY_KEYS) {
      const fund = state.funds[key];
      const pnls = fund.tradeLog.map((t) => t.pnl).filter((p): p is number => p !== null && p !== undefined);
      performance[key] = computePerformance(fund.equityCurve, pnls);
    }
    return NextResponse.json({ ok: true, state, performance });
  } catch (err: any) {
    return NextResponse.json({ ok: false, error: String(err?.message || err) }, { status: 500 });
  }
}

/** Wipes all four funds back to their starting paper equity. Gated behind the same
 * shared secret as the cron endpoint (there's no user login on this demo) so a
 * random visitor hitting the API can't reset it out from under someone watching it. */
export async function POST(req: NextRequest) {
  const expected = process.env.CRON_SECRET;
  if (expected && req.headers.get('x-admin-key') !== expected) {
    return NextResponse.json({ ok: false, error: 'unauthorized — set x-admin-key to CRON_SECRET' }, { status: 401 });
  }
  try {
    const state = await resetState();
    return NextResponse.json({ ok: true, state });
  } catch (err: any) {
    return NextResponse.json({ ok: false, error: String(err?.message || err) }, { status: 500 });
  }
}
