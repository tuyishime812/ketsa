// Shared WebSocket push client for wallet-scoped notifications and live
// leaderboard refreshes. Browser-only; guards against SSR/prerender.
//
// The server broadcasts one stream over /api/ws: market ticks/trades for
// everyone, plus wallet-scoped `notification` events that are only delivered
// to sockets that first sent { type: "sub", wallet_id, token }.
//
// The token matters: subscribing a wallet is a read of that wallet's private
// feed (deposits, withdrawals, mobile-money numbers, settlement payouts), so
// the server authorizes it with the same ownership check as the HTTP
// notification endpoints. An account wallet subscribed without a matching
// token is refused with a `sub_error` frame.

export interface PushEvent {
  type: string;
  [key: string]: unknown;
}

type Listener = (event: PushEvent) => void;

const WS_URL =
  (process.env.NEXT_PUBLIC_KETSA_BACKEND_URL || 'http://127.0.0.1:8000').replace(
    /^http/,
    'ws',
  ) + '/api/ws';

const listeners = new Set<Listener>();
let socket: WebSocket | null = null;
let walletId: string | null = null;
let walletToken: string | null = null;
let reconnectTimer: number | null = null;
let heartbeatTimer: number | null = null;
let retry = 0;
let started = false;

function clearTimers() {
  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (heartbeatTimer !== null) {
    window.clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

function teardown() {
  clearTimers();
  if (socket) {
    try {
      socket.close();
    } catch {
      /* ignore */
    }
  }
  socket = null;
}

function sendSub() {
  if (!socket || !walletId) return;
  try {
    socket.send(JSON.stringify({ type: 'sub', wallet_id: walletId, token: walletToken }));
  } catch {
    /* the close handler reconnects and re-subscribes */
  }
}

function open() {
  if (typeof window === 'undefined' || socket) return;
  try {
    socket = new WebSocket(WS_URL);
  } catch {
    scheduleReconnect();
    return;
  }
  socket.onopen = () => {
    retry = 0;
    sendSub();
    // Keep the connection alive past idle proxies.
    heartbeatTimer = window.setInterval(() => {
      try {
        socket?.send('ping');
      } catch {
        /* next close handler reconnects */
      }
    }, 25_000);
  };
  socket.onmessage = (ev) => {
    let payload: PushEvent;
    try {
      payload = JSON.parse(String(ev.data)) as PushEvent;
    } catch {
      return; // skip malformed / non-JSON frames
    }
    if (!payload || typeof payload.type !== 'string') return;
    if (payload.type === 'subscribed') return;
    listeners.forEach((l) => {
      try {
        l(payload);
      } catch {
        /* a bad listener must not kill the socket */
      }
    });
  };
  socket.onclose = () => {
    teardown();
    scheduleReconnect();
  };
  socket.onerror = () => {
    try {
      socket?.close();
    } catch {
      /* ignore */
    }
  };
}

function scheduleReconnect() {
  if (!started || reconnectTimer !== null) return;
  retry += 1;
  const delay = Math.min(1000 * retry, 15_000);
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null;
    open();
  }, delay);
}

/** Ensure the shared socket is connected (idempotent). */
export function startPush() {
  if (started) return;
  started = true;
  open();
}

/**
 * Subscribe the shared socket to a wallet so the server routes that wallet's
 * private notifications to this client. Pass the account's bearer token —
 * without it the server refuses an account-owned wallet.
 */
export function subscribeWallet(id: string | null, token: string | null = null) {
  walletId = id;
  walletToken = token;
  if (id && typeof window !== 'undefined' && socket?.readyState === WebSocket.OPEN) {
    sendSub();
  }
}

/**
 * Register a listener for push events. Returns an unsubscribe function.
 * Receives every broadcast event; filter by `event.type`.
 */
export function onPush(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function stopPush() {
  started = false;
  teardown();
}