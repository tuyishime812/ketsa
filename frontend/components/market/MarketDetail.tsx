'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { fetchBookSession, fetchTradesSession } from '@/lib/api';
import type { Market, OrderBook, Trade, TradeResponse } from '@/lib/types';
import {
  daysUntil,
  fmtEndDate,
  fmtUsd,
} from '@/lib/utils';
import { useWallet } from '@/components/wallet/WalletProvider';
import { liveOf, useMarketFeed } from './MarketFeed';
import PriceChart from './PriceChart';
import OrderBookPanel from './OrderBookPanel';
import RecentTrades from './RecentTrades';
import TradeWidget from './TradeWidget';

export interface MarketDetailInitial {
  market: Market;
  book: OrderBook;
  trades: Trade[];
}

export default function MarketDetail({ initial }: { initial: MarketDetailInitial }) {
  const { markets, upsert } = useMarketFeed();
  const { refreshWallet } = useWallet();
  const m = liveOf(initial.market, markets);

  const [book, setBook] = useState<OrderBook>(initial.book);
  const [trades, setTrades] = useState<Trade[]>(initial.trades);
  const [lastTrade, setLastTrade] = useState<Trade | null>(null);

  // Reset local book/trades when navigating between markets.
  useEffect(() => {
    setBook(initial.book);
    setTrades(initial.trades);
    setLastTrade(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [m.id]);

  // Keep book + tape fresh while the page is open.
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const [b, t] = await Promise.all([
          fetchBookSession(m.id),
          fetchTradesSession(m.id),
        ]);
        if (!alive) return;
        setBook(b);
        setTrades(t);
      } catch {
        /* transient — keep last good data */
      }
    };
    void tick();
    const id = window.setInterval(tick, 5000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [m.id]);

  async function handleTraded(resp: TradeResponse) {
    upsert(resp.market);
    setBook(resp.book);
    setTrades((prev) => [resp.trade, ...prev].slice(0, 60));
    setLastTrade(resp.trade);
    try {
      await refreshWallet();
    } catch {
      /* ignore */
    }
  }

  const ends = m.end_date ? daysUntil(m.end_date) : null;

  return (
    <section className="section">
      <div className="wrap">
        <Link
          href="/markets"
          className="mb-6 inline-flex items-center gap-[7px] font-mono text-[12.5px] text-ink-2 transition-colors hover:text-ink"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <path
              d="M19 12H5M12 19l-7-7 7-7"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          All markets
        </Link>

        <div className="mb-8 flex flex-wrap items-end justify-between gap-5">
          <div className="max-w-[780px]">
            <div className="mb-3 flex flex-wrap items-center gap-[10px] font-mono text-[11px] uppercase tracking-[.06em]">
              <span className="rounded-[5px] bg-brand-tint px-[9px] py-[3px] font-semibold text-brand">
                {m.tag}
              </span>
              <span className="text-ink-3">{m.cat}</span>
              {lastTrade && (
                <span className="text-pos">
                  Last fill {lastTrade.outcome.toUpperCase()} ·{' '}
                  {lastTrade.price}¢
                </span>
              )}
            </div>
            <h1 className="font-serif text-[clamp(24px,3.2vw,38px)] font-medium leading-[1.15] tracking-[-.01em]">
              {m.q}
            </h1>
            <p className="mt-4 max-w-[640px] text-[14.5px] leading-relaxed text-ink-2">
              {m.description}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-x-9 gap-y-4 sm:grid-cols-4">
            <Stat label="Volume" value={fmtUsd(m.volume ?? 0)} />
            <Stat label="Liquidity" value={fmtUsd(m.liquidity ?? 0)} />
            <Stat label="Traders" value={m.meta[1]} />
            <Stat
              label="Ends"
              value={ends !== null ? fmtEndDate(m.end_date) : 'Open'}
            />
          </div>
        </div>

        <div className="grid gap-6 lg:grid-cols-[1fr_400px]">
          <div className="flex flex-col gap-6">
            <PriceChart market={m} />
            <OrderBookPanel market={m} book={book} />
            <RecentTrades trades={trades} />
          </div>

          <div className="lg:sticky lg:top-[86px] lg:self-start">
            <TradeWidget market={m} book={book} onTraded={handleTraded} />
          </div>
        </div>
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-[.07em] text-ink-3">
        {label}
      </div>
      <div className="mt-[3px] font-mono text-[15px] font-semibold text-ink">
        {value}
      </div>
    </div>
  );
}