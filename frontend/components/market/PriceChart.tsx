'use client';

import type { Market } from '@/lib/types';
import { fmtCents, trendColor } from '@/lib/utils';

/** Fixed 0–100 probability axis for share-price charts. */
function pricePath(pts: number[], w: number, h: number): string {
  if (!pts || pts.length < 2) return '';
  const nx = (i: number) => (i / (pts.length - 1)) * w;
  const ny = (v: number) => h - (v / 100) * h;
  let d = `M${nx(0).toFixed(2)},${ny(pts[0]).toFixed(2)}`;
  for (let i = 1; i < pts.length; i++) {
    d += ` L${nx(i).toFixed(2)},${ny(pts[i]).toFixed(2)}`;
  }
  return d;
}

function priceAreaPath(pts: number[], w: number, h: number): string {
  const line = pricePath(pts, w, h);
  return `${line} L${w},${h} L0,${h} Z`;
}

const GRID = [0, 25, 50, 75, 100];
const W = 720;
const H = 250;

export default function PriceChart({ market }: { market: Market }) {
  const pts = (market.pts ?? []).length >= 2 ? market.pts : [market.yes];
  const color = trendColor(market.trend);
  const change =
    ((pts[pts.length - 1] - pts[0]) / Math.max(1, pts[0])) * 100;

  return (
    <div className="rounded-m border border-line bg-white p-5">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="mb-1 font-mono text-[10.5px] uppercase tracking-[.06em] text-ink-3">
            YES price over time
          </div>
          <div className="flex items-baseline gap-[10px]">
            <span
              className="font-mono text-[30px] font-semibold leading-none"
              style={{ color }}
            >
              {fmtCents(market.yes)}
            </span>
            <span
              className={`font-mono text-sm font-semibold ${
                market.trend === 'up' ? 'text-pos' : 'text-neg'
              }`}
            >
              {market.trend === 'up' ? '+' : ''}
              {change.toFixed(1)}%
            </span>
          </div>
        </div>
        <div className="flex gap-3 font-mono text-[11px] text-ink-3">
          <span>Low {fmtCents(Math.min(...pts))}</span>
          <span>High {fmtCents(Math.max(...pts))}</span>
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full">
        <defs>
          <linearGradient id="price-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.18" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {GRID.map((g) => {
          const y = H - (g / 100) * H;
          return (
            <g key={g}>
              <line x1="0" y1={y} x2={W} y2={y} stroke="#E4E7EC" strokeWidth="1" />
              <text
                x="4"
                y={y - 4}
                fontSize="10"
                fill="#8A93A3"
                fontFamily="var(--font-mono)"
              >
                {fmtCents(g)}
              </text>
            </g>
          );
        })}
        <path d={priceAreaPath(pts, W, H)} fill="url(#price-fill)" />
        <path
          d={pricePath(pts, W, H)}
          fill="none"
          stroke={color}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle
          cx={W}
          cy={H - (pts[pts.length - 1] / 100) * H}
          r="3.5"
          fill={color}
          className="animate-pulse-dot"
        />
      </svg>
    </div>
  );
}