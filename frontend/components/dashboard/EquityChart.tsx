'use client';

import { useEffect, useRef } from 'react';
import { areaPath, palette, sparkPath } from '@/lib/utils';

const W = 720;
const H = 220;

function formatAxis(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (abs >= 10_000) return `${(v / 1000).toFixed(0)}K`;
  return Math.round(v).toLocaleString('en-US');
}

export default function EquityChart({
  pts,
  positive,
}: {
  pts: number[];
  positive: boolean;
}) {
  const lineRef = useRef<SVGPathElement>(null);
  const areaRef = useRef<SVGPathElement>(null);
  const playedRef = useRef(false);

  const color = positive ? palette.pos : palette.neg;
  const line = sparkPath(pts, W, H);
  const area = areaPath(pts, W, H);
  const max = Math.max(...pts);
  const min = Math.min(...pts);
  const lastX = W;
  const lastY =
    H - ((pts[pts.length - 1] - min) / (max - min || 1)) * (H - 40) - 20;

  useEffect(() => {
    const line = lineRef.current;
    const area = areaRef.current;
    if (!line || !area) return;
    const len = line.getTotalLength();
    line.style.transition = 'none';
    line.style.strokeDasharray = String(len);
    line.style.strokeDashoffset = playedRef.current ? '0' : String(len);
    area.style.transition = 'none';
    area.style.opacity = playedRef.current ? '1' : '0';
    void (line as SVGPathElement).getBoundingClientRect();
    line.style.transition = 'stroke-dashoffset 1.1s cubic-bezier(.2,.7,.2,1)';
    area.style.transition = 'opacity .9s ease .3s';
    line.style.strokeDashoffset = '0';
    area.style.opacity = '1';
    playedRef.current = true;
  }, []);

  return (
    <div className="relative">
      <div className="pointer-events-none absolute left-0 top-0 z-[1] flex w-full justify-between px-1 font-mono text-[10px] font-semibold tabular-nums text-ink-3">
        <span>{formatAxis(max)}</span>
        <span>{formatAxis(min)}</span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="h-[220px] w-full overflow-visible"
      >
        <defs>
          <linearGradient
            id="equityGrad"
            x1="0"
            y1="0"
            x2="0"
            y2="1"
          >
            <stop offset="0%" stopColor={color} stopOpacity="0.18" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[40, 95, 150, 205].map((y) => (
          <line key={y} className="stroke-line" x1="0" y1={y} x2={W} y2={y} />
        ))}
        <path ref={areaRef} d={area} fill="url(#equityGrad)" />
        <path
          ref={lineRef}
          d={line}
          fill="none"
          stroke={color}
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle
          cx={lastX}
          cy={lastY}
          r="5"
          fill={color}
          opacity="0"
          className="animate-pulse-ring"
        />
        <circle
          cx={lastX}
          cy={lastY}
          r="4.5"
          fill={color}
          style={{ filter: `drop-shadow(0 2px 4px ${color}55)` }}
        />
      </svg>
    </div>
  );
}