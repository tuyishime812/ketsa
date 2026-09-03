// Thin fetch wrapper for the Ketsa FastAPI backend.
//
// In development, `next.config.js` rewrites `/api/*` to the FastAPI server so
// the browser only ever talks to the same origin (avoids CORS in the browser
// and keeps the API URL out of client bundles). At build time we read the
// data server-side via `fetchHomeData()`.

import type { HomeData, Market, WatchItem } from './types';

const API_BASE = process.env.KETSA_BACKEND_URL || 'http://127.0.0.1:8000';

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    // Never allow credentials on these public GET endpoints.
    credentials: 'omit',
    headers: {
      Accept: 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    throw new Error(`API request failed (${res.status}): ${path}`);
  }
  return (await res.json()) as T;
}

/** Fetch the full home bundle from the backend (server-side helper). */
export async function fetchHomeData(): Promise<HomeData> {
  return fetchJson<HomeData>(`${API_BASE}/api/home`);
}

export async function fetchWatch(): Promise<WatchItem[]> {
  return fetchJson<WatchItem[]>(`${API_BASE}/api/watch`);
}

export async function fetchMarket(id: string): Promise<Market> {
  return fetchJson<Market>(`${API_BASE}/api/markets/${encodeURIComponent(id)}`);
}

/**
 * Admin API helpers.
 *
 * These talk to the same-origin `/api/*` proxy at runtime (see next.config.js),
 * which forwards to FastAPI. All authenticated calls send the bearer token
 * returned by `adminLogin`. Tokens are stored in localStorage by the UI.
 */

export interface AdminLoginResult {
  token: string;
}

/** Path used client-side. Public read helper below uses API_BASE directly. */
const ADMIN_BASE = '/api/admin';

export async function adminLogin(password: string): Promise<string> {
  const res = await fetch(`${ADMIN_BASE}/login`, {
    method: 'POST',
    credentials: 'omit',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) {
    // Surface the server's reason detail (e.g. invalid password).
    let detail = 'Login failed';
    try {
      const body = await res.json();
      detail = body?.detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  const data = (await res.json()) as AdminLoginResult;
  return data.token;
}

export class AdminApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function adminFetch<T>(
  token: string,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${ADMIN_BASE}${path}`, {
    ...init,
    credentials: 'omit',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(init?.headers ?? {}),
    },
  });
  if (res.status === 401) {
    throw new AdminApiError(401, 'Unauthorized — please log in again');
  }
  if (!res.ok) {
    throw new AdminApiError(res.status, `Request failed (${res.status}): ${path}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function adminGet<T>(token: string, path: string): Promise<T> {
  return adminFetch<T>(token, path);
}

export function adminPost<T>(token: string, path: string, body: unknown): Promise<T> {
  return adminFetch<T>(token, path, { method: 'POST', body: JSON.stringify(body) });
}

export function adminPut<T>(token: string, path: string, body: unknown): Promise<T> {
  return adminFetch<T>(token, path, { method: 'PUT', body: JSON.stringify(body) });
}

export function adminDelete<T>(token: string, path: string): Promise<T> {
  return adminFetch<T>(token, path, { method: 'DELETE' });
}

