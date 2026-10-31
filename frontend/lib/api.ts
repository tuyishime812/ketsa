// Thin fetch wrapper for the Ketsa API service.
//
// Browser-side calls go to the same-origin `/api/*`, served by the runtime
// proxy in `app/api/[...path]/route.ts`, so the browser only ever talks to the
// Next.js origin (avoids CORS in the browser and keeps the API URL out of
// client bundles). Server components read data server-side via `fetchHomeData()`.

import type {
  AdminConfig,
  AuthCredentials,
  AuthSession,
  Correspondent,
  HomeData,
  LeaderboardEntry,
  Market,
  NotificationItem,
  OrderBook,
  Payment,
  PendingVerification,
  RegisterCredentials,
  RegisterResult,
  StaffInviteResult,
  StaffMember,
  StaffPublic,
  StaffUploadResult,
  Trade,
  TradeRequest,
  TradeResponse,
  Wallet,
  WatchItem,
} from './types';
import { loadStoredSession } from './wallet';

const API_BASE = (process.env.KETSA_BACKEND_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');

/** A failed API call. `status` is 0 when the request never got a response. */
export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/**
 * True when a *read* may safely be attempted again.
 *
 * Only transport failures (status 0) and server/gateway errors are retryable.
 * Deliberately excludes 4xx: retrying a 401/404/422 can never help, and 429 is
 * a rate-limit signal, not a transient fault.
 */
export function isRetryableReadError(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    (err.status === 0 ||
      err.status === 500 ||
      err.status === 502 ||
      err.status === 503 ||
      err.status === 504)
  );
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      // Never allow credentials on these public GET endpoints.
      credentials: 'omit',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new ApiError(0, `Cannot reach the API: ${path}`);
  }
  if (!res.ok) {
    let detail = `API request failed (${res.status}): ${path}`;
    try {
      const body = await res.json();
      detail = body?.detail || detail;
    } catch {
      /* fall through to generic message */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

/**
 * GET helper with a small bounded retry, for idempotent reads only.
 *
 * The market data pages are server-rendered, so a single transient blip
 * between the Next server and the API (a dropped Supabase connection, a
 * restarting backend) used to blank the whole markets section with
 * "Temporarily unavailable". Reads are side-effect free, so retrying twice
 * costs at most ~0.8s and turns a transient 5xx into a rendered page.
 *
 * Never use this for POSTs: a retried trade/deposit could execute twice.
 */
async function fetchReadJson<T>(path: string, init?: RequestInit): Promise<T> {
  const delays = [200, 600];
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await fetchJson<T>(path, init);
    } catch (err) {
      if (attempt >= delays.length || !isRetryableReadError(err)) throw err;
      await new Promise((resolve) => setTimeout(resolve, delays[attempt]));
    }
  }
}

/** Attach the authenticated user's bearer token to a client request, if signed in. */
function sessionAuthHeaders(): Record<string, string> {
  const session = loadStoredSession();
  if (!session?.token) return {};
  return { Authorization: `Bearer ${session.token}` };
}

/** A same-origin `/api/*` client helper — proxied to the backend by Next. */
async function clientJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    credentials: 'omit',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...sessionAuthHeaders(),
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = `API request failed (${res.status}): ${path}`;
    try {
      const body = await res.json();
      detail = body?.detail || detail;
    } catch {
      /* fall through to generic message */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export interface MarketsGroup {
  all: Market[];
  by_category: Record<string, Market[]>;
}

/** Fetch the full home bundle from the backend (server-side helper). */
export async function fetchHomeData(): Promise<HomeData> {
  return fetchReadJson<HomeData>(`${API_BASE}/api/home`);
}

export async function fetchWatch(): Promise<WatchItem[]> {
  return fetchReadJson<WatchItem[]>(`${API_BASE}/api/watch`);
}

export async function fetchMarket(id: string): Promise<Market> {
  return fetchReadJson<Market>(`${API_BASE}/api/markets/${encodeURIComponent(id)}`);
}

export async function fetchMarketBook(id: string): Promise<OrderBook> {
  return fetchReadJson<OrderBook>(
    `${API_BASE}/api/markets/${encodeURIComponent(id)}/book`,
  );
}

export async function fetchMarketTrades(id: string, limit = 30): Promise<Trade[]> {
  return fetchReadJson<Trade[]>(
    `${API_BASE}/api/markets/${encodeURIComponent(id)}/trades?limit=${limit}`,
  );
}

/** All markets as a group (used by server-side listings). */
export async function fetchMarketsGroup(): Promise<MarketsGroup> {
  return fetchReadJson<MarketsGroup>(`${API_BASE}/api/markets`);
}

// ---------------------------------------------------------------------------
// Client-side (browser) helpers. These hit the same-origin `/api/*` proxy so
// no CORS configuration is required at runtime.
// ---------------------------------------------------------------------------

export async function fetchMarketsSession(): Promise<MarketsGroup> {
  return clientJson<MarketsGroup>('/markets');
}

export async function fetchWalletSession(id: string): Promise<Wallet> {
  return clientJson<Wallet>(`/wallet/${encodeURIComponent(id)}`);
}

export async function connectWalletSession(
  name: string,
  existingId?: string,
): Promise<Wallet> {
  return clientJson<Wallet>('/wallet', {
    method: 'POST',
    body: JSON.stringify({ id: existingId, name }),
  });
}

export async function placeTradeSession(req: TradeRequest): Promise<TradeResponse> {
  return clientJson<TradeResponse>('/trade', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export async function placeMultiTradeSession(req: TradeRequest): Promise<TradeResponse> {
  // Try dedicated multi endpoints first, fallback to flexible routes
  try {
    return await clientJson<TradeResponse>('/trade/multi', {
      method: 'POST',
      body: JSON.stringify(req),
    });
  } catch {
    try {
      return await clientJson<TradeResponse>('/bets', {
        method: 'POST',
        body: JSON.stringify(req),
      });
    } catch {
      try {
        return await clientJson<TradeResponse>('/slip', {
          method: 'POST',
          body: JSON.stringify(req),
        });
      } catch {
        return await clientJson<TradeResponse>('/trade', {
          method: 'POST',
          body: JSON.stringify(req),
        });
      }
    }
  }
}

export async function fetchBookSession(id: string): Promise<OrderBook> {
  return clientJson<OrderBook>(`/markets/${encodeURIComponent(id)}/book`);
}

export async function fetchTradesSession(id: string, limit = 30): Promise<Trade[]> {
  return clientJson<Trade[]>(
    `/markets/${encodeURIComponent(id)}/trades?limit=${limit}`,
  );
}

export async function createDepositSession(
  walletId: string,
  amount: number,
  number: string,
  correspondent: Correspondent,
): Promise<Payment> {
  return clientJson<Payment>('/payments/deposits', {
    method: 'POST',
    body: JSON.stringify({ wallet_id: walletId, amount, number, correspondent }),
  });
}

export async function createWithdrawalSession(
  walletId: string,
  amount: number,
  number: string,
  correspondent: Correspondent,
): Promise<Payment> {
  return clientJson<Payment>('/payments/withdrawals', {
    method: 'POST',
    body: JSON.stringify({ wallet_id: walletId, amount, number, correspondent }),
  });
}

export async function fetchPaymentsSession(walletId: string): Promise<Payment[]> {
  return clientJson<Payment[]>(
    `/payments?wallet_id=${encodeURIComponent(walletId)}`,
  );
}

/** Poll a payment; the backend credits deposits / refunds on polling. */
export async function refreshPaymentSession(id: string): Promise<Payment> {
  return clientJson<Payment>(`/payments/${encodeURIComponent(id)}`);
}

export async function fetchWallet(id: string): Promise<Wallet> {
  return fetchReadJson<Wallet>(`${API_BASE}/api/wallet/${encodeURIComponent(id)}`);
}

export async function connectWallet(
  name: string,
  existingId?: string,
): Promise<Wallet> {
  return fetchJson<Wallet>(`${API_BASE}/api/wallet`, {
    method: 'POST',
    body: JSON.stringify({ id: existingId, name }),
  });
}

export async function placeTrade(req: TradeRequest): Promise<TradeResponse> {
  return fetchJson<TradeResponse>(`${API_BASE}/api/trade`, {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

// ---------------------------------------------------------------------------
// User auth (register / login / session).
// These hit the same-origin `/api/*` proxy at runtime, like the client
// helpers above.
// ---------------------------------------------------------------------------

const AUTH_BASE = '/api/auth';

/** Shown when the browser could not reach the API at all (offline / proxy down). */
const AUTH_UNREACHABLE =
  'Cannot reach Ketsa right now. Check your connection and try again.';

/** Shown when a 2xx response body was not the JSON we expected. */
const AUTH_BAD_RESPONSE =
  'Ketsa returned an unexpected response. Please try again.';

/**
 * Turn a failed auth response into a message that is safe and useful to show.
 *
 * 4xx responses carry an actionable `detail` from the backend ("Incorrect
 * password", "That code has expired", …) so we surface it. Anything else — a
 * 5xx, or a body that is not JSON because a gateway/proxy answered instead of
 * the API — gets a calm generic line rather than a stack-trace-looking string.
 */
async function authErrorFrom(res: Response): Promise<string> {
  const fallback =
    res.status >= 500
      ? 'Ketsa is temporarily unavailable. Please try again shortly.'
      : `Request failed (${res.status})`;
  try {
    const body: unknown = await res.json();
    const detail = (body as { detail?: unknown } | null)?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
  } catch {
    /* non-JSON body (e.g. an upstream HTML error page passed through) */
  }
  return fallback;
}

/** Same-origin auth fetch that turns a transport failure into a message. */
async function authFetch(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${AUTH_BASE}${path}`, {
      ...init,
      credentials: 'omit',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    // fetch only rejects on transport failure, so this is never a 4xx/5xx.
    throw new Error(AUTH_UNREACHABLE);
  }
}

async function authRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await authFetch(path, init);
  if (!res.ok) {
    throw new Error(await authErrorFrom(res));
  }
  try {
    return (await res.json()) as T;
  } catch {
    throw new Error(AUTH_BAD_RESPONSE);
  }
}

/**
 * Register a user account.
 *
 * Email signups answer 202 with `{ok, pending, email}` — an emailed OTP must
 * be verified via `verifyEmail()` before the account exists (and a wallet is
 * minted). Phone signups answer 200 with a full session immediately.
 */
export async function registerSession(
  body: RegisterCredentials,
): Promise<RegisterResult> {
  const res = await authFetch('/register', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(await authErrorFrom(res));
  }
  try {
    return (await res.json()) as RegisterResult;
  } catch {
    throw new Error(AUTH_BAD_RESPONSE);
  }
}

/** Complete an email signup with the emailed one-time passcode. */
export function verifyEmail(email: string, otp: string): Promise<AuthSession> {
  return authRequest<AuthSession>('/register/verify', {
    method: 'POST',
    body: JSON.stringify({ email, otp }),
  });
}

/** Re-email the signup code for a pending registration (cooldown-gated). */
export function resendRegisterOtp(email: string): Promise<PendingVerification> {
  return authRequest<PendingVerification>('/register/resend', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });
}

/** Request a password-reset code for an email account (uniform 200 reply). */
export function forgotPassword(identifier: string): Promise<{ ok: boolean }> {
  return authRequest<{ ok: boolean }>('/forgot-password', {
    method: 'POST',
    body: JSON.stringify({ identifier }),
  });
}

/** Set a new password with the emailed reset code; revokes all sessions. */
export function resetPassword(
  email: string,
  otp: string,
  newPassword: string,
): Promise<{ ok: boolean }> {
  return authRequest<{ ok: boolean }>('/reset-password', {
    method: 'POST',
    body: JSON.stringify({ email, otp, new_password: newPassword }),
  });
}

export function loginSession(body: AuthCredentials): Promise<AuthSession> {
  return authRequest<AuthSession>('/login', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/**
 * Ask the backend to email a one-time sign-in code.
 *
 * The backend answers `{ ok: true }` for every identifier — known account,
 * unknown address, phone number, malformed input and cooldown-suppressed
 * resend alike — so this can never be used to discover which addresses are
 * registered. The UI must therefore treat "sent" as unconfirmed and show the
 * code step either way, exactly like forgot-password.
 */
export function requestLoginCode(
  identifier: string,
): Promise<{ ok: boolean }> {
  return authRequest<{ ok: boolean }>('/login/code', {
    method: 'POST',
    body: JSON.stringify({ identifier }),
  });
}

/** Exchange a valid emailed sign-in code for a session. */
export function verifyLoginCode(email: string, otp: string): Promise<AuthSession> {
  return authRequest<AuthSession>('/login/code/verify', {
    method: 'POST',
    body: JSON.stringify({ email, otp }),
  });
}

export function logoutSession(token: string): Promise<{ ok: boolean }> {
  return authRequest<{ ok: boolean }>('/logout', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });
}

/** Start an Auth0 "Continue with Google" flow; returns the authorize URL. */
export function startSocialLogin(): Promise<{ url: string }> {
  return authRequest<{ url: string }>('/social/login', { method: 'POST' });
}

/** Exchange the single-use SSO ticket (from /auth/callback) for a session. */
export function completeSocialLogin(ticket: string): Promise<AuthSession> {
  return authRequest<AuthSession>('/social/session', {
    method: 'POST',
    body: JSON.stringify({ ticket }),
  });
}

/** Validate a stored token and refresh the user + wallet. */
export function fetchAuthMe(token: string): Promise<AuthSession> {
  return authRequest<AuthSession>('/me', {
    headers: { Authorization: `Bearer ${token}` },
  });
}

/** Change the authenticated account's password (returns a fresh token). */
export function changePasswordSession(
  current: string,
  next: string,
): Promise<AuthSession> {
  const session = loadStoredSession();
  return authRequest<AuthSession>('/password', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(session?.token ? { Authorization: `Bearer ${session.token}` } : {}),
    },
    body: JSON.stringify({ current, new: next }),
  });
}

// ---------------------------------------------------------------------------
// Leaderboard + notifications (client helpers)
// ---------------------------------------------------------------------------

export function fetchLeaderboard(limit = 25): Promise<LeaderboardEntry[]> {
  return clientJson<LeaderboardEntry[]>(`/leaderboard?limit=${limit}`);
}

export function fetchNotificationsSession(
  walletId: string,
  limit = 25,
): Promise<NotificationItem[]> {
  return clientJson<NotificationItem[]>(
    `/wallet/${encodeURIComponent(walletId)}/notifications?limit=${limit}`,
  );
}

export function markNotificationsReadSession(
  walletId: string,
  ids?: string[],
): Promise<{ ok: boolean; marked: number }> {
  return clientJson<{ ok: boolean; marked: number }>(
    `/wallet/${encodeURIComponent(walletId)}/notifications/read`,
    {
      method: 'POST',
      body: JSON.stringify({ ids: ids ?? [] }),
    },
  );
}

/**
 * Admin API helpers.
 *
 * These talk to the same-origin `/api/*` proxy at runtime, which forwards to
 * the Ketsa API. The runtime proxy (app/api/[...path]/route.ts) exchanges the
 * admin bearer token for an `HttpOnly; SameSite=Strict` cookie, so **no admin
 * token is ever stored in JavaScript**. Calls are authenticated by that cookie.
 */

/** Path used client-side. Public read helper below uses API_BASE directly. */
const ADMIN_BASE = '/api/admin';

/**
 * Log in. On success the proxy sets the HttpOnly admin cookie; the response
 * body contains no token by design.
 */
export async function adminLogin(password: string): Promise<void> {
  const res = await fetch(`${ADMIN_BASE}/login`, {
    method: 'POST',
    credentials: 'same-origin',
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
}

/** Revoke the server-side admin session and clear the cookie. */
export async function adminLogout(): Promise<void> {
  await fetch(`${ADMIN_BASE}/logout`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
}

/** True when the browser currently holds a valid admin session. */
export async function adminMe(): Promise<void> {
  await adminGet<unknown>('/me');
}

export class AdminApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function adminFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${ADMIN_BASE}${path}`, {
    ...init,
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  if (res.status === 401) {
    throw new AdminApiError(401, 'Unauthorized - please log in again');
  }
  if (!res.ok) {
    // Surface the backend's reason (e.g. "a staff member with that email
    // already exists") rather than a bare status, so the admin UI can explain
    // what went wrong.
    let detail = `Request failed (${res.status}): ${path}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === 'string' && body.detail) detail = body.detail;
    } catch {
      /* keep the generic message */
    }
    throw new AdminApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function adminGet<T>(path: string): Promise<T> {
  return adminFetch<T>(path);
}

export function adminPost<T>(path: string, body: unknown): Promise<T> {
  return adminFetch<T>(path, { method: 'POST', body: JSON.stringify(body) });
}

export function adminPut<T>(path: string, body: unknown): Promise<T> {
  return adminFetch<T>(path, { method: 'PUT', body: JSON.stringify(body) });
}

export function adminDelete<T>(path: string): Promise<T> {
  return adminFetch<T>(path, { method: 'DELETE' });
}

// --- Broadcast (one admin announcement to every user with an email) ----------

export interface BroadcastAccepted {
  job_id: string;
  total: number;
}

export interface BroadcastStatus {
  job_id: string;
  status: 'running' | 'done' | 'error';
  total: number;
  sent: number;
  failed: number;
  subject: string;
  error: string | null;
}

/**
 * Queue an announcement. Returns immediately with a job id: the backend sends
 * one email per recipient in the background, because a few thousand recipients
 * takes far longer than an HTTP request may wait.
 */
export function startBroadcast(
  subject: string,
  body: string,
): Promise<BroadcastAccepted> {
  return adminPost<BroadcastAccepted>('/broadcast', { subject, body });
}

export function getBroadcastStatus(jobId: string): Promise<BroadcastStatus> {
  return adminGet<BroadcastStatus>(`/broadcast/${encodeURIComponent(jobId)}`);
}

// --- Staff directory ---------------------------------------------------------

/** Public team directory (server-side helper; PII-free). */
export async function fetchStaffPublic(): Promise<StaffPublic[]> {
  return fetchReadJson<StaffPublic[]>(`${API_BASE}/api/staff`);
}

/** Public team directory (client-side, via the same-origin proxy). */
export function fetchStaffSession(): Promise<StaffPublic[]> {
  return clientJson<StaffPublic[]>('/staff');
}

export interface StaffCreateInput {
  name: string;
  email: string;
  phone?: string | null;
  role: string;
}

export function listStaff(): Promise<StaffMember[]> {
  return adminGet<StaffMember[]>('/staff');
}

export function createStaff(input: StaffCreateInput): Promise<StaffMember> {
  return adminPost<StaffMember>('/staff', input);
}

export function uploadStaff(payload: {
  text?: string;
  rows?: Record<string, unknown>[];
}): Promise<StaffUploadResult> {
  return adminPost<StaffUploadResult>('/staff/upload', payload);
}

export function updateStaff(
  id: string,
  patch: Partial<Pick<StaffMember, 'name' | 'email' | 'phone' | 'role' | 'active'>>,
): Promise<StaffMember> {
  return adminPut<StaffMember>(`/staff/${encodeURIComponent(id)}`, patch);
}

export function deleteStaff(
  id: string,
): Promise<{ ok: boolean; detail?: string }> {
  return adminDelete<{ ok: boolean; detail?: string }>(
    `/staff/${encodeURIComponent(id)}`,
  );
}

export function inviteStaff(id: string): Promise<StaffInviteResult> {
  return adminPost<StaffInviteResult>(
    `/staff/${encodeURIComponent(id)}/invite`,
    {},
  );
}

// --- Admin config (Settings tab) ---------------------------------------------

export function getAdminConfig(): Promise<AdminConfig> {
  return adminGet<AdminConfig>('/config');
}

export function saveAdminConfig<K extends keyof AdminConfig>(
  section: K,
  value: AdminConfig[K],
): Promise<{ ok: boolean; detail?: string }> {
  return adminPut<{ ok: boolean; detail?: string }>(
    `/config/${encodeURIComponent(section)}`,
    value,
  );
}

