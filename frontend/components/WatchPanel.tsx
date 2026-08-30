'use client';

import { useEffect, useRef, useState } from 'react';
import type { WatchItem } from '@/lib/types';
import { sparkPath } from '@/lib/utils';

interface RowState {
  price: number;
  pts: number[];
  delta: number;
}

/**
 * The "Market watch" signature panel. Prices jitter slightly on an interval,
 * flashing green/red exactly like the original single-file build.
 */
export default function WatchPanel({ items }: { items: WatchItem[] }) {
  const [rows, setRows] = useState<RowState[]>(
    items.map((it) => ({ price: it.price, pts: [...it.pts], delta: 0 })),
  );
  const [flash, setFlash] = useState<Record<number, string>>({});
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    timerRef.current = setInterval(() => {
      setRows((prev) => {
        const nextFlash: Record<number, string> = {};
        const next = prev.map((r, i) => {
          const delta = Math.random() * 5 - 2.4;
          const price = Math.max(1, Math.min(99, Math.round(r.price + delta)));
          const dir = price >= r.price ? 'up' : 'down';
          nextFlash[i] = dir;
          const pts = [...r.pts.slice(1), price];
          return { price, pts, delta: price - r.price };
        });
        setFlash(nextFlash);
        return next;
      });
    }, 2800);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  return (
    <div className="overflow-hidden rounded-m border border-line-strong bg-panel shadow-[0_1px_2px_rgba(12,21,38,.04),0_16px_40px_-24px_rgba(12,21,38,.18)]">
      <div className="flex items-center justify-between border-b border-line bg-paper px-[18px] py-[13px]">
        <span className="font-mono text-[11.5px] uppercase tracking-[.06em] text-ink-2">
          Market watch
        </span>
        <span className="flex items-center gap-[6px] font-mono text-[10.5px] text-pos">
          <span className="h-[5px] w-[5px] animate-pulse-dot-fast rounded-full bg-pos" />
          Live
        </span>
      </div>

      <div className="grid grid-cols-[1.4fr_0.8fr_0.7fr] gap-2 border-b border-line px-[18px] py-[9px] font-mono text-[10px] uppercase tracking-[.05em] text-ink-3 sm:grid-cols-[1.6fr_0.9fr_0.8fr_0.7fr]">
        <span>Market</span>
        <span className="hidden sm:block" />
        <span className="text-right">Price</span>
        <span className="hidden text-right sm:block">24h</span>
      </div>

      {rows.map((r, i) => {
        const item = items[i];
        const dir = flash[i];
        return (
          <div
            key={item.name}
            className={`grid grid-cols-[1.4fr_0.8fr_0.7fr] items-center gap-2 border-b border-line px-[18px] py-3 transition-colors duration-500 ease-ketsa sm:grid-cols-[1.6fr_0.9fr_0.8fr_0.7fr] ${
              dir === 'up' ? 'bg-pos-tint' : dir === 'down' ? 'bg-neg-tint' : ''
            }`}
          >
            <div>
              <span className="block text-[13px] font-semibold text-ink">{item.name}</span>
              <span className="mt-[1px] block text-[11px] text-ink-3">{item.cat}</span>
            </div>
            <svg
              className="hidden h-[22px] w-[64px] sm:block"
              viewBox="0 0 64 22"
              preserveAspectRatio="none"
            >
              <path
                d={sparkPath(r.pts, 64, 22)}
                fill="none"
                strokeWidth="1.6"
                stroke={dir === 'up' ? '#0F8F5F' : dir === 'down' ? '#C13333' : '#8A93A3'}
              />
            </svg>
            <span className="text-right font-mono text-[13.5px] font-semibold text-ink">
              {r.price}¢
            </span>
            <span
              className={`hidden text-right font-mono text-xs font-semibold sm:block ${
                dir === 'up' ? 'text-pos' : dir === 'down' ? 'text-neg' : 'text-ink-2'
              }`}
            >
              {r.delta >= 0 ? '+' : ''}
              {r.delta.toFixed(0)}
            </span>
          </div>
        );
      })}

      <div className="flex justify-between bg-paper px-[18px] py-[11px] font-mono text-[10.5px] text-ink-3">
        <span>Updated seconds ago</span>
        <span>UTC</span>
      </div>
    </div>
  );
}
