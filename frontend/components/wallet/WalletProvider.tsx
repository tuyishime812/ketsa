'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { connectWalletSession, fetchWalletSession } from '@/lib/api';
import type { Wallet } from '@/lib/types';
import {
  clearStoredWallet,
  loadStoredWallet,
  storeWallet,
} from '@/lib/wallet';
import ConnectWalletModal from './ConnectWalletModal';

interface WalletContextValue {
  wallet: Wallet | null;
  loading: boolean;
  /** Create or re-attach the simulated wallet. */
  connect: (name?: string) => Promise<Wallet>;
  disconnect: () => void;
  refreshWallet: () => Promise<void>;
  openConnect: () => void;
}

const WalletContext = createContext<WalletContextValue | null>(null);

export function WalletProvider({ children }: { children: ReactNode }) {
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const restoring = useRef(false);

  const refresh = useCallback(async (): Promise<Wallet | null> => {
    const stored = loadStoredWallet();
    if (!stored) {
      setWallet(null);
      return null;
    }
    try {
      const w = await fetchWalletSession(stored.id);
      setWallet(w);
      return w;
    } catch {
      try {
        // Wallet gone (backend restarted) — recreate with the same identity.
        const w = await connectWalletSession(stored.name, stored.id);
        setWallet(w);
        storeWallet({ id: w.id, name: w.name });
        return w;
      } catch {
        setWallet(null);
        return null;
      }
    }
  }, []);

  useEffect(() => {
    if (restoring.current) return;
    restoring.current = true;
    refresh().finally(() => setLoading(false));
  }, [refresh]);

  const connect = useCallback(async (name?: string) => {
    setConnecting(true);
    try {
      const stored = loadStoredWallet();
      const w = await connectWalletSession(
        name || stored?.name || 'Trader',
        stored?.id,
      );
      storeWallet({ id: w.id, name: w.name });
      setWallet(w);
      setModalOpen(false);
      return w;
    } finally {
      setConnecting(false);
    }
  }, []);

  const disconnect = useCallback(() => {
    clearStoredWallet();
    setWallet(null);
  }, []);

  const refreshWallet = useCallback(async () => {
    await refresh();
  }, [refresh]);

  const openConnect = useCallback(() => setModalOpen(true), []);

  return (
    <WalletContext.Provider
      value={{
        wallet,
        loading,
        connect,
        disconnect,
        refreshWallet,
        openConnect,
      }}
    >
      {children}
      {modalOpen && (
        <ConnectWalletModal
          busy={connecting}
          onConnect={(name) => {
            void connect(name);
          }}
          onClose={() => setModalOpen(false)}
        />
      )}
    </WalletContext.Provider>
  );
}

export function useWallet(): WalletContextValue {
  const ctx = useContext(WalletContext);
  if (!ctx) {
    throw new Error('useWallet must be used within a <WalletProvider>');
  }
  return ctx;
}