'use client';

import Link from 'next/link';
import { useMemo } from 'react';
import type { Market, Outcome, WalletPosition } from '@/lib/types';
import { useWallet } from '@/components/wallet/WalletProvider';
import { liveOf, useMarketFeed } from '@/components/market/MarketFeed';
import AccountSettings from '@/components/portfolio/AccountSettings';
import PaymentsPanel from '@/components/payments/PaymentsPanel';
import StatCard from '@/components/dashboard/StatCard';
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

interface Row {
  p: WalletPosition;
  market: Market | null;
  price: number;
  cost: number;
  value: number;
}

interface HoldingGroup {
  market_id: string;
  question: string;
  yes: Row | null;
  no: Row | null;
}

export default function Portfolio({
  initialMarkets,
}: {
  initialMarkets: Market[];
}) {
  const { wallet, loading, openConnect, user } = useWallet();
  const feed = useMarketFeed();

  const rows = useMemo(() => {
    if (!wallet) return [] as Row[];
    return wallet.positions.map((p) => {
      const market = positionMarket(p, initialMarkets, feed.markets);
      const price = priceOf(p, market, p.outcome);
      const cost = p.shares * (p.avg_price / 100);
      const value = p.shares * (price / 100);
      return { p, market, price, cost, value };
    });
  }, [wallet, initialMarkets, feed.markets]);

  const groups = useMemo<HoldingGroup[]>(() => {
    const byMarket = new Map<string, HoldingGroup>();
    for (const r of rows) {
      const g =
        byMarket.get(r.p.market_id) ?? {
          market_id: r.p.market_id,
          question: r.p.question,
          yes: null,
          no: null,
        };
      g[r.p.outcome] = r;
      byMarket.set(r.p.market_id, g);
    }
    return [...byMarket.values()];
  }, [rows]);

  const unrealized = rows.reduce((s, r) => s + (r.value - r.cost), 0);
  const totalPnl = (wallet?.realized_pnl ?? 0) + unrealized;
  const winRate =
    wallet && rows.length > 0
      ? Math.round((rows.filter((r) => r.value - r.cost > 0).length / rows.length) * 100)
      : 0;
  const currency = wallet?.currency ?? 'MWK';

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
        <div className="mb-8 flex flex-wrap items-end justify-between gap-5">
          <div>
            <div className="mb-2 font-mono text-[11px] uppercase tracking-[.07em] text-brand">
              Simulated wallet · {wallet.name}
            </div>
            <h1 className="font-serif text-[clamp(28px,3.5vw,40px)] font-medium tracking-[-.01em]">
              Portfolio
            </h1>
            <p className="mt-[6px] max-w-[520px] text-sm text-ink-2">
              Balance, open exposure and P&L across every market, plus wandePay
              top-up and cash-out.
            </p>
          </div>
          <div className="grid grow gap-[12px] sm:grid-cols-2 lg:grid-cols-4 lg:max-w-[760px]">
            <StatCard
              label="Equity"
              value={fmtBalance(wallet.equity, currency)}
              tone="brand"
            />
            <StatCard
              label="Total P&L"
              value={`${totalPnl >= 0 ? '+' : ''}${fmtBalance(totalPnl, currency)}`}
              tone={totalPnl >= 0 ? 'pos' : 'neg'}
              sub={`${fmtBalance(unrealized, currency)} unrealized`}
            />
            <StatCard
              label="Realized P&L"
              value={`${wallet.realized_pnl >= 0 ? '+' : ''}${fmtBalance(wallet.realized_pnl, currency)}`}
              tone={wallet.realized_pnl >= 0 ? 'pos' : 'neg'}
            />
            <StatCard
              label="Open positions"
              value={`${rows.length}`}
              tone={winRate >= 50 ? 'pos' : 'neutral'}
              sub={`${winRate}% in profit`}
            />
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
            {/* Left column: holdings + account */}
            <div className="flex flex-col gap-6">
              <div className="rounded-m border border-line bg-white p-5">
                <h3 className="mb-4 font-serif text-[17px] font-medium">
                  Holdings <span className="text-ink-3">· net exposure</span>
                </h3>
                <div className="flex flex-col gap-4">
                  {groups.map((g) => {
                    const gMax = Math.max(1, g.yes?.value ?? 0, g.no?.value ?? 0);
                    const net = (g.yes?.value ?? 0) - (g.no?.value ?? 0);
                    return (
                      <div key={g.market_id}>
                        <div className="mb-[6px] flex items-baseline justify-between gap-3">
                          <Link
                            href={`/markets/${g.market_id}`}
                            className="truncate text-[12.5px] font-medium text-ink-2 transition-colors hover:text-ink"
                          >
                            {g.question}
                          </Link>
                          <span
                            className={`font-mono text-[11px] font-semibold ${
                              net >= 0 ? 'text-pos' : 'text-neg'
                            }`}
                          >
                            net {fmtBalance(Math.abs(net), wallet.currency)}{' '}
                            {net >= 0 ? 'long' : 'short'}
                          </span>
                        </div>
                        <LadderRow
                          outcome="yes"
                          row={g.yes}
                          max={gMax}
                          currency={wallet.currency}
                        />
                        <LadderRow
                          outcome="no"
                          row={g.no}
                          max={gMax}
                          currency={wallet.currency}
                        />
                      </div>
                    );
                  })}
                </div>
                <p className="mt-5 border-t border-line pt-4 font-mono text-[10px] uppercase tracking-[.06em] text-ink-3">
                  Balance {fmtBalance(wallet.balance, wallet.currency)}
                </p>
              </div>

              {user && <AccountSettings />}
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
                              t.kind === 'resolution'
                                ? t.price > 0
                                  ? 'bg-pos/10 text-pos'
                                  : 'bg-neg/10 text-neg'
                                : t.side === 'buy'
                                  ? 'bg-pos/10 text-pos'
                                  : 'bg-paper-alt text-ink-2'
                            }`}
                          >
                            {t.kind === 'resolution'
                              ? t.price > 0
                                ? 'Payout'
                                : 'Expired'
                              : `${t.side} ${t.outcome}`}
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

function LadderRow({
  outcome,
  row,
  max,
  currency,
}: {
  outcome: Outcome;
  row: Row | null;
  max: number;
  currency: string;
}) {
  if (!row) return null;
  const isYes = outcome === 'yes';
  return (
    <div className="flex items-center gap-[8px] py-[2px]">
      <span
        className={`w-[40px] font-mono text-[10px] font-bold uppercase ${
          isYes ? 'text-pos' : 'text-neg'
        }`}
      >
        {outcome}
      </span>
      <div className="h-[8px] flex-1 overflow-hidden rounded-full bg-paper-alt">
        <div
          className={`h-full rounded-full ${isYes ? 'bg-pos' : 'bg-neg'}`}
          style={{ width: `${(row.value / max) * 100}%` }}
        />
      </div>
      <span className="w-[118px] truncate text-right font-mono text-[10.5px] text-ink-2">
        {fmtShares(row.p.shares)} sh · {fmtBalance(row.value, currency)}
      </span>
    </div>
  );
}