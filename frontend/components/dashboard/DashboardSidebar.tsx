'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';
import { useWallet } from '@/components/wallet/WalletProvider';
import { fmtBalance } from '@/lib/utils';

const LINKS: { href: string; label: string; icon: ReactNode }[] = [
  {
    href: '/dashboard',
    label: 'Overview',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
        <rect x="3" y="3" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.7" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.7" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.7" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.7" />
      </svg>
    ),
  },
  {
    href: '/wallet',
    label: 'Wallet',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
        <rect x="3" y="6" width="18" height="13" rx="2.5" stroke="currentColor" strokeWidth="1.7" />
        <path d="M3 10h18M16 14.5h2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    href: '/portfolio',
    label: 'Portfolio',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
        <path d="M20 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2Z" stroke="currentColor" strokeWidth="1.7" />
        <path d="M16 11a4 4 0 0 0-8 0M2 13h20" stroke="currentColor" strokeWidth="1.7" />
      </svg>
    ),
  },
  {
    href: '/markets',
    label: 'Markets',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
        <path d="M3 17l6-6 4 4 8-8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M14 7h6v6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    href: '/leaderboard',
    label: 'Leaderboard',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
        <path d="M8 21h8M12 17v4M7 4h10v4a5 5 0 0 1-10 0V4Z" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M7 6H4a2 2 0 0 0 2 4h1M17 6h3a2 2 0 0 1-2 4h-1" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      </svg>
    ),
  },
];

export default function DashboardSidebar() {
  const pathname = usePathname();
  const { user, wallet } = useWallet();

  return (
    <aside className="flex flex-col gap-1">
      {LINKS.map((l) => {
        const active = pathname === l.href || pathname.startsWith(`${l.href}/`);
        return (
          <Link
            key={l.href}
            href={l.href}
            className={`flex items-center gap-[11px] rounded-[10px] px-[13px] py-[10px] text-[13.5px] font-semibold transition-all duration-200 ease-ketsa ${
              active
                ? 'bg-ink text-white shadow-[0_10px_24px_-12px_rgba(12,21,38,.55)]'
                : 'text-ink-2 hover:bg-paper-alt hover:text-ink'
            }`}
          >
            <span
              className={
                active ? 'text-brand-tint' : 'text-ink-3 group-hover:text-ink'
              }
            >
              {l.icon}
            </span>
            {l.label}
            {active && (
              <span className="ml-auto h-[6px] w-[6px] rounded-full bg-brand" />
            )}
          </Link>
        );
      })}

      <div className="mt-5 rounded-m border border-line bg-white p-4">
        <div className="font-mono text-[9.5px] uppercase tracking-[.08em] text-ink-3">
          {user ? 'Signed in' : 'Guest wallet'}
        </div>
        <div className="mt-[6px] flex items-center gap-[9px]">
          <span className="flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-full bg-brand-tint font-mono text-[11px] font-semibold uppercase text-brand">
            {(user?.name || wallet?.name || '?').slice(0, 1)}
          </span>
          <span className="min-w-0">
            <span className="block truncate text-[12.5px] font-semibold leading-tight text-ink">
              {user?.name || wallet?.name || 'Not connected'}
            </span>
            <span className="block truncate font-mono text-[10.5px] text-ink-3">
              {wallet ? fmtBalance(wallet.equity, wallet.currency) : 'Connect a wallet'}
            </span>
          </span>
        </div>
        {user && (
          <p className="mt-[8px] truncate text-[11px] text-ink-3">{user.email || user.phone || ''}</p>
        )}
      </div>
    </aside>
  );
}
