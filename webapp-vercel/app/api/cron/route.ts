import { NextRequest, NextResponse } from 'next/server';
import { runFirmTick } from '@/lib/engine';
import { loadState, saveState } from '@/lib/state';

export const maxDuration = 60;
export const dynamic = 'force-dynamic';

/** Vercel Cron's target. When CRON_SECRET is set on the project, Vercel signs its
 * own cron requests with `Authorization: Bearer <CRON_SECRET>` automatically — this
 * just checks that the request actually came from Vercel Cron and not a random
 * caller, so nobody else can trigger autonomous trading cycles ad hoc. */
export async function GET(req: NextRequest) {
  const expected = process.env.CRON_SECRET;
  if (expected) {
    const auth = req.headers.get('authorization');
    if (auth !== `Bearer ${expected}`) return NextResponse.json({ ok: false, error: 'unauthorized' }, { status: 401 });
  }
  try {
    const state = await loadState();
    const summary = await runFirmTick(state);
    await saveState(state);
    return NextResponse.json({ ok: true, summary });
  } catch (err: any) {
    return NextResponse.json({ ok: false, error: String(err?.message || err) }, { status: 500 });
  }
}
