'use client';

import { useEffect, useRef, useState } from 'react';
import type { DashboardData, PortfolioStats, Position } from '@/lib/types';
import { areaPath, fmt, sparkPath, trendColor } from '@/lib/utils';

const RANGE_KEYS = ['1D', '1W', '1M', '1Y'] as const;

export default function Dashboard({
  data,
  stats,
}: {
  data: DashboardData;
  stats: PortfolioStats;
}) {
  const [range, setRange] = useState<'1D' | '1W' | '1M' | '1Y'>('1D');
  const [posRevealed, setPosRevealed] = useState(false);
  const [balanceDisplay, setBalanceDisplay] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);

  const series = data.ranges[range];
  const rangeSuffix =
    range === '1D' ? 'today' : range.toLowerCase().replace('1', '');

  // Count-up the portfolio balance from its previous value to the selected
  // range's value, matching the original single-file build.
  const prevBalance = useRef(series.balance);
  useEffect(() => {
    const target = series.balance;
    const from = prevBalance.current;
    prevBalance.current = target;
    const duration = 900;
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const p = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      setBalanceDisplay(Math.round(from + (target - from) * eased));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [series.balance]);

  // Reveal the panel + stagger rows + draw chart once it scrolls into view.
  useEffect(() => {
    const el = panelRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            io.unobserve(entry.target);
            setPosRevealed(true);
          }
        });
      },
      { threshold: 0.2 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <section className="section section--alt" id="dashboard">
      <div className="wrap">
        <SectionHead
          kicker="Dashboard"
          title="Your positions, priced live"
          sub="Track performance across every market you're in, updated in real time as odds move."
        />

        <div
          ref={panelRef}
          className="overflow-hidden rounded-l border border-line-strong bg-paper shadow-[0_1px_2px_rgba(12,21,38,.04),0_24px_60px_-30px_rgba(12,21,38,.2)]"
        >
          <div className="flex flex-wrap items-start justify-between gap-4 px-7 pt-7">
            <div>
              <div className="mb-2 font-mono text-[11px] uppercase tracking-[.05em] text-ink-3">
                Portfolio value
              </div>
              <div className="font-serif text-[38px] font-medium tracking-[-.01em] text-ink">
                ${fmt(balanceDisplay)}
              </div>
              <div
                className={`mt-[6px] inline-flex items-center gap-[5px] rounded-full px-[9px] py-[3px] font-mono text-[13px] font-semibold ${
                  series.change >= 0 ? 'bg-pos-tint text-pos' : 'bg-neg-tint text-neg'
                }`}
              >
                {series.change >= 0 ? '+' : ''}
                {series.change.toFixed(1)}% {rangeSuffix}
              </div>
            </div>

            <div className="flex gap-1 rounded-full border border-line bg-paper-alt p-1">
              {RANGE_KEYS.map((key) => (
                <button
                  key={key}
                  onClick={() => setRange(key)}
                  className={`rounded-full px-[13px] py-[6px] font-mono text-xs font-semibold transition-all duration-200 ease-ketsa ${
                    range === key ? 'bg-ink text-white' : 'text-ink-3 hover:text-ink'
                  }`}
                >
                  {key}
                </button>
              ))}
            </div>
          </div>

          <div className="relative h-[220px] px-5 pt-5">
            <PortfolioChart pts={series.pts} rangeKey={range} />
          </div>

          <div className="mt-6 grid grid-cols-1 border-t border-line sm:grid-cols-3">
            <StatTile label="Total P&L" val={`+$${fmt(stats.pnl)}`} up />
            <StatTile label="Open positions" val={String(stats.open_positions)} />
            <StatTile label="Win rate" val={`${stats.win_rate}%`} up />
          </div>

          <div className="border-t border-line">
            <div className="grid grid-cols-[1.4fr_0.8fr_0.8fr] gap-2 border-b border-line bg-paper-alt px-7 py-3 font-mono text-[10px] uppercase tracking-[.05em] text-ink-3 sm:grid-cols-[1.5fr_0.7fr_0.7fr_0.7fr_0.7fr]">
              <span>Market</span>
              <span className="hidden sm:block">Trend</span>
              <span className="hidden sm:block">Avg</span>
              <span className="text-right">Current</span>
              <span className="text-right">P&L</span>
            </div>
            {data.positions.map((p, i) => (
              <PositionRow key={p.name} pos={p} revealed={posRevealed} index={i} />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function SectionHead({
  kicker,
  title,
  sub,
}: {
  kicker: string;
  title: string;
  sub: string;
}) {
  return (
    <div className="mb-[38px] flex flex-wrap items-end justify-between gap-6">
      <div>
        <div className="mb-[9px] font-mono text-[11.5px] uppercase tracking-[.06em] text-brand">
          {kicker}
        </div>
        <h2 className="font-serif text-[clamp(26px,3vw,34px)] font-medium tracking-[-.01em]">
          {title}
        </h2>
      </div>
      <p className="max-w-[420px] text-[15px] text-ink-2">{sub}</p>
    </div>
  );
}

const CHART_W = 720;
const CHART_H = 200;

function PortfolioChart({ pts, rangeKey }: { pts: number[]; rangeKey: string }) {
  const lineRef = useRef<SVGPathElement>(null);
  const areaRef = useRef<SVGPathElement>(null);
  const pulseRef = useRef<SVGCircleElement>(null);
  const prevKeyRef = useRef<string | null>(null);

  const max = Math.max(...pts);
  const min = Math.min(...pts);
  const nx = (i: number) => (i / (pts.length - 1)) * CHART_W;
  const ny = (v: number) => CHART_H - ((v - min) / (max - min || 1)) * (CHART_H - 34) - 17;

  const lineD = sparkPath(pts, CHART_W, CHART_H);
  const areaD = areaPath(pts, CHART_W, CHART_H);
  const lastX = nx(pts.length - 1);
  const lastY = ny(pts[pts.length - 1]);

  const key = `${rangeKey}-${pts[0]}-${pts.length}`;

  useEffect(() => {
    const line = lineRef.current;
    const area = areaRef.current;
    const pulse = pulseRef.current;
    if (!line || !area || !pulse) return;

    const animate = prevKeyRef.current !== null && prevKeyRef.current !== key;
    prevKeyRef.current = key;

    const len = line.getTotalLength();
    line.style.transition = 'none';
    line.style.strokeDasharray = String(len);
    line.style.strokeDashoffset = animate ? String(len) : '0';
    area.style.transition = 'none';
    area.style.opacity = animate ? '0' : '1';
    pulse.style.opacity = '0';
    void (line as SVGPathElement).getBoundingClientRect();

    if (animate) {
      line.style.transition = 'stroke-dashoffset 1.15s cubic-bezier(.2,.7,.2,1)';
      line.style.strokeDashoffset = '0';
      area.style.transition = 'opacity 1s ease .35s';
      area.style.opacity = '1';
      const t = setTimeout(() => {
        pulse.style.transition = 'opacity .3s';
        pulse.style.opacity = '1';
      }, 1150);
      return () => clearTimeout(t);
    }
    pulse.style.transition = 'opacity .3s';
    pulse.style.opacity = '1';
  }, [key]);

  return (
    <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} preserveAspectRatio="none" className="h-full w-full overflow-visible">
      <defs>
        <linearGradient id="dashGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#1447E6" stopOpacity="0.16" />
          <stop offset="100%" stopColor="#1447E6" stopOpacity="0" />
        </linearGradient>
      </defs>
      <line className="stroke-line" x1="0" y1="30" x2={CHART_W} y2="30" />
      <line className="stroke-line" x1="0" y1="100" x2={CHART_W} y2="100" />
      <line className="stroke-line" x1="0" y1="170" x2={CHART_W} y2="170" />
      <path ref={areaRef} d={areaD} fill="url(#dashGrad)" />
      <path
        ref={lineRef}
        d={lineD}
        fill="none"
        stroke="#1447E6"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        ref={pulseRef}
        cx={lastX}
        cy={lastY}
        r="5"
        fill="#1447E6"
        opacity="0"
        className="animate-pulse-ring"
        style={{ transformOrigin: 'center' }}
      />
      <circle
        cx={lastX}
        cy={lastY}
        r="4.5"
        fill="#1447E6"
        style={{ filter: 'drop-shadow(0 2px 4px rgba(20,71,230,.35))' }}
      />
    </svg>
  );
}

function StatTile({
  label,
  val,
  up,
}: {
  label: string;
  val: string;
  up?: boolean;
}) {
  return (
    <div className="border-b border-line px-7 py-[22px] sm:border-b-0 sm:border-r sm:last:border-r-0">
      <div className="mb-2 font-mono text-[11px] uppercase tracking-[.04em] text-ink-3">
        {label}
      </div>
      <div
        className={`font-mono text-2xl font-semibold ${
          up ? 'text-pos' : 'text-ink'
        }`}
      >
        {val}
      </div>
    </div>
  );
}

function PositionRow({
  pos,
  revealed,
  index,
}: {
  pos: Position;
  revealed: boolean;
  index: number;
}) {
  const pnl = ((pos.cur - pos.avg) / pos.avg) * 100;
  const dir = pnl >= 0 ? 'up' : 'down';
  const delay = 200 + index * 90;

  return (
    <div
      className={`grid grid-cols-[1.4fr_0.8fr_0.8fr] items-center gap-2 border-b border-line px-7 py-[14px] transition-all duration-500 ease-ketsa hover:bg-paper-alt sm:grid-cols-[1.5fr_0.7fr_0.7fr_0.7fr_0.7fr] ${
        revealed ? 'translate-x-0 opacity-100' : '-translate-x-[10px] opacity-0'
      }`}
      style={{ transitionDelay: revealed ? `${delay}ms` : '0ms' }}
    >
      <span className="text-[13.5px] font-semibold text-ink">{pos.name}</span>
      <svg className="hidden h-[20px] w-[56px] sm:block" viewBox="0 0 56 20" preserveAspectRatio="none">
        <path d={sparkPath(pos.pts, 56, 20)} fill="none" stroke={trendColor(dir)} strokeWidth="1.6" />
      </svg>
      <span className="text-right font-mono text-[13px] text-ink-2">{pos.avg}¢</span>
      <span className="text-right font-mono text-[13px] text-ink-2">{pos.cur}¢</span>
      <span
        className={`text-right font-mono text-[13px] font-semibold ${
          pnl >= 0 ? 'text-pos' : 'text-neg'
        }`}
      >
        {pnl >= 0 ? '+' : ''}
        {pnl.toFixed(1)}%
      </span>
    </div>
  );
}
