'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useWallet } from '@/components/wallet/WalletProvider';
import { fmtBalance } from '@/lib/utils';

const NAV_LINKS = [
  { href: '/markets', label: 'Markets' },
  { href: '/portfolio', label: 'Portfolio' },
  { href: '/#how', label: 'How it works' },
];

export default function Nav() {
  const [open, setOpen] = useState(false);
  const { wallet, loading, openConnect, disconnect } = useWallet();

  return (
    <header className="sticky top-0 z-[100] border-b border-line bg-[rgba(255,255,255,.92)] backdrop-blur-[10px]">
      <div className="wrap flex h-[68px] items-center justify-between">
        <Link
          href="/"
          className="flex items-center gap-[9px] font-serif text-[22px] font-semibold italic text-ink"
        >
          <span className="h-2 w-2 rounded-full bg-brand" />
          Ketsa
        </Link>

        <nav
          className={`${
            open
              ? 'absolute left-0 right-0 top-[68px] flex flex-col gap-4 border-b border-line bg-white px-5 pb-6 pt-[18px]'
              : 'hidden items-center gap-[34px] md:flex'
          }`}
        >
          {NAV_LINKS.map((l) => (
            <Link
              key={l.label}
              href={l.href}
              className="text-sm font-medium text-ink-2 transition-colors duration-200 ease-ketsa hover:text-ink"
              onClick={() => setOpen(false)}
            >
              {l.label}
            </Link>
          ))}

          <div className="mt-1 md:hidden">
            <WalletButton
              wallet={wallet}
              loading={loading}
              onConnect={openConnect}
              onDisconnect={disconnect}
              className="w-full"
            />
          </div>
        </nav>

        <div className="flex items-center gap-[10px]">
          <div className="hidden md:block">
            <WalletButton
              wallet={wallet}
              loading={loading}
              onConnect={openConnect}
              onDisconnect={disconnect}
            />
          </div>
          <button
            className="md:hidden"
            aria-label="Menu"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path
                d={open ? 'M6 6L18 18M18 6L6 18' : 'M4 7H20M4 12H20M4 17H20'}
                stroke="#0C1526"
                strokeWidth="1.8"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>
      </div>
    </header>
  );
}

function WalletButton({
  wallet,
  loading,
  onConnect,
  onDisconnect,
  className = '',
}: {
  wallet: ReturnType<typeof useWallet>['wallet'];
  loading: boolean;
  onConnect: () => void;
  onDisconnect: () => void;
  className?: string;
}) {
  if (loading) {
    return (
      <span className="inline-flex items-center gap-2 rounded-full border border-line-strong px-[16px] py-[9px] text-sm font-semibold text-ink-3">
        <span className="animate-pulse-dot">•</span> Loading
      </span>
    );
  }

  if (!wallet) {
    return (
      <button
        className={`btn btn--brand ${className}`}
        onClick={onConnect}
        aria-label="Connect wallet"
      >
        Connect wallet
      </button>
    );
  }

  return (
    <div className="flex items-center gap-[8px]">
      <Link
        href="/portfolio"
        className="group flex items-center gap-[10px] rounded-full border border-line-strong bg-paper px-[14px] py-[8px] transition-colors duration-200 ease-ketsa hover:border-ink"
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-tint font-mono text-[10px] font-semibold uppercase text-brand">
          {wallet.name.slice(0, 1)}
        </span>
        <span className="text-left leading-none">
          <span className="block max-w-[110px] truncate text-[12px] font-semibold text-ink">
            {wallet.name}
          </span>
          <span className="mt-[3px] block font-mono text-[10.5px] text-brand">
            {fmtBalance(wallet.equity, wallet.currency)}
          </span>
        </span>
      </Link>
      <button
        aria-label="Disconnect wallet"
        title="Disconnect"
        className="rounded-full border border-transparent p-[6px] text-ink-3 transition-colors hover:border-line-strong hover:text-ink"
        onClick={onDisconnect}
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
          <path
            d="M9 3H5.5A1.5 1.5 0 0 0 4 4.5v15A1.5 1.5 0 0 0 5.5 21H9M16 8l4 4-4 4M20 12H9"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
    </div>
  );
}