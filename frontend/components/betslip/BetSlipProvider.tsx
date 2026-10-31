'use client';

import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import type { Outcome, Side, Market } from '@/lib/types';

export interface SlipLeg {
  market_id: string;
  market?: Market;
  outcome: Outcome;
  side: Side;
  amount?: number;
  shares?: number;
  addedAt: number;
}

interface BetSlipContextValue {
  legs: SlipLeg[];
  addLeg: (leg: Omit<SlipLeg, 'addedAt'>) => void;
  removeLeg: (index: number) => void;
  updateLeg: (index: number, patch: Partial<SlipLeg>) => void;
  clearSlip: () => void;
  count: number;
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
  toggle: () => void;
}

const BetSlipContext = createContext<BetSlipContextValue | undefined>(undefined);

const STORAGE_KEY_BASE = 'ketsa_betslip_v1';

export function BetSlipProvider({ children }: { children: React.ReactNode }) {
  const [legs, setLegs] = useState<SlipLeg[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [walletKey, setWalletKey] = useState<string>('guest');

  // Try to detect wallet from localStorage/session
  useEffect(() => {
    try {
      const raw = localStorage.getItem('ketsa_wallet_v1') || localStorage.getItem('ketsa_session_v1');
      if (raw) {
        const parsed = JSON.parse(raw);
        const wid = parsed?.wallet?.id || parsed?.id || parsed?.wallet_id;
        if (wid) setWalletKey(wid);
      }
    } catch {
      /* ignore */
    }
  }, []);

  const storageKey = `${STORAGE_KEY_BASE}_${walletKey}`;

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) setLegs(parsed);
      } else {
        setLegs([]);
      }
    } catch {
      /* ignore */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(legs));
    } catch {
      /* ignore */
    }
  }, [legs, storageKey]);

  const value = useMemo<BetSlipContextValue>(
    () => ({
      legs,
      addLeg: (leg) => {
        setLegs((prev) => {
          // Avoid exact duplicates
          const exists = prev.find(
            (p) =>
              p.market_id === leg.market_id &&
              p.outcome === leg.outcome &&
              p.side === leg.side,
          );
          if (exists) return prev;
          return [...prev, { ...leg, addedAt: Date.now() }];
        });
        setIsOpen(true);
      },
      removeLeg: (index) => {
        setLegs((prev) => prev.filter((_, i) => i !== index));
      },
      updateLeg: (index, patch) => {
        setLegs((prev) =>
          prev.map((leg, i) => (i === index ? { ...leg, ...patch } : leg)),
        );
      },
      clearSlip: () => setLegs([]),
      count: legs.length,
      isOpen,
      setIsOpen,
      toggle: () => setIsOpen((o) => !o),
    }),
    [legs, isOpen],
  );

  return <BetSlipContext.Provider value={value}>{children}</BetSlipContext.Provider>;
}

export function useBetSlip() {
  const ctx = useContext(BetSlipContext);
  if (!ctx) throw new Error('useBetSlip must be used within BetSlipProvider');
  return ctx;
}
