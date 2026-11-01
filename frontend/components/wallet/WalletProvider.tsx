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
  forgotPassword as forgotPasswordRequest,
  loginSession,
  logoutSession,
  registerSession,
  requestLoginCode as requestLoginCodeRequest,
  resetPassword as resetPasswordRequest,
  startSocialLogin,
  verifyLoginCode as verifyLoginCodeRequest,
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
  login: (identifier: string, password: string) => Promise<void>;
  /**
   * Email a one-time sign-in code (passwordless). Resolves true when the
   * backend accepted the request. The reply is deliberately uniform for every
   * identifier, so `true` does NOT confirm the address has an account.
   */
  requestLoginCode: (identifier: string) => Promise<boolean>;
  /** Complete a passwordless sign-in with the emailed code. */
  loginWithCode: (email: string, otp: string) => Promise<void>;
  /**
   * Register. Email and phone signups both complete immediately: the session
   * (and wallet) is live as soon as this resolves.
   */
  register: (name: string, identifier: string, password: string) => Promise<void>;
  /** Request a password-reset code; always succeeds (uniform 200). */
  forgotPassword: (identifier: string) => Promise<boolean>;
  /** Set a new password with the emailed code; true on success. */
  resetPassword: (
    email: string,
    otp: string,
    newPassword: string,
  ) => Promise<boolean>;
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

  // Safety net for `loading`.
  //
  // While it is true, AuthCta/CtaBand render non-interactive <span aria-hidden>
  // stand-ins instead of buttons — the CTAs look right but do nothing. The
  // effect above only clears it once the restore fetches settle, and the fetch
  // layer issues no AbortSignal/timeout of its own, so a hung or very slow
  // request would leave the primary "Log in" / "Create account" buttons inert
  // indefinitely. Cap it so the CTAs always become clickable; the normal path
  // still wins because it clears the flag first, and clearing twice is a no-op.
  useEffect(() => {
    const failsafe = setTimeout(() => setLoading(false), 8000);
    return () => clearTimeout(failsafe);
  }, []);

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
    async (identifier: string, password: string) => {
      setAuthBusy(true);
      setAuthError(null);
      try {
        const session = await loginSession({ identifier, password });
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

  const requestLoginCode = useCallback(async (identifier: string) => {
    setAuthBusy(true);
    setAuthError(null);
    try {
      await requestLoginCodeRequest(identifier);
      return true;
    } catch (err) {
      setAuthError(
        err instanceof Error ? err.message : 'Could not send the sign-in code',
      );
      return false;
    } finally {
      setAuthBusy(false);
    }
  }, []);

  const loginWithCode = useCallback(
    async (email: string, otp: string) => {
      setAuthBusy(true);
      setAuthError(null);
      try {
        const session = await verifyLoginCodeRequest(email, otp);
        finishAuth(session);
        setAuthOpen(false);
      } catch (err) {
        setAuthError(
          err instanceof Error ? err.message : 'That code was not accepted',
        );
      } finally {
        setAuthBusy(false);
      }
    },
    [finishAuth],
  );

  const register = useCallback(
    async (name: string, identifier: string, password: string): Promise<void> => {
      setAuthBusy(true);
      setAuthError(null);
      try {
        const session = await registerSession({ name, identifier, password });
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

  const forgotPassword = useCallback(async (identifier: string) => {
    setAuthBusy(true);
    setAuthError(null);
    try {
      await forgotPasswordRequest(identifier);
      return true;
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : 'Reset request failed');
      return false;
    } finally {
      setAuthBusy(false);
    }
  }, []);

  const resetPassword = useCallback(async (
    email: string,
    otp: string,
    newPassword: string,
  ) => {
    setAuthBusy(true);
    setAuthError(null);
    try {
      await resetPasswordRequest(email, otp, newPassword);
      return true;
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : 'Reset failed');
      return false;
    } finally {
      setAuthBusy(false);
    }
  }, []);

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
        requestLoginCode,
        loginWithCode,
        register,
        forgotPassword,
        resetPassword,
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
          onLogin={(identifier, password) => {
            void login(identifier, password);
          }}
          onRequestLoginCode={(identifier) => requestLoginCode(identifier)}
          onLoginWithCode={(email, otp) => loginWithCode(email, otp)}
          onRegister={(name, identifier, password) =>
            register(name, identifier, password)
          }
          onForgot={(identifier) => forgotPassword(identifier)}
          onReset={(email, otp, newPassword) =>
            resetPassword(email, otp, newPassword)
          }
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
