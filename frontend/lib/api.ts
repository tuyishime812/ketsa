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
