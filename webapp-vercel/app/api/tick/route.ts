import { NextResponse } from 'next/server';
import { runFirmTick } from '@/lib/engine';
import { loadState, saveState } from '@/lib/state';

export const maxDuration = 60;
export const dynamic = 'force-dynamic';

/** Manually advances the firm by one autonomous cycle. Anyone can call this (there's
 * no login on this demo) — it just runs the same no-human-in-the-loop decision loop
 * the cron job runs on a schedule. Safe to hammer: it's a paper broker. */
export async function POST() {
  try {
    const state = await loadState();
    const summary = await runFirmTick(state);
    await saveState(state);
    return NextResponse.json({ ok: true, summary, state });
  } catch (err: any) {
    return NextResponse.json({ ok: false, error: String(err?.message || err) }, { status: 500 });
  }
}
