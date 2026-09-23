'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import type { Market, Outcome, WalletPosition } from '@/lib/types';
import { useWallet } from '@/components/wallet/WalletProvider';
import { liveOf, useMarketFeed } from '@/components/market/MarketFeed';
import DashboardSidebar from '@/components/dashboard/DashboardSidebar';
import EquityChart from '@/components/dashboard/EquityChart';
import StatCard from '@/components/dashboard/StatCard';
import QuickDeposit from '@/components/dashboard/QuickDeposit';
import {
  buildEquityPoints,
  changePct,
  EQUITY_RANGES,
  filterEquityPoints,
  warmSeries,
  type EquityRange,
} from '@/lib/equity';
import { fmtBalance, fmtCents, fmtShares, sparkPath, timeAgo, trendColor } from '@/lib/utils';

interface Row {
  p: WalletPosition;
  market: Market | null;
  price: number;
  cost: number;
  value: number;
}

function rowMarket(
  p: WalletPosition,
  snapshots: Market[],
  feed: Record<string, Market>,
): Market | null {
  const fallback = snapshots.find((mk) => mk.id === p.market_id) ?? null;
  const live = fallback ? liveOf(fallback, feed) : null;
  return live ?? snapshots.find((mk) => mk.q === p.question) ?? null;
}

function rowPrice(p: WalletPosition, m: Market | null, outcome: Outcome): number {
  if (!m) return p.current_price;
  return (outcome === 'yes' ? m.yes : m.no) as number;
}

export default function DashboardShell({
  initialMarkets,
}: {
  initialMarkets: Market[];
}) {
  const { wallet, user, loading, openConnect, openAuth } = useWallet();
  const feed = useMarketFeed();
  const [range, setRange] = useState<EquityRange>('1D');

  const rows = useMemo<Row[]>(() => {
    if (!wallet) return [];
    return wallet.positions.map((p) => {
      const market = rowMarket(p, initialMarkets, feed.markets);
      const price = rowPrice(p, market, p.outcome);
      const cost = p.shares * (p.avg_price / 100);
      const value = p.shares * (price / 100);
      return { p, market, price, cost, value };
    });
  }, [wallet, initialMarkets, feed.markets]);

  const openPnl = rows.reduce((s, r) => s + (r.value - r.cost), 0);
  const totalPnl = (wallet?.realized_pnl ?? 0) + openPnl;
  const profitable = rows.filter((r) => r.value - r.cost > 0).length;
  const winRate =
    wallet && rows.length > 0 ? Math.round((profitable / rows.length) * 100) : 0;

  const equityPoints = useMemo(
    () =>
      wallet
        ? warmSeries(
            filterEquityPoints(
              buildEquityPoints(wallet.history, wallet.equity, wallet.created),
              range,
            ),
          )
        : [],
    [wallet, range],
  );
  const equityChange = changePct(equityPoints);
  const equityPositive = equityChange >= 0;

  const hour = new Date().getHours();
  const greet =
    hour < 5 ? 'Good night' : hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  const displayName = user?.name || wallet?.name || 'there';

  if (loading) {
    return <DashboardSkeleton />;
  }

  if (!wallet) {
    return (
      <section className="section">
        <div className="wrap">
          <div className="mx-auto max-w-[520px] rounded-l border border-line bg-white p-10 text-center shadow-[0_24px_60px_-30px_rgba(12,21,38,.25)]">
            <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full bg-brand-tint">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                <rect x="3" y="4" width="18" height="14" rx="2" stroke="#1447E6" strokeWidth="1.7" />
                <path d="M3 8h18M7 15h4" stroke="#1447E6" strokeWidth="1.7" strokeLinecap="round" />
              </svg>
            </div>
            <h1 className="font-serif text-[28px] font-medium">Your dashboard</h1>
            <p className="mx-auto mt-3 max-w-[380px] text-sm text-ink-2">
              Connect a play wallet or create an account to see your equity,
              positions and live P&L across every market.
            </p>
            <div className="mt-7 flex flex-wrap justify-center gap-3">
              <button className="btn btn--brand" onClick={() => openConnect()}>
                Connect wallet
              </button>
              <button className="btn btn--ghost" onClick={() => openAuth('register')}>
                Create account
              </button>
            </div>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="section">
      <div className="wrap">
        <div className="grid gap-8 lg:grid-cols-[232px_1fr]">
          {/* Sidebar */}
          <div className="hidden lg:block">
            <div className="sticky top-[88px]">
              <DashboardSidebar />
            </div>
          </div>

          {/* Main column */}
          <div className="min-w-0">
            {/* Heading */}
            <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
              <div>
                <div className="mb-[6px] font-mono text-[11px] uppercase tracking-[.07em] text-brand">
                  {user ? 'Personal dashboard' : 'Guest dashboard · play money'}
                </div>
                <h1 className="font-serif text-[clamp(26px,3.2vw,36px)] font-medium tracking-[-.01em]">
                  {greet}, {displayName}
                </h1>
                <p className="mt-[6px] text-sm text-ink-2">
                  {rows.length > 0
                    ? `${rows.length} open position${rows.length === 1 ? '' : 's'} across ${initialMarkets.length} live markets.`
                    : 'No open positions yet — find a market and take a view.'}
                </p>
              </div>
              <Link href="/portfolio" className="btn btn--brand">
                View portfolio
              </Link>
            </div>

            {/* Mobile nav */}
            <div className="mb-7 lg:hidden">
              <DashboardSidebar />
            </div>

            {/* KPI cards */}
            <div className="grid gap-[14px] sm:grid-cols-2 xl:grid-cols-4">
              <StatCard
                label="Total equity"
                value={fmtBalance(wallet.equity, wallet.currency)}
                tone="brand"
                icon={
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <path d="M16.5 9.4a4.5 4.5 0 1 0-9 0 4.5 4.5 0 0 0 9 0Z" stroke="currentColor" strokeWidth="1.7" />
                    <path d="M12 13.4V17M9.5 20h5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
                  </svg>
                }
                trend={{
                  dir: equityPositive ? 'up' : 'down',
                  label: `${equityPositive ? '+' : ''}${equityChange.toFixed(1)}% ${range.toLowerCase()}`,
                }}
              />
              <StatCard
                label="Available balance"
                value={fmtBalance(wallet.balance, wallet.currency)}
                sub={`Spendable · ${wallet.positions.length} position${wallet.positions.length === 1 ? '' : 's'} open`}
                icon={
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <rect x="2.5" y="5" width="19" height="14" rx="2" stroke="currentColor" strokeWidth="1.7" />
                    <circle cx="12" cy="12" r="2.5" stroke="currentColor" strokeWidth="1.7" />
                  </svg>
                }
              />
              <StatCard
                label="Total P&L"
                value={`${totalPnl >= 0 ? '+' : ''}${fmtBalance(totalPnl, wallet.currency)}`}
                tone={totalPnl >= 0 ? 'pos' : 'neg'}
                sub={`${fmtBalance(wallet.realized_pnl, wallet.currency)} realized`}
                icon={
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <path d="M4 19V5M4 19h16" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
                    <path d="M8 15l3-3 3 2 5-6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                }
              />
              <StatCard
                label="Open positions"
                value={`${rows.length}`}
                tone={winRate >= 50 ? 'pos' : 'neutral'}
                sub={`${winRate}% in profit`}
                icon={
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <circle cx="9" cy="9" r="5" stroke="currentColor" strokeWidth="1.7" />
                    <path d="M9 7v2l1.5 1.5M14 5h6M14 9h6M14 13h6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
                  </svg>
                }
              />
            </div>

            {/* Equity chart + right rail */}
            <div className="mt-[18px] grid gap-[18px] xl:grid-cols-[1fr_340px]">
              <div className="rounded-m border border-line bg-white p-6">
                <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="font-mono text-[10.5px] uppercase tracking-[.07em] text-ink-3">
                      Equity performance
                    </div>
                    <div
                      className={`mt-[4px] font-mono text-[22px] font-semibold tracking-[-.01em] ${
                        equityPositive ? 'text-pos' : 'text-neg'
                      }`}
                    >
                      {fmtBalance(wallet.equity, wallet.currency)}
                    </div>
                  </div>
                  <div className="flex gap-1 rounded-full border border-line bg-paper-alt p-1">
                    {EQUITY_RANGES.map((key) => (
                      <button
                        key={key}
                        onClick={() => setRange(key)}
                        className={`rounded-full px-[12px] py-[5px] font-mono text-[11px] font-semibold transition-all duration-200 ease-ketsa ${
                          range === key ? 'bg-ink text-white' : 'text-ink-3 hover:text-ink'
                        }`}
                      >
                        {key}
                      </button>
                    ))}
                  </div>
                </div>
                {equityPoints.length >= 2 ? (
                  <EquityChart
                    pts={equityPoints.map((p) => p.v)}
                    positive={equityPositive}
                  />
                ) : (
                  <div className="flex h-[220px] items-center justify-center text-ink-3">
                    Not enough history yet
                  </div>
                )}
              </div>

              <div className="flex flex-col gap-[18px]">
                <QuickDeposit />
                <AccountCard />
              </div>
            </div>

            {/* Positions */}
            <div className="mt-[18px] rounded-m border border-line bg-white">
              <div className="flex items-center justify-between border-b border-line px-6 py-4">
                <h2 className="font-serif text-[18px] font-medium">Open positions</h2>
                <Link
                  href="/portfolio"
                  className="text-[12.5px] font-semibold text-brand transition-colors hover:text-brand-ink"
                >
                  Manage →
                </Link>
              </div>
              {rows.length === 0 ? (
                <div className="px-6 py-12 text-center">
                  <p className="font-serif text-[18px] font-medium text-ink">
                    No open positions yet
                  </p>
                  <p className="mx-auto mt-1 max-w-[360px] text-[13px] text-ink-2">
                    Buy YES or NO on any market — your exposure shows up here instantly.
                  </p>
                  <Link href="/markets" className="btn btn--brand mt-5">
                    Explore markets
                  </Link>
                </div>
              ) : (
                <ul className="flex flex-col">
                  {rows
                    .slice()
                    .sort((a, b) => b.value - a.value)
                    .slice(0, 6)
                    .map((r) => (
                      <PositionRow key={`${r.p.market_id}:${r.p.outcome}`} r={r} currency={wallet.currency} />
                    ))}
                </ul>
              )}
            </div>

            {/* Recent activity */}
            <div className="mt-[18px] rounded-m border border-line bg-white">
              <div className="flex items-center justify-between border-b border-line px-6 py-4">
                <h2 className="font-serif text-[18px] font-medium">Recent activity</h2>
                <Link
                  href="/portfolio"
                  className="text-[12.5px] font-semibold text-brand transition-colors hover:text-brand-ink"
                >
                  Trade history →
                </Link>
              </div>
              {wallet.history.length === 0 ? (
                <div className="px-6 py-10 text-center text-[13px] text-ink-3">
                  No trades yet — your fills, deposits and payouts will appear here.
                </div>
              ) : (
                <ul className="flex flex-col">
                  {wallet.history
                    .slice()
                    .sort((a, b) => b.ts - a.ts)
                    .slice(0, 8)
                    .map((t, i) => (
                      <li
                        key={`${t.ts}-${i}`}
                        className="grid grid-cols-[80px_72px_1fr_auto] items-center gap-3 border-b border-line px-6 py-[13px] font-mono text-[12px] last:border-b-0"
                      >
                        <span className="text-ink-3">{timeAgo(t.ts)}</span>
                        <span
                          className={`w-fit rounded-[4px] px-[7px] py-[2px] text-[10px] font-semibold uppercase ${
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
                          className="truncate font-sans text-[12.5px] font-medium text-ink-2 transition-colors hover:text-ink"
                        >
                          {t.question}
                        </Link>
                        <span className="text-right font-semibold text-ink">
                          {t.kind === 'resolution' ? '+' : t.side === 'buy' ? '−' : '+'}
                          {fmtBalance(t.notional, wallet.currency)}
                        </span>
                      </li>
                    ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function PositionRow({ r, currency }: { r: Row; currency: string }) {
  const pnl = r.value - r.cost;
  const dir = pnl >= 0 ? ('up' as const) : ('down' as const);
  const pts = r.market?.pts ?? [r.p.avg_price, r.price];
  return (
    <li className="grid grid-cols-[1fr_auto] items-center gap-4 border-b border-line px-6 py-[14px] last:border-b-0 hover:bg-paper-alt">
      <div className="min-w-0">
        <Link
          href={`/markets/${r.p.market_id}`}
          className="block truncate font-serif text-[15px] font-medium leading-snug text-ink transition-colors hover:text-brand"
        >
          {r.p.question}
        </Link>
        <div className="mt-[6px] flex flex-wrap items-center gap-[7px]">
          <span
            className={`rounded-[4px] px-[7px] py-[2px] font-mono text-[10px] font-bold uppercase ${
              r.p.outcome === 'yes' ? 'bg-pos/10 text-pos' : 'bg-neg/10 text-neg'
            }`}
          >
            {r.p.outcome} · {fmtShares(r.p.shares)} sh
          </span>
          <span className="font-mono text-[10.5px] text-ink-3">
            avg {fmtCents(r.p.avg_price)} · now {fmtCents(r.price)}
          </span>
          <svg className="h-[18px] w-[52px]" viewBox="0 0 52 18" preserveAspectRatio="none">
            <path
              d={sparkPath(pts, 52, 18)}
              fill="none"
              stroke={trendColor(dir)}
              strokeWidth="1.5"
            />
          </svg>
        </div>
      </div>
      <div className="text-right">
        <div className="font-mono text-[17px] font-semibold tabular-nums text-ink">
          {fmtBalance(r.value, currency)}
        </div>
        <div
          className={`font-mono text-[12px] font-semibold ${
            pnl >= 0 ? 'text-pos' : 'text-neg'
          }`}
        >
          {pnl >= 0 ? '+' : ''}
          {fmtBalance(pnl, currency)}
        </div>
      </div>
    </li>
  );
}

function AccountCard() {
  const { user, openAuth } = useWallet();
  return (
    <div className="rounded-m border border-line bg-white p-5">
      <div className="mb-3 font-mono text-[10.5px] uppercase tracking-[.07em] text-ink-3">
        Account
      </div>
      {user ? (
        <>
          <div className="flex items-center gap-[10px]">
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-tint font-mono text-[13px] font-semibold uppercase text-brand">
              {user.name.slice(0, 1)}
            </span>
            <div className="min-w-0">
              <div className="truncate text-[13.5px] font-semibold text-ink">{user.name}</div>
              <div className="truncate text-[11.5px] text-ink-3">{user.email || user.phone || ''}</div>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <Link href="/portfolio" className="btn btn--ghost px-3 text-[12.5px]">
              Settings
            </Link>
            <Link href="/portfolio" className="btn btn--brand px-3 text-[12.5px]">
              Portfolio
            </Link>
          </div>
        </>
      ) : (
        <>
          <p className="mb-4 text-[12.5px] leading-snug text-ink-2">
            Playing as a guest. Create an account to keep your wallet on this
            device and unlock the full dashboard.
          </p>
          <button className="btn btn--brand w-full" onClick={() => openAuth('register')}>
            Create free account
          </button>
        </>
      )}
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <section className="section">
      <div className="wrap">
        <div className="grid gap-8 lg:grid-cols-[232px_1fr]">
          <div className="hidden lg:block">
            <div className="h-64 animate-pulse rounded-m border border-line bg-white" />
          </div>
          <div>
            <div className="h-4 w-48 animate-pulse rounded bg-paper-alt" />
            <div className="mt-4 grid gap-[14px] sm:grid-cols-2 xl:grid-cols-4">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-[110px] animate-pulse rounded-m border border-line bg-white" />
              ))}
            </div>
            <div className="mt-[18px] h-[320px] animate-pulse rounded-m border border-line bg-white" />
          </div>
        </div>
      </div>
    </section>
  );
}