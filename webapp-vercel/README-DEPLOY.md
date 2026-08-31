# Strategy Fund Desk — Vercel deployment guide

This is a Next.js rewrite of the trading-agent demo, built to run as a real, persistent
Vercel deployment instead of a one-off Artifact. Four paper-trading funds (balanced,
momentum, value, macro) pull **real, live data from Yahoo Finance's unofficial API**,
screen the market on their own, and open/close/rotate positions **with no human
approval step anywhere in the path** — exactly what was asked for. What did **not**
change: it is still a paper broker (no brokerage/exchange connection, no real money),
and all four funds still hit the exact same hard-coded risk limits on every single
order (3x leverage cap, 10%-of-equity position cap, mandatory stop-loss, daily loss
circuit breaker). Autonomy was expanded; the safety ceiling was not touched.

## What's been verified since, and what's still open

A later session had (temporary, sandboxed) outbound access to `finance.yahoo.com` and
used it to actually call the two endpoints this app's core data path depends on:

- **`getChart` (prices/OHLCV) and `getNewsHeadlines` (sentiment input) are confirmed
  working against live Yahoo responses**, parsed shape and all —
  `chart.result[0].{timestamp, meta.currency, indicators.quote[0].{open,high,low,close,volume}}`
  and `news[].title` both matched exactly what `lib/yahoo.ts` expects, with real,
  current prices coming back. `getMacroSnapshot` just composes `getChart` calls, so it
  inherits this same verification.
- **`getFundamentals` and `getScreenerUniverse` remain unverified** — both need the
  crumb/cookie handshake in `getCrumb()`, and that specific flow (simulating a
  browser's cookie-and-crumb dance to get past Yahoo's auth gate) wasn't something
  that session's environment permitted testing, for policy reasons unrelated to
  whether the code itself is correct. This matters less than it sounds: `getFundamentals`
  already returns `{}` on any failure (every fundamentals field downstream is already
  optional), and `getCandidateUniverse` (`lib/screening.ts`) already falls back to a
  20-name static seed list if the screener returns fewer than 5 symbols or throws —
  so a broken crumb flow degrades the fund's data quality, it doesn't break the loop.
  **Still do a real tick right after your first deploy** (see step 5) and check
  whether the log panel's `candidateSource` reads `screener` or `fallback_seed` — the
  latter means the crumb flow isn't working in your deployment and is worth
  investigating (rate limiting, IP-based blocking, or Yahoo having changed the flow).
- **Vercel Cron on the Hobby plan is confirmed capped to once/day** — a real deploy
  attempt hit exactly this: Vercel rejected the original hourly schedule
  (`0 * * * *`) outright with "Hobby accounts are limited to daily cron jobs."
  `vercel.json` now requests `5 21 * * *` (21:05 UTC, ~5 minutes after the US
  market close) once daily instead — deliberately timed so the one guaranteed
  cron tick reflects that day's actual closing prices, not a stale intraday
  snapshot. `/api/cron` (`app/api/cron/route.ts`) has no hourly-specific logic;
  it just runs one tick whenever called, so this was a config-only fix, not a
  code change. If you're on Pro and want finer granularity back, edit the
  schedule in `vercel.json` directly — anything Vercel's cron syntax accepts
  will work.

## Two ways the loop advances

1. **Vercel Cron** (`vercel.json` → `/api/cron`, once daily by default — Hobby's
   ceiling, see "Known limitations" below) — runs even if nobody has the page open.
   Protected by `CRON_SECRET` so only Vercel can trigger it.
2. **The page itself** — polls `/api/state` every 20s while open, and has a "지금 한
   틱 실행" button that calls `/api/tick` directly. On Hobby, **this is actually the
   primary way the loop advances more than once a day** — cron alone only guarantees
   one tick every 24 hours. Someone needs to have the tab open (or click the button)
   for anything faster than that.

Both paths call the exact same `runFirmTick()` in `lib/engine.ts` — there's no
separate "manual mode" with looser rules.

## Deploy steps

1. **Import the project.** In Vercel: New Project → import this GitHub repo. Because
   this app lives in a subfolder of a larger repo, set **Root Directory** to
   `webapp-vercel` in the project's settings before the first deploy.
2. **Add Upstash Redis.** Vercel dashboard → your project → Storage tab → Create
   Database → Upstash Redis (or connect an existing Upstash database). This is where
   all four funds' positions, trade logs, and equity curves persist between ticks —
   without it, `/api/state` and `/api/tick` return a clear "Upstash not configured"
   error instead of crashing, but nothing actually runs. Connecting it through the
   Vercel Storage tab auto-injects `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN`.
3. **Set `CRON_SECRET`.** Project Settings → Environment Variables → add `CRON_SECRET`
   with any random string. This gates both the `/api/cron` endpoint (Vercel signs its
   own cron requests with it automatically) and the reset endpoint.
4. **Deploy.**
5. **Trigger the first tick by hand.** Open the deployed URL and click "지금 한 틱
   실행" rather than waiting for the next cron firing. Watch the 실행 로그 panel —
   you should see real ticker symbols (from Yahoo's day_gainers/day_losers/
   most_actives/etc. screeners) with real prices, not simulation placeholders. If it
   errors, the error banner will say why (Upstash not configured, Yahoo fetch
   failures, etc.) — Yahoo's unofficial API can and does occasionally block/rate-limit
   requests without warning; see below.

## Local development

```
cd webapp-vercel
npm install
cp .env.example .env.local   # fill in UPSTASH_REDIS_REST_URL / TOKEN, and CRON_SECRET
npm run dev
```

Yahoo Finance access from your own machine is very likely unrestricted (unlike the
sandbox this was built in), so local dev is actually the easiest place to first
confirm real data is flowing.

## Resetting the paper accounts

All four funds share one Redis key. To wipe them back to their starting paper equity:

```
curl -X POST -H "x-admin-key: $CRON_SECRET" https://<your-deployment>/api/state
```

## Known limitations, on purpose

- **Yahoo Finance is unofficial and can break without notice.** No SLA, no support
  contract, occasional crumb/cookie/auth changes that can 401 every request until the
  code catches up. A failed fetch for one symbol just drops that symbol for that tick
  (see `lib/market.ts`) rather than failing the whole cycle.
- **No login, no multi-tenant separation.** This is a single shared demo instance —
  anyone with the URL sees the same four funds. The reset endpoint is the only thing
  gated, and only by a shared secret, not real auth.
- **Autonomy is bounded by policy knobs, not just hard risk limits.** `AUTONOMY` in
  `lib/engine.ts` caps how many positions a fund can hold at once (5) and how
  confident a strategy must be before opening a new one (0.35). These are tunable
  parameters, not safety limits — the actual safety ceiling is `RISK_LIMITS` in
  `lib/risk.ts`, which nothing in the autonomous loop can adjust.
- **Still, deliberately, not connected to any real brokerage or exchange.** If this
  is ever pointed at a real account, that integration needs its own independent
  review — the "no human approval needed" design here is only safe because execution
  only ever touches an in-memory/Redis paper ledger.
