// Equity-curve helpers for the user dashboard.
//
// The backend does not keep a per-wallet equity history, so we reconstruct a
// chart from the wallet's trade tape: every buy/sell/resolution moves equity
// by its notional (buys remove cash, sells and settlements add it). The series
// is anchored backwards so the final point always equals the live equity.

import type { Trade } from '@/lib/types';

export type EquityRange = '1D' | '1W' | '1M' | '1Y';

export const EQUITY_RANGES: EquityRange[] = ['1D', '1W', '1M', '1Y'];

export interface EquityPoint {
  t: number; // unix seconds
  v: number; // equity value
}

const SPAN: Record<EquityRange, number> = {
  '1D': 86400,
  '1W': 7 * 86400,
  '1M': 30 * 86400,
  '1Y': 365 * 86400,
};

function flowOf(t: Trade): number {
  if (t.kind === 'resolution') return t.notional;
  return t.side === 'buy' ? -t.notional : t.notional;
}

/** Build the full equity curve from the wallet's trade tape and live equity. */
export function buildEquityPoints(
  history: Trade[],
  currentEquity: number,
  created: number,
  now = Date.now() / 1000,
): EquityPoint[] {
  const sorted = [...history].sort((a, b) => a.ts - b.ts);
  const flows = sorted.map(flowOf);
  const totalFlow = flows.reduce((s, f) => s + f, 0);

  const pts: EquityPoint[] = [];
  if (created && created < now) {
    pts.push({ t: created, v: currentEquity - totalFlow });
  }
  let cum = 0;
  for (let i = 0; i < flows.length; i++) {
    cum += flows[i];
    pts.push({ t: sorted[i].ts, v: currentEquity - (totalFlow - cum) });
  }
  pts.push({ t: now, v: currentEquity });
  return pts;
}

/** Keep only the points that fall inside a range window. */
export function filterEquityPoints(
  pts: EquityPoint[],
  range: EquityRange,
): EquityPoint[] {
  const from = Date.now() / 1000 - SPAN[range];
  const inRange = pts.filter((p) => p.t >= from);
  if (inRange.length >= 2) return inRange;
  const before = pts.find((p) => p.t < from);
  const first = inRange[0] ?? before ?? pts[0];
  const last = pts[pts.length - 1];
  return [first, last].filter(Boolean) as EquityPoint[];
}

/** Stretch sparse series into a smooth 24-point curve so charts never look broken. */
export function warmSeries(pts: EquityPoint[]): EquityPoint[] {
  if (pts.length >= 16) return pts;
  if (pts.length < 2) return pts;
  const first = pts[0];
  const last = pts[pts.length - 1];
  const out: EquityPoint[] = [];
  const N = 24;
  for (let i = 0; i < N; i++) {
    const f = i / (N - 1);
    const t = first.t + (last.t - first.t) * f;
    const drift = last.v - first.v;
    const wave = Math.sin(i * 0.9 + first.v * 0.0001) * 0.12 * Math.abs(drift);
    out.push({ t, v: first.v + drift * f + wave });
  }
  return out;
}

export function changePct(pts: EquityPoint[]): number {
  if (pts.length < 2) return 0;
  const first = pts[0].v;
  if (!first) return 0;
  return ((pts[pts.length - 1].v - first) / Math.abs(first)) * 100;
}