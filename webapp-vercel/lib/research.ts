import type { AnalystReport, ResearchDebateResult } from './types';

/**
 * weights: optional { agent_name: multiplier } — this is where a "strategy" acts:
 * it re-weights how much each analyst's vote counts toward consensus. It never
 * changes what an analyst saw or computed, only how loudly it's heard.
 */
export function researchDebate(reports: AnalystReport[], weights?: Record<string, number>): ResearchDebateResult {
  const wm = weights || {};
  const weightOf = (r: AnalystReport) => (wm[r.agent_name] ?? 1);
  const supporting = reports.filter((r) => r.signal !== 'bearish').flatMap((r) => r.key_points);
  const opposing = reports.filter((r) => r.signal !== 'bullish').flatMap((r) => r.key_points);
  const bullThesis = `Bull case: ${supporting[0] || 'No supporting evidence found.'}`;
  const bearThesis = `Bear case: ${opposing[0] || 'No opposing evidence found.'}`;
  const dir: Record<string, number> = { bullish: 1, bearish: -1, neutral: 0 };
  let weighted = 0, totalWeight = 0;
  for (const r of reports) {
    const wt = r.confidence * weightOf(r);
    weighted += dir[r.signal] * wt;
    totalWeight += wt;
  }
  const avg = totalWeight ? weighted / totalWeight : 0;
  const consensus = avg > 0.15 ? 'bullish' : avg < -0.15 ? 'bearish' : 'neutral';
  return {
    bull_thesis: bullThesis,
    bear_thesis: bearThesis,
    consensus_signal: consensus,
    consensus_confidence: Math.min(1.0, Math.abs(avg)),
    rationale: bullThesis,
  };
}
