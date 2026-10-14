'use client';

import { useMemo } from 'react';
import { useWallet } from '@/components/wallet/WalletProvider';
import StatCard from '@/components/dashboard/StatCard';
import PaymentsPanel from '@/components/payments/PaymentsPanel';
import AccountSettings from '@/components/portfolio/AccountSettings';
import { fmtBalance } from '@/lib/utils';

/**
 * The wallet hub: balance at a glance, real-money top-up / cash-out, and
 * account security. Kept separate from the trading dashboard so the money
 * surface is a single, obvious destination.
 */
export default function WalletDashboard() {
  const { wallet, user, loading, openConnect } = useWallet();

  const inPositions = useMemo(
    () => (wallet ? wallet.positions.reduce((s, p) => s + p.value, 0) : 0),
    [wallet],
  );

  if (loading) {
    return (
      <section className="section">
        <div className="wrap">
          <div className="h-3 w-40 animate-pulse rounded bg-paper-alt" />
          <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_360px]">
            <div className="h-80 rounded-m border border-line bg-white p-5" />
            <div className="h-64 rounded-m border border-line bg-white p-5" />
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
                <rect
                  x="3"
                  y="6"
                  width="18"
                  height="13"
                  rx="2.5"
                  stroke="#E77917"
                  strokeWidth="1.8"
                />
                <path
                  d="M3 10h18M16 14.5h2"
                  stroke="#E77917"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                />
              </svg>
            </div>
            <h1 className="font-serif text-[26px] font-medium">Your wallet</h1>
            <p className="mt-3 text-sm text-ink-2">
              Connect a wallet to see your balance, top up or cash out, and
              manage your account.
            </p>
            <button className="btn btn--brand mt-6" onClick={openConnect}>
              Connect wallet
            </button>
          </div>
        </div>
      </section>
    );
  }

  const currency = wallet.currency;

  return (
    <section className="section">
      <div className="wrap">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-5">
          <div>
            <div className="mb-2 font-mono text-[11px] uppercase tracking-[.07em] text-brand">
              {user ? 'Account wallet' : 'Guest wallet'} · {wallet.name}
            </div>
            <h1 className="font-serif text-[clamp(28px,3.5vw,40px)] font-medium tracking-[-.01em]">
              Wallet
            </h1>
            <p className="mt-[6px] max-w-[520px] text-sm text-ink-2">
              Your balance, real-money top-ups and cash-outs, and account
              security — in one place.
            </p>
          </div>
          <div className="grid grow gap-[12px] sm:grid-cols-2 lg:max-w-[760px] lg:grid-cols-4">
            <StatCard
              label="Available"
              value={fmtBalance(wallet.balance, currency)}
              tone="brand"
            />
            <StatCard
              label="In positions"
              value={fmtBalance(inPositions, currency)}
              sub={`${wallet.positions.length} open`}
            />
            <StatCard
              label="Equity"
              value={fmtBalance(wallet.equity, currency)}
            />
            <StatCard
              label="Cash out"
              value={fmtBalance(wallet.withdrawable, currency)}
              sub="deposited funds"
            />
          </div>
        </div>

        <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
          <div className="flex flex-col gap-6">
            <PaymentsPanel />
          </div>

          <div className="flex flex-col gap-6">
            {user ? (
              <AccountSettings />
            ) : (
              <div className="rounded-m border border-line bg-white p-5">
                <h3 className="mb-2 font-serif text-[17px] font-medium">
                  Guest wallet
                </h3>
                <p className="text-[12.5px] leading-snug text-ink-2">
                  You&apos;re trading with play money. Create an account to keep
                  this balance and move real MWK.
                </p>
              </div>
            )}

            <div className="rounded-m border border-line bg-white p-5">
              <h3 className="mb-3 font-serif text-[17px] font-medium">
                How money works
              </h3>
              <ul className="flex flex-col gap-[10px] text-[12.5px] leading-snug text-ink-2">
                <li className="flex items-start gap-2">
                  <span className="mt-[6px] h-[5px] w-[5px] shrink-0 rounded-full bg-brand" />
                  Deposits via Airtel Money or TNM Mpamba credit your available
                  balance.
                </li>
                <li className="flex items-start gap-2">
                  <span className="mt-[6px] h-[5px] w-[5px] shrink-0 rounded-full bg-brand" />
                  Trading moves money between your balance and your positions;
                  equity tracks both.
                </li>
                <li className="flex items-start gap-2">
                  <span className="mt-[6px] h-[5px] w-[5px] shrink-0 rounded-full bg-brand" />
                  Only funds you deposited are cashable out — play balance and
                  trading winnings stay in the app.
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
