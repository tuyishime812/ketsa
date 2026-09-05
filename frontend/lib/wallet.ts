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