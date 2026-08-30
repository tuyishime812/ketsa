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
