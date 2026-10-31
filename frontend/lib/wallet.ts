// Simulated-wallet session persistence. The wallet identity (id + display
// name) lives in localStorage; the actual balance/positions are held by the
// backend keyed by wallet id.

export interface StoredWallet {
  id: string;
  name: string;
}

const KEY = 'ketsa:wallet';

export function loadStoredWallet(): StoredWallet | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredWallet>;
    if (typeof parsed.id === 'string' && parsed.id) {
      return { id: parsed.id, name: parsed.name || 'Trader' };
    }
    return null;
  } catch {
    return null;
  }
}

export function storeWallet(w: StoredWallet): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(w));
  } catch {
    /* storage unavailable (private mode) — session-only wallet */
  }
}

export function clearStoredWallet(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

// --- Auth session persistence ----------------------------------------------
// An authenticated session is a bearer token + the owning user. The wallet
// identity is still stored under `ketsa:wallet` so the rest of the app is
// oblivious to whether the wallet is guest-created or account-owned.

export interface StoredSession {
  token: string;
  userId: string;
  email: string;
  name: string;
}

const SESSION_KEY = 'ketsa:session';

export function loadStoredSession(): StoredSession | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredSession>;
    if (typeof parsed.token === 'string' && parsed.token && parsed.userId) {
      return parsed as StoredSession;
    }
    return null;
  } catch {
    return null;
  }
}

export function storeSession(s: StoredSession): void {
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify(s));
  } catch {
    /* storage unavailable */
  }
}

export function clearStoredSession(): void {
  try {
    localStorage.removeItem(SESSION_KEY);
  } catch {
    /* ignore */
  }
}
