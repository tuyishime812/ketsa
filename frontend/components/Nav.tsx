'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';
import { useWallet } from '@/components/wallet/WalletProvider';
import NotificationsBell from '@/components/notifications/NotificationsBell';
import { fmtBalance } from '@/lib/utils';

const NAV_LINKS = [
  { href: '/dashboard', label: 'Dashboard', requiresWallet: true },
  { href: '/wallet', label: 'Wallet', requiresWallet: true },
  { href: '/markets', label: 'Markets' },
  { href: '/leaderboard', label: 'Leaderboard' },
  { href: '/portfolio', label: 'Portfolio', requiresWallet: true },
];

export default function Nav() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const { wallet, user, loading, openConnect, openAuth, disconnect, logout } =
    useWallet();

  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);
  const signOut = () => (user ? logout() : disconnect());
  const links = NAV_LINKS.filter((l) => !l.requiresWallet || wallet);

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

        {/* Desktop menu bar */}
        <nav className="hidden items-center gap-[2px] md:flex" aria-label="Primary">
          {links.map((l) => (
            <Link
              key={l.label}
              href={l.href}
              className={`relative flex items-center gap-[7px] rounded-[8px] px-[15px] py-[9px] text-sm font-semibold leading-none transition-colors duration-200 ease-ketsa ${
                isActive(l.href)
                  ? 'bg-brand-tint text-brand-ink'
                  : 'text-ink-2 hover:bg-paper-alt hover:text-ink'
              }`}
            >
              {isActive(l.href) && (
                <span className="h-[5px] w-[5px] rounded-full bg-brand" />
              )}
              {l.label}
              {l.href === '/markets' && (
                <span className="ml-[2px] hidden items-center gap-[3px] rounded-full border border-line-strong bg-paper px-[7px] py-[2px] font-mono text-[9.5px] font-bold uppercase tracking-[.05em] text-ink-3 lg:inline-flex">
                  Live
                </span>
              )}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-[10px]">
          <div className="hidden md:block">
            <NotificationsBell />
          </div>
          <div className="hidden md:block">
            <RightControls
              wallet={wallet}
              user={user}
              loading={loading}
              onConnect={() => openConnect()}
              onLogin={() => openAuth('login')}
              onRegister={() => openAuth('register')}
              onDisconnect={signOut}
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

      {/* Mobile menu */}
      {open && (
        <div className="border-t border-line bg-white md:hidden">
          <div className="wrap flex flex-col gap-1 py-4">
            {links.map((l) => (
              <Link
                key={l.label}
                href={l.href}
                className={`flex items-center gap-[8px] rounded-[9px] px-[14px] py-[11px] text-sm font-semibold transition-colors ${
                  isActive(l.href)
                    ? 'bg-brand-tint text-brand-ink'
                    : 'text-ink-2 hover:bg-paper-alt hover:text-ink'
                }`}
                onClick={() => setOpen(false)}
              >
                <span
                  className={`h-[6px] w-[6px] rounded-full ${
                    isActive(l.href) ? 'bg-brand' : 'bg-line-strong'
                  }`}
                />
                {l.label}
              </Link>
            ))}
            <div className="mt-3 border-t border-line pt-4">
              <div className="flex items-center justify-between pb-3">
                <NotificationsBell />
              </div>
              <div className="flex gap-3">
                <RightControls
                  wallet={wallet}
                  user={user}
                  loading={loading}
                  onConnect={() => {
                    setOpen(false);
                    openConnect();
                  }}
                  onLogin={() => {
                    setOpen(false);
                    openAuth('login');
                  }}
                  onRegister={() => {
                    setOpen(false);
                    openAuth('register');
                  }}
                  onDisconnect={signOut}
                  className="w-full"
                  stack
                />
              </div>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}

function RightControls({
  wallet,
  user,
  loading,
  onConnect,
  onLogin,
  onRegister,
  onDisconnect,
  className = '',
  stack = false,
}: {
  wallet: ReturnType<typeof useWallet>['wallet'];
  user: ReturnType<typeof useWallet>['user'];
  loading: boolean;
  onConnect: () => void;
  onLogin: () => void;
  onRegister: () => void;
  onDisconnect: () => void;
  className?: string;
  stack?: boolean;
}) {
  if (loading) {
    return (
      <span
        className="inline-flex h-[38px] w-[38px] items-center justify-center rounded-full border border-line-strong"
        aria-hidden
      >
        <span className="animate-pulse-dot h-2 w-2 rounded-full bg-brand" />
      </span>
    );
  }

  // Authenticated (or guest wallet attached) — show the account chip.
  if (wallet) {
    return (
      <div
        className={`flex items-center gap-[8px] ${
          stack ? 'flex-col w-full' : ''
        }`}
      >
        <Link
          href="/dashboard"
          className="group flex w-full items-center gap-[10px] rounded-full border border-line-strong bg-paper px-[14px] py-[8px] transition-colors duration-200 ease-ketsa hover:border-ink"
        >
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-tint font-mono text-[10px] font-semibold uppercase text-brand">
            {(user?.name || wallet.name).slice(0, 1)}
          </span>
          <span className="text-left leading-none">
            <span className="block max-w-[110px] truncate text-[12px] font-semibold text-ink">
              {user?.name || wallet.name}
            </span>
            <span className="mt-[3px] block font-mono text-[10.5px] text-brand">
              {fmtBalance(wallet.equity, wallet.currency)}
            </span>
          </span>
        </Link>
        <button
          aria-label="Log out"
          title="Log out"
          className="rounded-full border border-line-strong p-[7px] text-ink-3 transition-colors hover:border-ink hover:text-ink"
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

  // Signed out — show Log in / Create account.
  return (
    <div
      className={`flex items-center gap-[8px] ${
        stack ? 'flex-col w-full' : ''
      }`}
    >
      <button
        className={`btn btn--ghost ${className}`}
        onClick={onLogin}
        aria-label="Log in"
      >
        Log in
      </button>
      <button className={`btn btn--brand ${className}`} onClick={onRegister}>
        Create account
      </button>
      <button
        className="hidden text-[12.5px] font-medium text-ink-3 transition-colors hover:text-ink md:inline-block"
        onClick={onConnect}
      >
        Play wallet
      </button>
    </div>
  );
}