// Shared rendering helpers ported from the original single-file build.

export type Trend = 'up' | 'down';

/** Build an SVG polyline path `d` string from an array of numeric points. */
export function sparkPath(pts: number[], w: number, h: number): string {
  if (!pts || pts.length < 2) return '';
  const max = Math.max(...pts);
  const min = Math.min(...pts);
  const range = max - min || 1;
  const nx = (i: number) => (i / (pts.length - 1)) * w;
  const ny = (v: number) => h - ((v - min) / range) * (h - 4) - 2;
  let d = `M${nx(0).toFixed(2)},${ny(pts[0]).toFixed(2)}`;
  for (let i = 1; i < pts.length; i++) {
    d += ` L${nx(i).toFixed(2)},${ny(pts[i]).toFixed(2)}`;
  }
  return d;
}

/** Build an area path (same line + closing to bottom) — used by the dashboard chart. */
export function areaPath(pts: number[], w: number, h: number): string {
  const line = sparkPath(pts, w, h);
  return `${line} L${w},${h} L0,${h} Z`;
}

/** Theme tokens resolved to concrete colors for non-Tailwind SVG attributes. */
export const palette = {
  pos: '#0F8F5F',
  neg: '#C13333',
  brand: '#1447E6',
  ink3: '#8A93A3',
};

export const trendColor = (t: Trend) => (t === 'up' ? palette.pos : palette.neg);

/** Random up/down change string ("+3.2%" / "-1.4%"). */
export function randomChange(t: Trend): string {
  const amt = (2 + Math.random() * 6).toFixed(1);
  return `${t === 'up' ? '+' : '-'}${amt}%`;
}

/** Format a number with thousands separators. */
export function fmt(n: number): string {
  return n.toLocaleString('en-US');
}

// ---------------------------------------------------------------------------
// Marketplace formatting helpers
// ---------------------------------------------------------------------------

/** Compact dollar formatting: $2.4M, $98K, $640. */
export function fmtUsd(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
}

/** Full dollar amount with cents: $1,234.56 */
export function fmtUsdFull(n: number): string {
  return `$${n.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Wallet money with currency code: MK 1,234.56 */
export function fmtBalance(n: number, currency = 'MWK'): string {
  const label = (currency || 'MWK').toUpperCase() === 'USD' ? '$' : `MK `;
  return `${label}${n.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Percentage display for share prices: 41¢ */
export function fmtCents(cents: number): string {
  return `${Math.round(cents)}¢`;
}

/** Number / shares display with grouping + up to 2 decimals. */
export function fmtShares(n: number): string {
  return n.toLocaleString('en-US', {
    maximumFractionDigits: n < 10 ? 2 : 0,
  });
}

/** Render a raw epoch (seconds) timestamp as a short relative "4s ago". */
export function timeAgo(ts: number): string {
  const s = Math.floor((Date.now() / 1000 - ts) / 1000);
  if (!isFinite(s) || s < 0) return 'now';
  if (s < 5) return 'now';
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

/** Format an ISO end_date into a readable date. */
export function fmtEndDate(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('en-US', {
    timeZone: 'UTC',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

/** Whole days until an ISO date (from now, UTC). */
export function daysUntil(iso?: string | null): number {
  if (!iso) return 0;
  const target = new Date(iso).getTime() / 1000;
  if (!isFinite(target)) return 0;
  return Math.max(0, Math.ceil((target - Date.now() / 1000) / 86400));
}
