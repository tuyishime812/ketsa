import type { TickerItem } from '@/lib/types';

export default function Ticker({ items }: { items: TickerItem[] }) {
  const doubled = [...items, ...items];
  const arrow = (d: TickerItem['d']) => (d === 'up' ? '▲' : '▼');

  return (
    <div className="overflow-hidden whitespace-nowrap border-b border-line bg-paper-alt py-[11px]">
      <div className="inline-flex animate-ticker-scroll hover:[animation-play-state:paused]">
        {doubled.map((it, i) => (
          <span
            key={`${it.t}-${i}`}
            className="inline-flex items-center gap-2 border-r border-line px-6 font-mono text-[12.5px] text-ink-2"
          >
            <b className="font-semibold text-ink">{it.t}</b>
            <span className={it.d === 'up' ? 'text-pos' : 'text-neg'}>
              {it.v} {arrow(it.d)}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
