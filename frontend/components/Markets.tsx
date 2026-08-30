'use client';

import { forwardRef, useEffect, useMemo, useRef, useState } from 'react';
import type { Category, Market } from '@/lib/types';
import { randomChange, sparkPath, trendColor } from '@/lib/utils';

const TABS: { key: 'all' | Category; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'politics', label: 'Politics' },
  { key: 'crypto', label: 'Crypto' },
  { key: 'sports', label: 'Sports' },
  { key: 'culture', label: 'Culture' },
  { key: 'tech', label: 'Tech' },
  { key: 'climate', label: 'Climate' },
];

export default function Markets({ markets }: { markets: Market[] }) {
  const [filter, setFilter] = useState<'all' | Category>('all');

  const filtered = useMemo(
    () => (filter === 'all' ? markets : markets.filter((m) => m.cat === filter)),
    [markets, filter],
  );

  return (
    <section className="section" id="markets">
      <div className="wrap">
        <SectionHead
          kicker="Order book"
          title="Markets moving right now"
          sub="Every price is a probability. Buy the side you believe, sell whenever the market catches up to you."
        />

        <div className="mb-8 flex flex-wrap gap-[10px]">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setFilter(t.key)}
              className={`tab ${filter === t.key ? 'is-active' : ''}`}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="grid gap-px overflow-hidden rounded-m border border-line bg-line sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((m, i) => (
            <RevealCard key={m.id} market={m} index={i} />
          ))}
        </div>
      </div>
    </section>
  );
}

/**
 * Wraps a market card with the original scroll/stagger reveal, sparkline
 * draw-in and progress-bar animation. Each card fades/slides in once it
 * enters the viewport, staggered by index.
 */
function RevealCard({ market, index }: { market: Market; index: number }) {
  const ref = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(false);
  const [drawn, setDrawn] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true);
      setDrawn(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            io.unobserve(entry.target);
            setVisible(true);
            // Let the card fade in before drawing the sparkline, mirroring
            // the original `stroke-dashoffset` transition.
            window.setTimeout(() => setDrawn(true), 550);
          }
        });
      },
      { threshold: 0.16 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const delay = (index % 6) * 70;

  return (
    <MarketCard
      ref={ref}
      market={market}
      visible={visible}
      drawn={drawn}
      delay={delay}
    />
  );
}

interface MarketCardProps {
  market: Market;
  visible: boolean;
  drawn: boolean;
  delay: number;
}

const MarketCard = forwardRef<HTMLElement, MarketCardProps>(
  function MarketCard({ market: m, visible, drawn, delay }, ref) {
    return (
      <article
        ref={ref}
        className={`group flex flex-col gap-[15px] bg-paper p-6 transition-transform duration-200 ease-ketsa hover:bg-paper-alt ${
          visible
            ? 'translate-y-0 opacity-100 transition-[opacity,transform] duration-[550ms] ease-ketsa'
            : 'translate-y-4 opacity-0'
        }`}
        style={{ transitionDelay: visible ? `${delay}ms` : '0ms' }}
      >
        <div className="flex items-center justify-between">
          <span className="font-mono text-[10px] uppercase tracking-[.05em] text-ink-3">
            {m.tag}
          </span>
          <span
            className={`font-mono text-xs font-semibold ${
              m.trend === 'up' ? 'text-pos' : 'text-neg'
            }`}
          >
            {randomChange(m.trend)}
          </span>
        </div>

        <h3 className="min-h-[48px] font-serif text-[17px] font-medium leading-[1.4] text-ink">
          {m.q}
        </h3>

        <svg className="h-[38px] w-full" viewBox="0 0 200 38" preserveAspectRatio="none">
          <path
            d={sparkPath(m.pts, 200, 38)}
            fill="none"
            stroke={trendColor(m.trend)}
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeDasharray="300"
            strokeDashoffset={drawn ? '0' : '300'}
            style={{ transition: 'stroke-dashoffset 1s cubic-bezier(.2,.7,.2,1)' }}
          />
        </svg>

        <div className="h-[3px] overflow-hidden rounded-full bg-line">
          <div
            className="h-full bg-ink"
            style={{
              width: visible ? `${m.yes}%` : '0%',
              transition: 'width .9s cubic-bezier(.2,.7,.2,1) .15s',
            }}
          />
        </div>

        <div className="flex gap-2">
          <div className="price-btn price-btn--yes">
            <span className="lbl">YES</span>
            <span className="val">{m.yes}¢</span>
          </div>
          <div className="price-btn price-btn--no">
            <span className="lbl">NO</span>
            <span className="val">{m.no}¢</span>
          </div>
        </div>

        <div className="flex justify-between font-mono text-[11px] text-ink-3">
          <span>{m.meta[0]}</span>
          <span>{m.meta[1]}</span>
        </div>
      </article>
    );
  },
);

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
