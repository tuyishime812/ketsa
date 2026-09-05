'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import type { Category, Market } from '@/lib/types';
import {
  daysUntil,
  fmtEndDate,
  fmtUsd,
  sparkPath,
  trendColor,
} from '@/lib/utils';
import { liveOf, useMarketFeed } from './MarketFeed';

const CATS: ('all' | Category)[] = [
  'all',
  'politics',
  'crypto',
  'sports',
  'culture',
  'tech',
  'climate',
];

type SortKey = 'volume' | 'liquidity' | 'end' | 'newest';

const SORTS: { key: SortKey; label: string }[] = [
  { key: 'volume', label: 'Volume' },
  { key: 'liquidity', label: 'Liquidity' },
  { key: 'end', label: 'Ending soon' },
  { key: 'newest', label: 'Newest' },
];

export default function MarketsExplorer({ initial }: { initial: Market[] }) {
  const feed = useMarketFeed();
  const [query, setQuery] = useState('');
  const [cat, setCat] = useState<'all' | Category>('all');
  const [sort, setSort] = useState<SortKey>('volume');

  const markets = useMemo(
    () => initial.map((m) => liveOf(m, feed.markets)),
    [initial, feed.markets],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    let out = markets.filter(
      (m) =>
        (cat === 'all' || m.cat === cat) &&
        (!q ||
          `${m.q} ${m.tag} ${m.id}`.toLowerCase().includes(q)),
    );
    const vol = (m: Market) => m.volume ?? 0;
    const liq = (m: Market) => m.liquidity ?? 0;
    const end = (m: Market) =>
      m.end_date ? new Date(m.end_date).getTime() : Number.MAX_SAFE_INTEGER;
    const created = (m: Market) =>
      m.created ? new Date(m.created).getTime() : 0;
    out = [...out];
    switch (sort) {
      case 'volume':
        out.sort((a, b) => vol(b) - vol(a));
        break;
      case 'liquidity':
        out.sort((a, b) => liq(b) - liq(a));
        break;
      case 'end':
        out.sort((a, b) => end(a) - end(b));
        break;
      case 'newest':
        out.sort((a, b) => created(b) - created(a));
        break;
    }
    return out;
  }, [markets, query, cat, sort]);

  return (
    <section className="section">
      <div className="wrap">
        <div className="mb-[30px] flex flex-wrap items-end justify-between gap-5">
          <div>
            <div className="mb-[9px] flex items-center gap-2 font-mono text-[11.5px] uppercase tracking-[.06em] text-brand">
              <span className="flex items-center gap-[7px]">
                <span
                  className={`h-2 w-2 rounded-full ${
                    feed.connected ? 'bg-pos animate-pulse-dot' : 'bg-line-strong'
                  }`}
                />
                {feed.connected ? 'Live order books' : 'Syncing'}
              </span>
            </div>
            <h1 className="font-serif text-[clamp(30px,4vw,42px)] font-medium tracking-[-.01em]">
              Markets
            </h1>
          </div>
          <p className="max-w-[380px] text-[15px] text-ink-2">
            Every price is a probability. Pick a market and put a number on
            what you believe.
          </p>
        </div>

        <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-1 flex-col gap-3 sm:flex-row sm:items-center">
            <div className="relative w-full sm:max-w-[320px]">
              <svg
                className="pointer-events-none absolute left-[13px] top-1/2 -translate-y-1/2 text-ink-3"
                width="15"
                height="15"
                viewBox="0 0 24 24"
                fill="none"
              >
                <circle
                  cx="11"
                  cy="11"
                  r="7"
                  stroke="currentColor"
                  strokeWidth="1.8"
                />
                <path
                  d="M20 20l-3.5-3.5"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                />
              </svg>
              <input
                className="field w-full pl-[36px]"
                placeholder="Search markets…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
          </div>

          <select
            className="field w-full border-0 bg-transparent sm:w-auto"
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
            aria-label="Sort markets"
          >
            {SORTS.map((s) => (
              <option key={s.key} value={s.key}>
                Sort by {s.label}
              </option>
            ))}
          </select>
        </div>

        <div className="mb-7 flex flex-wrap gap-[10px]">
          {CATS.map((c) => (
            <button
              key={c}
              onClick={() => setCat(c)}
              className={`tab ${cat === c ? 'is-active' : ''}`}
            >
              {c === 'all' ? 'All' : c[0].toUpperCase() + c.slice(1)}
            </button>
          ))}
        </div>

        {filtered.length === 0 ? (
          <div className="rounded-m border border-dashed border-line-strong px-6 py-12 text-center text-sm text-ink-2">
            No markets match your search.
          </div>
        ) : (
          <div className="grid gap-[14px] md:grid-cols-2 xl:grid-cols-3">
            {filtered.map((m) => (
              <MarketListCard key={m.id} market={m} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function MarketListCard({ market }: { market: Market }) {
  const m = market;
  const ends = daysUntil(m.end_date);

  return (
    <Link
      href={`/markets/${m.id}`}
      className="group flex flex-col gap-[13px] rounded-m border border-line bg-white p-[18px] transition-all duration-200 ease-ketsa hover:-translate-y-[1px] hover:border-ink"
    >
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-[.05em] text-brand">
          {m.tag}
        </span>
        <span
          className={`flex items-center gap-[5px] font-mono text-[11px] ${
            ends === 0 ? 'text-neg' : 'text-ink-3'
          }`}
        >
          {ends > 0
            ? ends === 1
              ? 'Ends tomorrow'
              : `Ends in ${ends}d`
            : ends === 0
              ? 'Closing'
              : 'Closed'}
          <span className="flex h-1.5 w-1.5 rounded-full bg-current" />
        </span>
      </div>

      <h3 className="min-h-[44px] font-serif text-[15.5px] font-medium leading-[1.4] text-ink">
        {m.q}
      </h3>

      <div className="flex items-end gap-[14px]">
        <div className="flex flex-1 gap-[7px]">
          <div className="price-btn price-btn--yes">
            <span className="lbl">YES</span>
            <span className="val">{m.yes}¢</span>
          </div>
          <div className="price-btn price-btn--no">
            <span className="lbl">NO</span>
            <span className="val">{m.no}¢</span>
          </div>
        </div>
        <svg
          className="h-[26px] w-[92px] shrink-0"
          viewBox="0 0 92 26"
          preserveAspectRatio="none"
        >
          <path
            d={sparkPath(m.pts, 92, 26)}
            fill="none"
            stroke={trendColor(m.trend)}
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>

      <div className="flex justify-between border-t border-line pt-[11px] font-mono text-[11px] text-ink-3">
        <span>Vol {fmtUsd(m.volume ?? 0)}</span>
        <span>Liq {fmtUsd(m.liquidity ?? 0)}</span>
        <span>{fmtEndDate(m.end_date)}</span>
      </div>
    </Link>
  );
}