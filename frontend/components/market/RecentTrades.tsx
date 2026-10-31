'use client';

import type { Trade } from '@/lib/types';
import { fmtCents, fmtShares, fmtUsd, timeAgo } from '@/lib/utils';

export default function RecentTrades({ trades }: { trades: Trade[] }) {
  return (
    <div className="rounded-m border border-line bg-white p-5">
      <h3 className="mb-3 font-serif text-[17px] font-medium">
        Recent trades
      </h3>
      {trades.length === 0 ? (
        <p className="py-6 text-center text-sm text-ink-3">
          Be the first to trade this market.
        </p>
      ) : (
        <ul className="flex flex-col gap-[7px]">
          {trades.map((t, i) => (
            <li
              key={`${t.ts}-${i}`}
              className="grid grid-cols-[72px_64px_1fr_1fr_1fr] items-center gap-2 font-mono text-[11.5px]"
            >
              <span className="text-ink-3">{timeAgo(t.ts)}</span>
              <span
                className={`inline-flex w-fit items-center gap-[5px] rounded-[4px] px-[6px] py-[2px] text-[10px] font-semibold uppercase ${
                  t.outcome === 'yes' && t.side === 'buy'
                    ? 'bg-pos/10 text-pos'
                    : t.outcome === 'no'
                      ? 'bg-neg/10 text-neg'
                      : 'bg-paper-alt text-ink-2'
                }`}
              >
                {t.side} {t.outcome}
              </span>
              <span className="text-ink">{fmtShares(t.qty)} shares</span>
              <span className="font-semibold" style={{ color: t.outcome === 'no' ? 'inherit' : undefined }}>
                {fmtCents(t.price)}
              </span>
              <span className="text-right text-ink-2">{fmtUsd(t.notional)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
