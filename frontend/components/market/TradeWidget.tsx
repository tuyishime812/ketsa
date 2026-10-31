'use client';

import { useMemo, useState } from 'react';
import { placeTradeSession } from '@/lib/api';
import { useWallet } from '@/components/wallet/WalletProvider';
import { useBetSlip } from '@/components/betslip/BetSlipProvider';
import type {
  Market,
  OrderBook,
  Outcome,
  Side,
  TradeResponse,
} from '@/lib/types';
import { fmtBalance, fmtCents, fmtShares, fmtUsd, fmtUsdFull } from '@/lib/utils';

export interface EstimateSummary {
  avg: number;
  count: number;
  total: number;
}

/** Walk levels in best-first order to fill a buy budget (amount in wallet currency). */
function buySummary(
  levels: { price: number; size: number }[],
  budget: number,
): EstimateSummary {
  let remaining = budget;
  let count = 0;
  let cost = 0;
  for (const l of levels) {
    if (remaining <= 0) break;
    const levelCost = (l.size * l.price) / 100;
    if (levelCost <= remaining) {
      count += l.size;
      cost += levelCost;
      remaining -= levelCost;
    } else {
      const q = remaining / (l.price / 100);
      count += q;
      cost += remaining;
      remaining = 0;
    }
  }
  return {
    avg: cost / Math.max(count, 0.0001) / 100,
    count,
    total: cost,
  };
}

/** Walk levels in best-first order to fill a number of shares being sold. */
function sellSummary(
  levels: { price: number; size: number }[],
  shares: number,
): EstimateSummary {
  let remaining = shares;
  let proceeds = 0;
  for (const l of levels) {
    if (remaining <= 0) break;
    const q = Math.min(remaining, l.size);
    proceeds += (q * l.price) / 100;
    remaining -= q;
  }
  return {
    avg: proceeds / Math.max(shares, 0.0001) / 100,
    count: shares,
    total: proceeds,
  };
}

export default function TradeWidget({
  market,
  book,
  onTraded,
}: {
  market: Market;
  book: OrderBook;
  onTraded: (resp: TradeResponse) => void;
}) {
  const { wallet, openConnect } = useWallet();
  const { addLeg, setIsOpen } = useBetSlip();
  const [outcome, setOutcome] = useState<Outcome>(
    market.yes >= 50 ? 'yes' : 'no',
  );
  const [side, setSide] = useState<Side>('buy');
  const [amount, setAmount] = useState('100');
  const [shares, setShares] = useState('100');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const estimate = useMemo<EstimateSummary | null>(() => {
    const levels =
      outcome === 'yes'
        ? side === 'buy'
          ? book.asks
          : book.bids
        : side === 'buy'
          ? book.no_asks
          : book.no_bids;
    if (levels.length === 0) return null;
    const val = side === 'buy' ? parseFloat(amount) : parseFloat(shares);
    if (!Number.isFinite(val) || val <= 0) return null;
    return side === 'buy' ? buySummary(levels, val) : sellSummary(levels, val);
  }, [side, outcome, amount, shares, book]);

  const canAfford =
    wallet === null ||
    wallet === undefined ||
    wallet.balance >= (estimate?.total ?? 0);

  if (market.status === 'resolved') {
    const winner = market.resolved_outcome ?? (market.yes > market.no ? 'yes' : 'no');
    const winPrice = market.resolved_price ?? (winner === 'yes' ? market.yes : market.no);
    return (
      <div className="rounded-m border border-line bg-white p-6 text-center">
        <div className="font-mono text-[10px] uppercase tracking-[.07em] text-ink-3">
          Market resolved
        </div>
        <div className="mt-3 font-serif text-[24px] font-medium">
          <span className={winner === 'yes' ? 'text-pos' : 'text-neg'}>
            {winner.toUpperCase()}
          </span>{' '}
          won
        </div>
        <p className="mx-auto mt-2 max-w-[260px] text-[13px] text-ink-2">
          Settled at {fmtCents(winPrice)} per share. Holding positions were
          paid out or expired automatically — trading is closed.
        </p>
        <div className="mt-5 grid grid-cols-2 gap-3">
          <div className="rounded-[7px] border border-line bg-paper-alt px-3 py-3">
            <div className="font-mono text-[10px] uppercase tracking-[.06em] text-ink-3">
              YES
            </div>
            <div className="mt-[2px] font-mono text-[17px] font-semibold text-ink">
              {market.yes}¢
            </div>
          </div>
          <div className="rounded-[7px] border border-line bg-paper-alt px-3 py-3">
            <div className="font-mono text-[10px] uppercase tracking-[.06em] text-ink-3">
              NO
            </div>
            <div className="mt-[2px] font-mono text-[17px] font-semibold text-ink">
              {market.no}¢
            </div>
          </div>
        </div>
      </div>
    );
  }

  async function submit() {
    if (!wallet || !estimate) return;
    setError(null);
    setFlash(null);
    setBusy(true);
    try {
      const resp = await placeTradeSession({
        wallet_id: wallet.id,
        market_id: market.id,
        outcome,
        side,
        amount: side === 'buy' ? parseFloat(amount) : undefined,
        shares: side === 'sell' ? parseFloat(shares) : undefined,
      });
      setFlash(
        side === 'buy'
          ? `Bought ${fmtShares(estimate.count).toUpperCase()} shares`
          : `Sold ${fmtShares(estimate.count).toUpperCase()} shares`,
      );
      onTraded(resp);
      if (side === 'sell') setShares('100');
    } catch (e) {
      setError(
        e instanceof Error ? e.message : 'Trade failed — please try again.',
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-m border border-line bg-white p-5">
      <h3 className="mb-4 font-serif text-[17px] font-medium">
        Trade <span className="text-ink-3">· play money</span>
      </h3>

      <div className="segment mb-4">
        <button
          className={`segment-btn ${outcome === 'yes' ? 'segment-btn--yes is-active' : ''}`}
          onClick={() => setOutcome('yes')}
        >
          YES <span className="font-mono">{market.yes}¢</span>
        </button>
        <button
          className={`segment-btn ${outcome === 'no' ? 'segment-btn--no is-active' : ''}`}
          onClick={() => setOutcome('no')}
        >
          NO <span className="font-mono">{market.no}¢</span>
        </button>
      </div>

      <div className="mb-4 flex items-center gap-2">
        <button
          className={`trade-side ${side === 'buy' ? 'is-buy is-active' : ''}`}
          onClick={() => setSide('buy')}
        >
          Buy
        </button>
        <button
          className={`trade-side ${side === 'sell' ? 'is-sell is-active' : ''}`}
          onClick={() => setSide('sell')}
        >
          Sell
        </button>
      </div>

      <label className="mb-4 block">
        <span className="mb-2 block font-mono text-[10.5px] uppercase tracking-[.07em] text-ink-3">
          {side === 'buy' ? `Amount (${wallet?.currency ?? 'MWK'} · balance ${fmtBalance(wallet?.balance ?? 0, wallet?.currency)})` : 'Shares to sell'}
        </span>
        <div className="flex items-center gap-2">
          <input
            className="field w-full"
            type="number"
            inputMode="decimal"
            min="1"
            step="1"
            value={side === 'buy' ? amount : shares}
            onChange={(e) =>
              (side === 'buy' ? setAmount : setShares)(e.target.value)
            }
          />
          <span className="font-mono text-sm text-ink-3">
            {side === 'buy' ? (wallet?.currency ?? 'MWK') : 'shares'}
          </span>
        </div>
      </label>

      <div className="mb-4 rounded-[7px] border border-line bg-paper-alt px-[13px] py-[11px]">
        {estimate === null ? (
          <div className="text-[12.5px] text-ink-3">
            Enter an amount above to preview your fill.
          </div>
        ) : (
          <div className="flex flex-wrap gap-x-8 gap-y-[6px] font-mono text-[12.5px]">
            <div>
              <div className="text-[10px] uppercase tracking-[.06em] text-ink-3">
                Est. avg price
              </div>
              <div className="mt-[2px] font-semibold text-ink">
                {fmtUsdFull(estimate.avg)} ({fmtCents(Math.round(estimate.avg * 100))})
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-[.06em] text-ink-3">
                {side === 'buy' ? 'Shares received' : 'Proceeds'}
              </div>
              <div className="mt-[2px] font-semibold text-ink">
                {side === 'buy'
                  ? fmtShares(estimate.count)
                  : fmtUsdFull(estimate.total)}
              </div>
            </div>
          </div>
        )}
        {flash && (
          <div className="mt-[8px] border-t border-line pt-[8px] font-mono text-[12px] font-semibold text-pos">
            {flash} — your wallet has been updated.
          </div>
        )}
        {error && (
          <div className="mt-[8px] border-t border-line pt-[8px] text-[12px] font-semibold text-neg">
            {error}
          </div>
        )}
      </div>

      {!wallet ? (
        <button className="btn btn--brand w-full" onClick={openConnect}>
          Connect wallet to trade
        </button>
      ) : (
        <div className="flex flex-col gap-2">
          <button
            className="btn btn--brand w-full"
            disabled={
              busy ||
              estimate === null ||
              estimate.count <= 0 ||
              !canAfford
            }
            onClick={() => void submit()}
          >
            {busy
              ? 'Placing order…'
              : !canAfford
                ? 'Insufficient balance'
                : `${side === 'buy' ? 'Buy' : 'Sell'} ${outcome.toUpperCase()} for ${fmtUsd(
                    estimate?.total ?? 0,
                  )}`}
          </button>
          <button
            className="w-full rounded-[8px] border border-line py-[10px] text-center font-mono text-[11px] uppercase tracking-[.08em] text-ink hover:bg-paper-alt"
            disabled={estimate === null || estimate.count <= 0}
            onClick={() => {
              if (estimate === null || estimate.count <= 0) return;
              addLeg({
                market_id: market.id,
                market,
                outcome,
                side,
                amount: side === 'buy' ? parseFloat(amount) || 100 : undefined,
                shares: side === 'sell' ? parseFloat(shares) || 100 : undefined,
              });
              setFlash('Added to bet slip');
              setTimeout(() => setFlash(null), 2000);
              setIsOpen(true);
            }}
          >
            Add to bet slip / Multi bet
          </button>
        </div>
      )}
      <p className="mt-[10px] text-center font-mono text-[10px] uppercase tracking-[.06em] text-ink-3">
        Simulated wallet · no real funds
      </p>
    </div>
  );
}
