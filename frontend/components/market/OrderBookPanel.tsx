'use client';

import type { Market, OrderBook as OrderBookT } from '@/lib/types';
import { fmtCents, fmtShares } from '@/lib/utils';

function Ladder({
  asks,
  bids,
  bestAsk,
  bestBid,
}: {
  asks: { price: number; size: number }[];
  bids: { price: number; size: number }[];
  bestAsk: number | null;
  bestBid: number | null;
}) {
  const maxSize = Math.max(
    1,
    ...asks.map((l) => l.size),
    ...bids.map((l) => l.size),
  );
  const spread = bestAsk !== null && bestBid !== null ? bestAsk - bestBid : null;

  return (
    <div className="flex flex-col gap-[7px] text-[12px]">
      <div className="flex gap-3 font-mono text-[10px] uppercase tracking-[.07em] text-ink-3">
        <span className="w-[142px]">Price</span>
        <span>Size</span>
        <span className="ml-auto">{spread === null ? '' : `spread ${fmtCents(spread).replace('¢', '')}¢`}</span>
      </div>

      {asks.map((l) => (
        <div
          key={`a${l.price}`}
          className="relative flex items-center justify-between gap-3 overflow-hidden rounded-[4px] px-[7px] py-[3px]"
        >
          <span
            className="absolute inset-y-0 left-0 bg-neg/10"
            style={{ width: `${(l.size / maxSize) * 100}%` }}
          />
          <span className="relative font-mono text-neg">{fmtCents(l.price)}</span>
          <span className="relative font-mono text-ink-2">{fmtShares(l.size)}</span>
        </div>
      ))}

      <div className="my-1 flex items-center justify-between border-y border-line bg-paper-alt px-[7px] py-[5px] font-mono text-[11.5px]">
        <span className="font-mono font-semibold text-pos">YES</span>
        <span className="uppercase tracking-[.07em] text-ink-3">Mid</span>
        <span className="font-mono font-semibold text-neg">NO</span>
      </div>

      {bids.map((l) => (
        <div
          key={`b${l.price}`}
          className="relative flex items-center justify-between gap-3 overflow-hidden rounded-[4px] px-[7px] py-[3px]"
        >
          <span
            className="absolute inset-y-0 right-0 bg-pos/10"
            style={{ width: `${(l.size / maxSize) * 100}%` }}
          />
          <span className="relative font-mono text-pos">{fmtCents(l.price)}</span>
          <span className="relative font-mono text-ink-2">{fmtShares(l.size)}</span>
        </div>
      ))}
    </div>
  );
}

export default function OrderBookPanel({ market, book }: { market: Market; book: OrderBookT }) {
  const yesBid = book.bids[0]?.price ?? null;
  const yesAsk = book.asks[0]?.price ?? null;
  const noBid = book.no_bids[0]?.price ?? null;
  const noAsk = book.no_asks[0]?.price ?? null;

  if (market.status === 'resolved') {
    const winner = market.resolved_outcome ?? (market.yes > market.no ? 'yes' : 'no');
    return (
      <div className="flex flex-col gap-5 rounded-m border border-line bg-white p-5">
        <div className="flex items-center justify-between">
          <h3 className="font-serif text-[17px] font-medium">
            Order book <span className="text-ink-3">· final</span>
          </h3>
          <span
            className={`font-mono text-[10.5px] font-semibold uppercase tracking-[.06em] ${
              winner === 'yes' ? 'text-pos' : 'text-neg'
            }`}
          >
            {winner.toUpperCase()} 100¢ · NO 0¢
          </span>
        </div>
        <div className="flex flex-col gap-[7px]">
          <div className="flex items-center justify-between rounded-[6px] border border-pos/20 bg-pos/5 px-[13px] py-[10px]">
            <span className="font-mono text-[12px] text-pos">
              YES settled at {market.yes}¢
            </span>
            <span className="font-mono text-[10px] uppercase tracking-[.06em] text-ink-3">
              Payout $1/share
            </span>
          </div>
          <div className="flex items-center justify-between rounded-[6px] border border-line bg-paper-alt px-[13px] py-[10px]">
            <span className="font-mono text-[12px] text-neg">
              NO settled at {market.no}¢
            </span>
            <span className="font-mono text-[10px] uppercase tracking-[.06em] text-ink-3">
              Expired
            </span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5 rounded-m border border-line bg-white p-5">
      <div className="flex items-center justify-between">
        <h3 className="font-serif text-[17px] font-medium">
          Order book <span className="text-ink-3">· live</span>
        </h3>
        <span className="flex items-center gap-[6px] font-mono text-[10.5px] uppercase tracking-[.06em] text-ink-3">
          Last {fmtCents(market.yes)}
          {/* last price indicator pulses with the live price */}
          <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-pos" />
        </span>
      </div>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <div>
          <div className="mb-2 font-mono text-[10.5px] uppercase tracking-[.07em] text-ink-3">
            Buy / sell <span className="font-semibold text-pos">YES</span>
          </div>
          <Ladder
            asks={book.asks}
            bids={book.bids}
            bestAsk={yesAsk}
            bestBid={yesBid}
          />
        </div>
        <div className="sm:border-l sm:border-line sm:pl-6">
          <div className="mb-2 font-mono text-[10.5px] uppercase tracking-[.07em] text-ink-3">
            Buy / sell <span className="font-semibold text-neg">NO</span>
          </div>
          <Ladder
            asks={book.no_asks}
            bids={book.no_bids}
            bestAsk={noAsk}
            bestBid={noBid}
          />
        </div>
      </div>
    </div>
  );
}