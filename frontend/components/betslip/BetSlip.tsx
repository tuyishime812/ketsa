'use client';

import { useMemo, useState } from 'react';
import { useBetSlip } from './BetSlipProvider';
import { useWallet } from '@/components/wallet/WalletProvider';
import { placeMultiTradeSession } from '@/lib/api';
import { fmtCents, fmtShares, fmtUsd } from '@/lib/utils';
import type { OrderBook, TradeResponse } from '@/lib/types';

function estimateBuy(levels: { price: number; size: number }[] | undefined, budget: number) {
  if (!levels || levels.length === 0 || !Number.isFinite(budget) || budget <= 0) return null;
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
  if (count <= 0) return null;
  return { avg: cost / count / 100, count, cost };
}

export default function BetSlip() {
  const { legs, removeLeg, updateLeg, clearSlip, isOpen, setIsOpen, count } = useBetSlip();
  const { wallet, openConnect, refreshWallet } = useWallet();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const sharedStake = legs[0]?.amount;
  const totalStake = legs.reduce((sum, leg) => {
    const amt = typeof leg.amount === 'number' ? leg.amount : 0;
    return sum + amt;
  }, 0);

  const perLegEstimates = useMemo(() => {
    return legs.map((leg) => {
      if (!leg.market) return null;
       const book = (leg.market as { book?: OrderBook }).book;
      if (!book) return null;
      const levels =
        leg.outcome === 'yes'
          ? leg.side === 'buy'
            ? book.asks
            : book.bids
          : leg.side === 'buy'
            ? book.no_asks
            : book.no_bids;
      if (leg.side === 'buy') {
        return estimateBuy(levels, leg.amount || 0);
      }
      return null;
    });
  }, [legs]);

  const totalPotential = useMemo(() => {
    let sum = 0;
    perLegEstimates.forEach((est, idx) => {
      if (est && legs[idx]?.side === 'buy') {
        sum += est.count; // 1.00 per share if win
      }
    });
    return sum;
  }, [perLegEstimates, legs]);

  const canPlace = wallet && legs.length > 0 && !busy && totalStake >= 0.01;

  async function placeSlip() {
    if (!wallet) {
      openConnect();
      return;
    }
    if (legs.length === 0) return;
    setError(null);
    setSuccess(null);
    setBusy(true);
    try {
      const resp: TradeResponse = await placeMultiTradeSession({
        wallet_id: wallet.id,
        legs: legs.map((leg) => ({
          market_id: leg.market_id,
          outcome: leg.outcome,
          side: leg.side,
          amount: leg.amount,
          shares: leg.shares,
        })),
        slip: legs.map((leg) => ({
          market_id: leg.market_id,
          outcome: leg.outcome,
          side: leg.side,
          amount: leg.amount,
          shares: leg.shares,
        })),
      });
      await refreshWallet().catch(() => {});
      const filled = resp.trades?.length ?? resp.results?.length ?? legs.length;
      setSuccess(`Placed ${filled} bet${filled === 1 ? '' : 's'} on one slip`);
      clearSlip();
      setTimeout(() => setSuccess(null), 4000);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to place multi-bet');
    } finally {
      setBusy(false);
    }
  }

  if (!isOpen && count === 0) return null;

  return (
    <>
      {/* Floating button */}
      {!isOpen && count > 0 && (
        <button
          onClick={() => setIsOpen(true)}
          className="fixed bottom-5 right-5 z-50 flex items-center gap-2 rounded-full bg-brand px-5 py-2.5 font-mono text-[12px] font-semibold uppercase tracking-[.08em] text-white shadow-lg hover:bg-brand/90"
        >
          Bet Slip ({count})
        </button>
      )}

      {/* Slip panel */}
      {isOpen && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div className="absolute inset-0 bg-black/30" onClick={() => setIsOpen(false)} />
          <div className="relative h-full w-full max-w-[380px] md:max-w-[380px] max-[640px]:max-w-full bg-white shadow-2xl flex flex-col">
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <div>
                <div className="font-serif text-[18px] font-medium">Bet Slip</div>
                <div className="font-mono text-[11px] uppercase tracking-[.06em] text-ink-3">
                  {count} {count === 1 ? 'selection' : 'selections'} · Multi-bet
                </div>
              </div>
              <button
                onClick={() => setIsOpen(false)}
                className="rounded-[6px] px-2 py-1 text-ink-3 hover:bg-paper-alt hover:text-ink"
              >
                ✕
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
              {legs.length === 0 ? (
                <div className="py-10 text-center text-[13px] text-ink-3">
                  No selections yet. Add bets from markets to build your slip.
                </div>
              ) : (
                legs.map((leg, idx) => {
                  const est = perLegEstimates[idx];
                  return (
                    <div key={`${leg.market_id}-${leg.outcome}-${idx}`} className="rounded-[8px] border border-line p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="text-[13px] font-medium leading-snug line-clamp-2">
                            {leg.market?.q || leg.market_id}
                          </div>
                          <div className="mt-1 flex items-center gap-2 font-mono text-[11px] uppercase tracking-[.06em]">
                            <span className={leg.outcome === 'yes' ? 'text-pos' : 'text-neg'}>
                              {leg.outcome.toUpperCase()}
                            </span>
                            <span className="text-ink-3">{leg.side}</span>
                            {leg.market && (
                              <span className="text-ink-3">
                                {leg.outcome === 'yes' ? fmtCents(leg.market.yes) : fmtCents(leg.market.no)}
                              </span>
                            )}
                          </div>
                        </div>
                        <button
                          onClick={() => removeLeg(idx)}
                          className="text-ink-3 hover:text-neg"
                        >
                          ✕
                        </button>
                      </div>
                      <div className="mt-2 font-mono text-[10.5px] text-ink-3">
                        Stake {fmtUsd(leg.amount ?? 0)}
                      </div>
                      {leg.side === 'buy' && est && (
                        <div className="mt-2 rounded-[6px] bg-paper-alt px-2 py-1.5 font-mono text-[10.5px] text-ink-2">
                          Est. {fmtShares(est.count)} shares @ {fmtUsd(est.avg)} avg
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>

            {legs.length > 0 && (
              <div className="border-t border-line px-5 py-4 space-y-3">
                <label className="block">
                  <span className="mb-1 block font-mono text-[10px] uppercase tracking-[.06em] text-ink-3">
                    Same stake for every selection ({wallet?.currency ?? 'MWK'})
                  </span>
                  <input
                    type="number"
                    inputMode="decimal"
                    min="0.01"
                    step="1"
                    className="field w-full"
                    value={sharedStake ?? ''}
                    onChange={(e) => {
                      const val = e.target.value === '' ? undefined : parseFloat(e.target.value);
                      const amount = Number.isFinite(val as number) ? (val as number) : undefined;
                      legs.forEach((_, index) => updateLeg(index, { amount }));
                    }}
                    placeholder="100"
                  />
                </label>
                <div className="space-y-1">
                  <div className="flex items-center justify-between font-mono text-[12px]">
                    <span className="text-ink-3 uppercase tracking-[.06em]">Total stake</span>
                    <span className="font-semibold">{fmtUsd(totalStake)}</span>
                  </div>
                  {totalPotential > 0 && (
                    <div className="flex items-center justify-between font-mono text-[11px]">
                      <span className="text-ink-3 uppercase tracking-[.06em]">Potential payout (all win)</span>
                      <span className="text-pos">{fmtUsd(totalPotential)}</span>
                    </div>
                  )}
                </div>
                {error && <div className="text-[12px] text-neg">{error}</div>}
                {success && <div className="text-[12px] text-pos">{success}</div>}
                {!wallet ? (
                  <button onClick={openConnect} className="btn btn--brand w-full">
                    Connect wallet to place multi-bet
                  </button>
                ) : (
                  <button
                    onClick={() => void placeSlip()}
                    disabled={!canPlace}
                    className="btn btn--brand w-full disabled:opacity-50"
                  >
                    {busy ? 'Placing...' : `Place ${count} bet${count === 1 ? '' : 's'} on slip`}
                  </button>
                )}
                <button
                  onClick={clearSlip}
                  className="w-full text-center font-mono text-[11px] uppercase tracking-[.06em] text-ink-3 hover:text-ink"
                >
                  Clear slip
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
