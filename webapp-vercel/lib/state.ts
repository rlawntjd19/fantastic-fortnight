import { Redis } from '@upstash/redis';
import { STRATEGY_KEYS } from './strategies';
import type { FirmState, FundState } from './types';

const STATE_KEY = 'strategy-fund-desk:firm-state:v1';
const STARTING_EQUITY = 10_000_000;

let redisClient: Redis | null = null;

function getRedis(): Redis {
  if (redisClient) return redisClient;
  const url = process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!url || !token) {
    throw new Error(
      'Upstash Redis is not configured. Provision it from the Vercel dashboard (Storage → Upstash Redis) and connect ' +
        'it to this project, or set UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN yourself. See README-DEPLOY.md.',
    );
  }
  redisClient = new Redis({ url, token });
  return redisClient;
}

function freshFund(strategyKey: string): FundState {
  return {
    strategyKey,
    cashEquity: STARTING_EQUITY,
    positions: {},
    realizedPnl: 0,
    tradeLog: [],
    equityCurve: [STARTING_EQUITY],
    reflection: {},
    recentDecisions: [],
    startingEquity: STARTING_EQUITY,
    circuitBreakerStartEquity: STARTING_EQUITY,
    circuitBreakerDay: new Date().toISOString().slice(0, 10),
  };
}

export function freshFirmState(): FirmState {
  const funds: Record<string, FundState> = {};
  for (const key of STRATEGY_KEYS) funds[key] = freshFund(key);
  return { createdAt: Date.now(), updatedAt: Date.now(), tick: 0, funds, lastCandidatePool: [], lastError: null };
}

export async function loadState(): Promise<FirmState> {
  const redis = getRedis();
  const state = await redis.get<FirmState>(STATE_KEY);
  if (!state) return freshFirmState();
  // Defensive: tolerate a state blob saved before a new strategy key existed.
  for (const key of STRATEGY_KEYS) if (!state.funds[key]) state.funds[key] = freshFund(key);
  return state;
}

export async function saveState(state: FirmState): Promise<void> {
  const redis = getRedis();
  state.updatedAt = Date.now();
  await redis.set(STATE_KEY, state);
}

export async function resetState(): Promise<FirmState> {
  const state = freshFirmState();
  await saveState(state);
  return state;
}
