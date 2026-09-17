'use client';

import { forwardRef, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import type { Category, Market, SectionCopy } from '@/lib/types';
import { randomChange, sparkPath, trendColor } from '@/lib/utils';
import { liveOf, useMarketFeed } from '@/components/market/MarketFeed';

const TABS: { key: 'all' | Category; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'politics', label: 'Politics' },
  { key: 'crypto', label: 'Crypto' },
  { key: 'sports', label: 'Sports' },
  { key: 'culture', label: 'Culture' },
  { key: 'tech', label: 'Tech' },
  { key: 'climate', label: 'Climate' },
];

export default function Markets({
  markets,
  copy,
}: {
  markets: Market[];
  copy: SectionCopy;
}) {
  const [filter, setFilter] = useState<'all' | Category>('all');
  const feed = useMarketFeed();

  const filtered = useMemo(() => {
    const live = markets.map((m) => liveOf(m, feed.markets));
    return filter === 'all' ? live : live.filter((m) => m.cat === filter);
  }, [markets, filter, feed.markets]);

  return (
    <section className="section" id="markets">
      <div className="wrap">
        <SectionHead
          kicker={copy.kicker}
          title={copy.title}
          sub={copy.description}
        />

        <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-wrap gap-[10px]">
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
          <div className="flex items-center gap-[16px]">
            <span className="flex items-center gap-[7px] font-mono text-[11px] uppercase tracking-[.06em] text-ink-3">
              <span
                className={`h-2 w-2 rounded-full ${
                  feed.connected ? 'bg-pos animate-pulse-dot' : 'bg-line-strong'
                }`}
              />
              {feed.connected ? 'Live' : 'Syncing'}
            </span>
            <Link
              href="/markets"
              className="font-mono text-[11.5px] font-semibold text-brand transition-colors hover:text-ink"
            >
              View all markets →
            </Link>
          </div>
        </div>

        <div className="grid gap-[14px] md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((m, i) => (
            <RevealCard key={m.id} market={m} index={i} />
          ))}
        </div>
      </div>
    </section>
  );
}

/**
 * Wraps a market card. Cards are always visible (never hidden at SSR) so the
 * grid renders instantly; only the sparkline + progress bar draw in once the
 * card scrolls into view, staggered by index.
 */
function RevealCard({ market, index }: { market: Market; index: number }) {
  const ref = useRef<HTMLAnchorElement>(null);
  const [drawn, setDrawn] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === 'undefined') {
      setDrawn(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            io.unobserve(entry.target);
            // Small stagger so cards feel alive without hiding content.
            window.setTimeout(() => setDrawn(true), 550);
          }
        });
      },
      { threshold: 0.12 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const delay = (index % 6) * 70;

  return (
    <MarketCard
      ref={ref}
      market={market}
      drawn={drawn}
      delay={delay}
    />
  );
}

interface MarketCardProps {
  market: Market;
  drawn: boolean;
  delay: number;
}

const MarketCard = forwardRef<HTMLAnchorElement, MarketCardProps>(
  function MarketCard({ market: m, drawn, delay }, ref) {
    return (
      <Link
        ref={ref}
        href={`/markets/${m.id}`}
        className="group flex flex-col gap-[13px] rounded-m border border-line bg-white p-[18px] transition-all duration-200 ease-ketsa hover:-translate-y-[1px] hover:border-ink-3 hover:shadow-[0_12px_32px_-16px_rgba(12,21,38,.22)]"
      >
        <div className="flex items-center justify-between">
          <span className="rounded-[5px] bg-brand-tint px-[8px] py-[3px] font-mono text-[10px] font-semibold uppercase tracking-[.05em] text-brand">
            {m.tag}
          </span>
          {m.status === 'resolved' ? (
            <span className="rounded-[4px] bg-pos/10 px-[7px] py-[2px] font-mono text-[10px] font-bold uppercase tracking-[.05em] text-pos">
              Resolved
            </span>
          ) : (
            <span
              className={`font-mono text-xs font-bold ${
                m.trend === 'up' ? 'text-pos' : 'text-neg'
              }`}
            >
              {randomChange(m.trend)}
            </span>
          )}
        </div>

        <h3 className="line-clamp-2 font-serif text-[16.5px] font-medium leading-[1.4] text-ink">
          {m.q}
        </h3>

        <svg
          className="h-[36px] w-full"
          viewBox="0 0 200 36"
          preserveAspectRatio="none"
        >
          <path
            d={sparkPath(m.pts, 200, 36)}
            fill="none"
            stroke={trendColor(m.trend)}
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeDasharray="300"
            strokeDashoffset={drawn ? '0' : '300'}
            style={{
              transition: `stroke-dashoffset 1s cubic-bezier(.2,.7,.2,1) ${delay}ms`,
            }}
          />
        </svg>

        <div className="h-[3px] overflow-hidden rounded-full bg-line">
          <div
            className="h-full bg-ink"
            style={{
              width: `${m.yes}%`,
              transition: `width .9s cubic-bezier(.2,.7,.2,1) ${delay}ms`,
            }}
          />
        </div>

        <div className="flex gap-2 pt-[2px]">
          <div className="price-btn price-btn--yes">
            <span className="lbl">YES</span>
            <span className="val">{m.yes}¢</span>
          </div>
          <div className="price-btn price-btn--no">
            <span className="lbl">NO</span>
            <span className="val">{m.no}¢</span>
          </div>
        </div>

        <div className="flex justify-between border-t border-line pt-[11px] font-mono text-[11px] text-ink-3">
          <span>{m.meta[0]}</span>
          <span>{m.meta[1]}</span>
        </div>
      </Link>
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
        <div className="mb-[9px] flex items-center gap-[7px] font-mono text-[11.5px] uppercase tracking-[.06em] text-brand">
          <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-pos" />
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