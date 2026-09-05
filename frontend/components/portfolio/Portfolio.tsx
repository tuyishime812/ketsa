'use client';

import Link from 'next/link';
import { useMemo } from 'react';
import type { Market, Outcome, WalletPosition } from '@/lib/types';
import { useWallet } from '@/components/wallet/WalletProvider';
import { liveOf, useMarketFeed } from '@/components/market/MarketFeed';
import PaymentsPanel from '@/components/payments/PaymentsPanel';
import {
  fmtBalance,
  fmtCents,
  fmtShares,
  timeAgo,
} from '@/lib/utils';

function positionMarket(
  p: WalletPosition,
  snapshots: Market[],
  feed: Record<string, Market>,
): Market | null {
  const fallback =
    snapshots.find((mk) => mk.id === p.market_id) ?? null;
  const live = fallback ? liveOf(fallback, feed) : null;
  if (live) return live;
  return snapshots.find((mk) => mk.q === p.question) ?? null;
}

function priceOf(p: WalletPosition, m: Market | null, outcome: Outcome): number {
  if (!m) return p.current_price;
  return (outcome === 'yes' ? m.yes : m.no) as number;
}

export default function Portfolio({
  initialMarkets,
}: {
  initialMarkets: Market[];
}) {
  const { wallet, loading, openConnect } = useWallet();
  const feed = useMarketFeed();

  const rows = useMemo(() => {
    if (!wallet) return [];
    return wallet.positions.map((p) => {
      const market = positionMarket(p, initialMarkets, feed.markets);
      const price = priceOf(p, market, p.outcome);
      const cost = p.shares * (p.avg_price / 100);
      const value = p.shares * (price / 100);
      return { p, market, price, cost, value };
    });
  }, [wallet, initialMarkets, feed.markets]);

  const unrealized = rows.reduce((s, r) => s + (r.value - r.cost), 0);
  const totalPnl = (wallet?.realized_pnl ?? 0) + unrealized;
  const maxValue = Math.max(1, ...rows.map((r) => r.value));

  if (loading) {
    return (
      <section className="section">
        <div className="wrap">
          <div className="h-3 w-40 animate-pulse rounded bg-paper-alt" />
          <div className="mt-8 grid gap-6 lg:grid-cols-[320px_1fr]">
            <div className="h-64 rounded-m border border-line bg-white p-5" />
            <div className="h-96 rounded-m border border-line bg-white p-5" />
          </div>
        </div>
      </section>
    );
  }

  if (!wallet) {
    return (
      <section className="section">
        <div className="wrap">
          <div className="mx-auto max-w-[480px] rounded-m border border-line bg-white p-8 text-center">
            <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full bg-brand-tint">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                <path
                  d="M12 3v12m0 0l-4-4m4 4l4-4M5 21h14"
                  stroke="#E77917"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <h1 className="font-serif text-[26px] font-medium">
              Your portfolio
            </h1>
            <p className="mt-3 text-sm text-ink-2">
              Connect your simulated wallet to track balance, positions and
              P&L across every market.
            </p>
            <button
              className="btn btn--brand mt-6"
              onClick={openConnect}
            >
              Connect wallet
            </button>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="section">
      <div className="wrap">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="mb-2 font-mono text-[11px] uppercase tracking-[.07em] text-brand">
              Simulated wallet · {wallet.name}
            </div>
            <h1 className="font-serif text-[clamp(28px,3.5vw,40px)] font-medium tracking-[-.01em]">
              Portfolio
            </h1>
          </div>
          <div className="flex gap-5 text-right">
            <Summary label="Equity" value={fmtBalance(wallet.equity, wallet.currency)} strong />
            <Summary
              label="Total P&L"
              value={`${totalPnl >= 0 ? '+' : ''}${fmtBalance(totalPnl, wallet.currency)}`}
              strong
              tone={totalPnl >= 0 ? 'pos' : 'neg'}
            />
            <Summary label="Realized" value={fmtBalance(wallet.realized_pnl, wallet.currency)} />
            <Summary label="Open" value={fmtBalance(unrealized, wallet.currency)} />
          </div>
        </div>

        {rows.length === 0 ? (
          <div className="rounded-m border border-dashed border-line-strong px-6 py-16 text-center">
            <p className="font-serif text-[20px] font-medium text-ink">
              No open positions yet
            </p>
            <p className="mx-auto mt-2 max-w-[400px] text-sm text-ink-2">
              Find a market you have a view on, then buy or sell YES and NO.
            </p>
            <Link href="/markets" className="btn btn--brand mt-6">
              Explore markets
            </Link>
          </div>
        ) : (
          <div className="grid gap-6 lg:grid-cols-[340px_1fr]">
            {/* Holdings breakdown */}
            <div className="rounded-m border border-line bg-white p-5">
              <h3 className="mb-4 font-serif text-[17px] font-medium">
                Holdings
              </h3>
              <div className="flex flex-col gap-4">
                {rows.map((r) => (
                  <div key={`${r.p.market_id}:${r.p.outcome}`}>
                    <div className="mb-[6px] flex items-baseline justify-between gap-3">
                      <span className="truncate text-[12.5px] font-medium text-ink-2">
                        {r.p.outcome.toUpperCase()} · {r.p.question}
                      </span>
                      <span className="font-mono text-[11.5px] font-semibold text-ink">
                        {fmtBalance(r.value, wallet.currency)}
                      </span>
                    </div>
                    <div className="flex items-center gap-[8px]">
                      <div className="h-[7px] flex-1 overflow-hidden rounded-full bg-paper-alt">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${(r.value / maxValue) * 100}%`,
                            backgroundColor:
                              r.p.outcome === 'yes' ? '#13A95C' : '#E5484D',
                          }}
                        />
                      </div>
                      <span className="font-mono text-[10px] text-ink-3">
                        {((r.value / Math.max(wallet.equity, 1)) * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-5 border-t border-line pt-4 font-mono text-[10px] uppercase tracking-[.06em] text-ink-3">
                Balance {fmtBalance(wallet.balance, wallet.currency)}
              </p>
            </div>

            {/* Positions list */}
            <div className="flex flex-col gap-4">
              {rows.map((r) => (
                <div
                  key={`${r.p.market_id}:${r.p.outcome}`}
                  className="rounded-m border border-line bg-white p-5"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <Link
                        href={`/markets/${r.p.market_id}`}
                        className="font-serif text-[16px] font-medium leading-snug text-ink transition-colors hover:text-brand"
                      >
                        {r.p.question}
                      </Link>
                      <div className="mt-[6px] flex flex-wrap gap-[7px]">
                        <span
                          className={`rounded-[4px] px-[7px] py-[2px] font-mono text-[10px] font-semibold uppercase ${
                            r.p.outcome === 'yes'
                              ? 'bg-pos/10 text-pos'
                              : 'bg-neg/10 text-neg'
                          }`}
                        >
                          {r.p.outcome}
                        </span>
                        <span className="font-mono text-[11px] text-ink-3">
                          {fmtShares(r.p.shares)} shares @ avg {fmtCents(r.p.avg_price)}
                        </span>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-[19px] font-semibold text-ink">
                        {fmtBalance(r.value, wallet.currency)}
                      </div>
                      <div
                        className={`font-mono text-[12px] font-semibold ${
                          r.price - r.p.avg_price >= 0 ? 'text-pos' : 'text-neg'
                        }`}
                      >
                        {fmtCents(r.price - r.p.avg_price)} ·{' '}
                        {fmtBalance(r.value - r.cost, wallet.currency)}
                      </div>
                    </div>
                  </div>
                </div>
              ))}

              <div className="rounded-m border border-line bg-white p-5">
                <h3 className="mb-3 font-serif text-[17px] font-medium">
                  Trade history
                </h3>
                {wallet.history.length === 0 ? (
                  <p className="py-4 text-sm text-ink-3">No trades yet.</p>
                ) : (
                  <ul className="flex flex-col gap-[6px]">
                    {wallet.history
                      .slice()
                      .sort((a, b) => b.ts - a.ts)
                      .slice(0, 25)
                      .map((t, i) => (
                        <li
                          key={`${t.ts}-${i}`}
                          className="grid grid-cols-[84px_64px_1fr_auto_auto] items-center gap-3 font-mono text-[11.5px]"
                        >
                          <span className="text-ink-3">{timeAgo(t.ts)}</span>
                          <span
                            className={`rounded-[4px] px-[6px] py-[2px] text-[10px] font-semibold uppercase ${
                              t.side === 'buy' ? 'bg-pos/10 text-pos' : 'bg-paper-alt text-ink-2'
                            }`}
                          >
                            {t.side} {t.outcome}
                          </span>
                          <Link
                            href={`/markets/${t.market_id}`}
                            className="truncate text-ink-2 hover:text-ink"
                          >
                            {t.question}
                          </Link>
                          <span>{fmtCents(t.price)}</span>
                          <span className="text-right text-ink-2">
                            {fmtBalance(t.notional, wallet.currency)}
                          </span>
                        </li>
                      ))}
                  </ul>
                )}
              </div>

              <PaymentsPanel />
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function Summary({
  label,
  value,
  strong = false,
  tone,
}: {
  label: string;
  value: string;
  strong?: boolean;
  tone?: 'pos' | 'neg';
}) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-[.07em] text-ink-3">
        {label}
      </div>
      <div
        className={`mt-[3px] font-mono ${strong ? 'text-[19px] font-semibold' : 'text-[14px] font-medium'} ${
          tone === 'pos' ? 'text-pos' : tone === 'neg' ? 'text-neg' : 'text-ink'
        }`}
      >
        {value}
      </div>
    </div>
  );
}