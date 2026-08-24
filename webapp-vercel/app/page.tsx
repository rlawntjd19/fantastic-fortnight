'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { STRATEGY_KEYS, STRATEGY_PRESETS } from '@/lib/strategies';
import type { PerformanceReport } from '@/lib/performance';
import type { FirmState } from '@/lib/types';

type StateResponse = { ok: true; state: FirmState; performance: Record<string, PerformanceReport> } | { ok: false; error: string };
type TickResponse = { ok: true } | { ok: false; error: string };

const POLL_MS = 20_000;

function fmtMoney(x: number): string {
  const sign = x < 0 ? '-' : '';
  return sign + '$' + Math.abs(x).toLocaleString('en-US', { maximumFractionDigits: 0 });
}
function fmtPct(x: number): string {
  return (x * 100).toFixed(2) + '%';
}

function resolveColor(varName: string): string {
  if (typeof window === 'undefined') return '#888';
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
}
function hexToRgba(hex: string, alpha: number): string {
  const h = hex.trim().replace('#', '');
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  const n = parseInt(full, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

function Sparkline({ history, colorVar }: { history: number[]; colorVar: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    if (history.length < 2) return;
    const color = resolveColor(colorVar);
    const min = Math.min(...history), max = Math.max(...history);
    const pad = (max - min) * 0.1 || Math.abs(min) * 0.02 || 1;
    const lo = min - pad, hi = max + pad;
    const xOf = (i: number) => (i / (history.length - 1)) * (w - 4) + 2;
    const yOf = (v: number) => h - 3 - ((v - lo) / (hi - lo || 1)) * (h - 6);
    ctx.beginPath();
    ctx.moveTo(xOf(0), h);
    history.forEach((v, i) => ctx.lineTo(xOf(i), yOf(v)));
    ctx.lineTo(xOf(history.length - 1), h);
    ctx.closePath();
    ctx.fillStyle = hexToRgba(color, 0.14);
    ctx.fill();
    ctx.beginPath();
    history.forEach((v, i) => (i === 0 ? ctx.moveTo(xOf(i), yOf(v)) : ctx.lineTo(xOf(i), yOf(v))));
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.75;
    ctx.stroke();
  }, [history, colorVar]);
  return <canvas ref={ref} width={300} height={40} />;
}

export default function Page() {
  const [state, setState] = useState<FirmState | null>(null);
  const [performance, setPerformance] = useState<Record<string, PerformanceReport>>({});
  const [selectedFund, setSelectedFund] = useState<string>('balanced');
  const [ticking, setTicking] = useState(false);
  const [autoPoll, setAutoPoll] = useState(true);
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastFetchedAt, setLastFetchedAt] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch('/api/state', { cache: 'no-store' });
      const json: StateResponse = await res.json();
      if (json.ok) {
        setState(json.state);
        setPerformance(json.performance);
        setLastError(json.state.lastError);
      } else {
        setLastError(json.error);
      }
    } catch (err: any) {
      setLastError(String(err?.message || err));
    }
    setLastFetchedAt(Date.now());
  }, []);

  const runTick = useCallback(async () => {
    setTicking(true);
    try {
      const res = await fetch('/api/tick', { method: 'POST' });
      const json: TickResponse = await res.json();
      if (!json.ok) setLastError(json.error);
    } catch (err: any) {
      setLastError(String(err?.message || err));
    }
    await refresh();
    setTicking(false);
  }, [refresh]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!autoPoll) return;
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [autoPoll, refresh]);

  const leaderboard = STRATEGY_KEYS.map((key) => ({
    key,
    preset: STRATEGY_PRESETS[key],
    fund: state?.funds[key],
    perf: performance[key],
  })).filter((r) => r.fund && r.perf) as Array<{ key: string; preset: typeof STRATEGY_PRESETS[string]; fund: NonNullable<FirmState['funds'][string]>; perf: PerformanceReport }>;
  leaderboard.sort((a, b) => b.perf.total_return_pct - a.perf.total_return_pct);

  return (
    <>
      <header>
        <h1>Strategy Fund Desk</h1>
        <span className="badge">Live Data · Paper Trading · Fully Autonomous</span>
        <span className={`pill ${ticking ? 'running' : lastError ? 'error' : 'idle'}`} style={{ marginLeft: 'auto' }}>
          {ticking ? '실행 중' : lastError ? '오류' : `Tick ${state?.tick ?? 0}`}
        </span>
      </header>

      <div className="disclaimer">
        <strong>실시간 시세를 반영하는 페이퍼 트레이딩 데모입니다. 투자 자문이 아니며 어떤 수익도 보장하지 않습니다.</strong>{' '}
        4개의 가상 펀드가 Yahoo Finance의 비공식 API로 실시간 시세·재무 데이터·뉴스를 가져와, 전체 시장을 스스로
        스크리닝해 종목을 편입/제거하고 매수/매도를 사람 개입 없이 100% 자율로 실행합니다. 단, 계좌는 어떤 증권사·
        거래소에도 연결되어 있지 않은 가상 잔고이며, 4개 펀드 모두 동일한 하드코딩 리스크 한도(레버리지 3배, 계좌
        10%, 손절 필수, 일일 손실 서킷브레이커)를 예외 없이 적용받습니다. Yahoo의 비공식 API는 예고 없이 차단·
        변경될 수 있어 데이터가 간헐적으로 끊길 수 있습니다.
      </div>

      <main>
        <div className="col">
          <div className="panel">
            <h2>운용 현황</h2>
            <div className="controls" style={{ marginBottom: 12 }}>
              <button className="primary" onClick={runTick} disabled={ticking}>
                {ticking ? '실행 중…' : '지금 한 틱 실행'}
              </button>
              <label className="inline">
                <input type="checkbox" checked={autoPoll} onChange={(e) => setAutoPoll(e.target.checked)} />
                20초마다 자동 갱신
              </label>
            </div>
            <div className="empty">
              마지막 갱신: {lastFetchedAt ? new Date(lastFetchedAt).toLocaleTimeString('ko-KR', { hour12: false }) : '—'}
              {lastError ? <div style={{ color: 'var(--bad)', marginTop: 4 }}>오류: {lastError}</div> : null}
            </div>
          </div>

          <div className="panel">
            <h2>스크리닝 후보군 {state ? `· ${state.lastCandidatePool.length}개` : ''}</h2>
            <div className="universe-tags">
              {state?.lastCandidatePool.length ? (
                state.lastCandidatePool.map((s) => <span className="universe-tag" key={s}>{s}</span>)
              ) : (
                <div className="empty">아직 스크리닝 결과가 없습니다. &quot;지금 한 틱 실행&quot;을 눌러보세요.</div>
              )}
            </div>
          </div>

          <div className="panel">
            <h2>운용 전략 (4개 고정)</h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="strategy-chip"><span className="strategy-dot" style={{ background: 'var(--muted)' }} />균형 · 멀티팩터</div>
              <div className="strategy-chip"><span className="strategy-dot" style={{ background: 'var(--strategy-momentum)' }} />모멘텀 · 추세추종</div>
              <div className="strategy-chip"><span className="strategy-dot" style={{ background: 'var(--strategy-value)' }} />가치 · 펀더멘털</div>
              <div className="strategy-chip"><span className="strategy-dot" style={{ background: 'var(--strategy-macro)' }} />매크로 · 거시경제</div>
            </div>
          </div>
        </div>

        <div className="col">
          <div className="panel">
            <h2>펀드 순위표 <span className="tick-note">· Tick {state?.tick ?? 0}</span></h2>
            <div className="table-wrap">
              {leaderboard.length ? (
                <table>
                  <thead>
                    <tr><th>순위</th><th>전략</th><th>총자산</th><th>수익률</th><th>실현손익</th><th>MDD</th><th>포지션</th></tr>
                  </thead>
                  <tbody>
                    {leaderboard.map((r, i) => (
                      <tr key={r.key}>
                        <td><span className={`rank-badge ${i === 0 ? 'r1' : ''}`}>{i + 1}</span></td>
                        <td><span className="strategy-chip"><span className="strategy-dot" style={{ background: `var(${r.preset.colorVar})` }} />{r.preset.name}</span></td>
                        <td>{fmtMoney(r.perf.ending_equity)}</td>
                        <td className={r.perf.total_return_pct >= 0 ? 'up' : 'down'}>{fmtPct(r.perf.total_return_pct)}</td>
                        <td className={r.fund.realizedPnl > 0 ? 'up' : r.fund.realizedPnl < 0 ? 'down' : ''}>{fmtMoney(r.fund.realizedPnl)}</td>
                        <td>{fmtPct(r.perf.max_drawdown_pct)}</td>
                        <td>{Object.keys(r.fund.positions).length}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="empty">불러오는 중…</div>
              )}
            </div>
          </div>

          <div className="panel">
            <h2>펀드별 현황</h2>
            <div className="fund-grid">
              {STRATEGY_KEYS.map((key) => {
                const preset = STRATEGY_PRESETS[key];
                const fund = state?.funds[key];
                const perf = performance[key];
                return (
                  <div className="fund-card" key={key}>
                    <span className="strategy-chip"><span className="strategy-dot" style={{ background: `var(${preset.colorVar})` }} />{preset.name}</span>
                    <Sparkline history={fund?.equityCurve ?? []} colorVar={preset.colorVar} />
                    <div className="fc-stats">
                      <span>{perf ? fmtMoney(perf.ending_equity) : '—'}</span>
                      <span className={perf && perf.total_return_pct >= 0 ? 'up' : 'down'}>{perf ? fmtPct(perf.total_return_pct) : '—'}</span>
                    </div>
                    <div className="fc-sub">
                      포지션 {fund ? Object.keys(fund.positions).length : 0}개 · 실현손익 {fund ? fmtMoney(fund.realizedPnl) : '—'}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="panel">
            <h2>실행 로그 · 자율 판단 내역</h2>
            <div className="fund-tabs">
              {STRATEGY_KEYS.map((key) => (
                <button key={key} className={selectedFund === key ? 'active' : ''} onClick={() => setSelectedFund(key)}>
                  {STRATEGY_PRESETS[key].name.split(' ')[0]}
                </button>
              ))}
            </div>
            <div className="thoughts">
              {state?.funds[selectedFund]?.recentDecisions.length ? (
                state.funds[selectedFund].recentDecisions.slice(0, 60).map((d, i) => (
                  <div className="thought" key={i}>
                    <div className="meta">{new Date(d.ts).toLocaleTimeString('ko-KR', { hour12: false })} · {d.kind}</div>
                    <div className={d.kind === 'open' ? 'up' : d.kind === 'close' || d.kind === 'stop_out' ? 'down' : undefined}>
                      <strong>{d.symbol}</strong>
                      {d.decision ? ` — ${d.decision.trade_plan.action.toUpperCase()} @ ${fmtMoney(d.decision.trade_plan.entry_price)} (${d.booked ? '체결됨' : d.decision.blocked_reason || '차단됨'})` : d.note ? ` — ${d.note}` : ''}
                    </div>
                  </div>
                ))
              ) : (
                <div className="empty">아직 판단 기록이 없습니다.</div>
              )}
            </div>
          </div>
        </div>
      </main>

      <footer>
        4개의 전략 펀드가 동일한 Yahoo Finance 실시간 데이터와 동일한 하드코딩 리스크 한도(레버리지 3배, 계좌 10%,
        손절 필수, 일일 손실 서킷브레이커) 아래에서 종목 편입·제거·매수·매도를 100% 자율로 수행합니다. 실제 증권사
        연동이나 실제 자금 이동은 없습니다 — 계좌는 이 애플리케이션 안에만 존재하는 가상 잔고입니다.
      </footer>
    </>
  );
}
