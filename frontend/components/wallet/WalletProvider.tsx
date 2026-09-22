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
import {
  connectWalletSession,
  fetchAuthMe,
  fetchWalletSession,
  loginSession,
  logoutSession,
  registerSession,
  startSocialLogin,
} from '@/lib/api';
import type { User, Wallet } from '@/lib/types';
import {
  clearStoredSession,
  clearStoredWallet,
  loadStoredSession,
  loadStoredWallet,
  storeSession,
  storeWallet,
} from '@/lib/wallet';
import ConnectWalletModal from './ConnectWalletModal';
import AuthModal from '@/components/auth/AuthModal';

type AuthMode = 'login' | 'register';

interface WalletContextValue {
  wallet: Wallet | null;
  user: User | null;
  loading: boolean;
  /** Create or re-attach the simulated/guest wallet. */
  connect: (name?: string) => Promise<Wallet>;
  disconnect: () => void;
  refreshWallet: () => Promise<void>;
  openConnect: () => void;
  // Auth
  openAuth: (mode?: AuthMode) => void;
  closeAuth: () => void;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  /** Start Auth0 "Continue with Google"; the browser leaves for Auth0. */
  googleLogin: () => Promise<void>;
  logout: () => Promise<void>;
  /** Persist a refreshed token + user + wallet (e.g. after a password change). */
  applySession: (session: { token: string; user: User; wallet: Wallet }) => void;
}

const WalletContext = createContext<WalletContextValue | null>(null);

export function WalletProvider({ children }: { children: ReactNode }) {
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);
  const [authMode, setAuthMode] = useState<AuthMode>('login');
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
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

  // Restore an authenticated session first; fall back to the guest wallet.
  useEffect(() => {
    if (restoring.current) return;
    restoring.current = true;
    (async () => {
      const session = loadStoredSession();
      if (session?.token) {
        try {
          const me = await fetchAuthMe(session.token);
          setUser(me.user);
          setWallet(me.wallet);
          storeSession({
            token: me.token || session.token,
            userId: me.user.id,
            email: me.user.email,
            name: me.user.name,
          });
          storeWallet({ id: me.wallet.id, name: me.wallet.name });
          return;
        } catch {
          clearStoredSession();
          // Fall through to guest wallet restore.
        }
      }
      await refresh();
    })().finally(() => setLoading(false));
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

  const openAuth = useCallback((mode: AuthMode = 'login') => {
    setAuthMode(mode);
    setAuthError(null);
    setAuthOpen(true);
  }, []);

  const closeAuth = useCallback(() => {
    if (authBusy) return;
    setAuthOpen(false);
    setAuthError(null);
  }, [authBusy]);

  const finishAuth = useCallback((session: { token: string; user: User; wallet: Wallet }) => {
    setUser(session.user);
    setWallet(session.wallet);
    storeSession({
      token: session.token || loadStoredSession()?.token || '',
      userId: session.user.id,
      email: session.user.email,
      name: session.user.name,
    });
    storeWallet({ id: session.wallet.id, name: session.wallet.name });
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      setAuthBusy(true);
      setAuthError(null);
      try {
        const session = await loginSession({ email, password });
        finishAuth(session);
        setAuthOpen(false);
      } catch (err) {
        setAuthError(err instanceof Error ? err.message : 'Login failed');
      } finally {
        setAuthBusy(false);
      }
    },
    [finishAuth],
  );

  const register = useCallback(
    async (name: string, email: string, password: string) => {
      setAuthBusy(true);
      setAuthError(null);
      try {
        const session = await registerSession({ name, email, password });
        finishAuth(session);
        setAuthOpen(false);
      } catch (err) {
        setAuthError(err instanceof Error ? err.message : 'Registration failed');
      } finally {
        setAuthBusy(false);
      }
    },
    [finishAuth],
  );

  const googleLogin = useCallback(async () => {
    setAuthBusy(true);
    setAuthError(null);
    try {
      const { url } = await startSocialLogin();
      // Full-page navigation: Auth0 -> backend callback -> /auth/callback.
      // The auth modal stays mounted until the browser leaves.
      window.location.assign(url);
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : 'Google login unavailable');
      setAuthBusy(false);
    }
  }, []);

  const logout = useCallback(async () => {
    const session = loadStoredSession();
    if (session?.token) {
      try {
        await logoutSession(session.token);
      } catch {
        /* best-effort server-side revoke */
      }
    }
    clearStoredSession();
    clearStoredWallet();
    setUser(null);
    setWallet(null);
  }, []);

  return (
    <WalletContext.Provider
      value={{
        wallet,
        user,
        loading,
        connect,
        disconnect,
        refreshWallet,
        openConnect,
        openAuth,
        closeAuth,
        login,
        register,
        googleLogin,
        logout,
        applySession: finishAuth,
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
      {authOpen && (
        <AuthModal
          initialMode={authMode}
          busy={authBusy}
          error={authError}
          onLogin={(email, password) => {
            void login(email, password);
          }}
          onRegister={(name, email, password) => {
            void register(name, email, password);
          }}
          onGoogle={() => {
            void googleLogin();
          }}
          onClose={closeAuth}
          onGuest={() => {
            setAuthOpen(false);
            setModalOpen(true);
          }}
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