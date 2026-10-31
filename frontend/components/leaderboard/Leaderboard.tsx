'use client';

import { useEffect, useState } from 'react';
import { fetchLeaderboard } from '@/lib/api';
import type { LeaderboardEntry } from '@/lib/types';
import { useWallet } from '@/components/wallet/WalletProvider';
import { fmtBalance } from '@/lib/utils';
import { onPush, startPush } from '@/lib/push';

const MEDAL = ['🥇', '🥈', '🥉'];

export default function Leaderboard() {
  const { wallet, loading: walletLoading } = useWallet();
  const [rows, setRows] = useState<LeaderboardEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const data = await fetchLeaderboard(50);
        if (alive) setRows(data);
      } catch {
        if (alive) setError('Leaderboard is unavailable right now.');
      }
    }
    void load();
    const timer = window.setInterval(load, 30_000);
    // Push: refresh immediately when a resolution or balance change fires.
    startPush();
    const off = onPush((ev) => {
      if (ev.type === 'leaderboard' || ev.type === 'resolution') void load();
    });
    return () => {
      alive = false;
      window.clearInterval(timer);
      off();
    };
  }, []);

  return (
    <section className="section">
      <div className="wrap">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-[7px] font-mono text-[11px] uppercase tracking-[.07em] text-brand">
              <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-pos" />
              Live rankings
            </div>
            <h1 className="font-serif text-[clamp(28px,3.5vw,40px)] font-medium tracking-[-.01em]">
              Leaderboard
            </h1>
            <p className="mt-2 max-w-[520px] text-[15px] text-ink-2">
              Top simulated wallets by equity. Ranked live as markets move —
              trade your way up the board.
            </p>
          </div>
        </div>

        <div className="overflow-hidden rounded-m border border-line bg-white">
          <div className="grid grid-cols-[44px_1fr_90px_90px_64px_40px] items-center gap-2 border-b border-line bg-paper-alt/60 px-[16px] py-[10px] font-mono text-[10px] font-semibold uppercase tracking-[.06em] text-ink-3 sm:grid-cols-[56px_1fr_120px_120px_90px_40px]">
            <span>Rank</span>
            <span>Trader</span>
            <span className="text-right">Equity</span>
            <span className="text-right">P&L</span>
            <span className="text-right">Positions</span>
            <span />
          </div>

          {error && (
            <div className="px-6 py-14 text-center text-sm text-ink-3">{error}</div>
          )}
          {!error && rows === null && (
            <div className="px-6 py-14 text-center text-sm text-ink-3">
              <span className="mr-2 inline-block h-2 w-2 animate-pulse-dot rounded-full bg-brand" />
              Loading leaderboard…
            </div>
          )}
          {!error && rows !== null && rows.length === 0 && (
            <div className="px-6 py-14 text-center text-sm text-ink-3">
              No traders yet — be the first on the board by connecting a wallet.
            </div>
          )}

          {rows !== null && rows.length > 0 && (
            <ul>
              {rows.map((r) => {
                const isYou = !walletLoading && wallet?.id === r.wallet_id;
                return (
                  <li
                    key={r.wallet_id}
                    className={`grid grid-cols-[44px_1fr_90px_90px_64px_40px] items-center gap-2 border-b border-line px-[16px] py-[12px] text-[13px] last:border-b-0 ${
                      isYou ? 'bg-brand-tint/40' : 'hover:bg-paper'
                    }`}
                  >
                    <span className="font-mono text-[13px] font-bold tabular-nums text-ink-2">
                      {r.rank <= 3 ? MEDAL[r.rank - 1] : `#${r.rank}`}
                    </span>
                    <span className="min-w-0 truncate font-semibold text-ink">
                      <span className="hidden sm:inline">{r.name}</span>
                      <span className="sm:hidden">{r.name}</span>
                      {isYou && (
                        <span className="ml-2 rounded-[4px] bg-brand px-[6px] py-[2px] font-mono text-[9px] font-bold uppercase tracking-[.05em] text-white">
                          You
                        </span>
                      )}
                    </span>
                    <span className="text-right font-mono font-semibold tabular-nums text-ink">
                      {fmtBalance(r.equity, r.currency)}
                    </span>
                    <span
                      className={`text-right font-mono tabular-nums ${
                        r.realized_pnl >= 0 ? 'text-pos' : 'text-neg'
                      }`}
                    >
                      {r.realized_pnl >= 0 ? '+' : ''}
                      {fmtBalance(r.realized_pnl, r.currency)}
                    </span>
                    <span className="text-right font-mono tabular-nums text-ink-2">
                      {r.positions}
                    </span>
                    <span />
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <p className="mt-4 font-mono text-[10.5px] uppercase tracking-[.07em] text-ink-3">
          Equity = cash + open positions, priced live
        </p>
      </div>
    </section>
  );
}
