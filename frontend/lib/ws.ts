// Single source of truth for the live-feed WebSocket URL.
//
// The browser connects to the backend for the feed: the Next runtime proxy in
// `app/api/[...path]/route.ts` handles normal HTTP but does not proxy WebSocket
// upgrades. Resolution order:
//   1. `NEXT_PUBLIC_KETSA_BACKEND_URL` (build-time, inlined) — explicit public
//      backend origin for cross-origin deployments.
//   2. Browser same-origin — on Vercel services `/api/*` is routed to the
//      backend, so the socket can use the current origin (`wss://host/api/ws`).
//   3. Local dev fallback — `http://127.0.0.1:8000` during SSR/build.

function resolveBase(): string {
  if (process.env.NEXT_PUBLIC_KETSA_BACKEND_URL) {
    return process.env.NEXT_PUBLIC_KETSA_BACKEND_URL;
  }
  if (typeof window !== 'undefined' && window.location?.origin) {
    return window.location.origin;
  }
  // SSR/build fallback for local development.
  return process.env.KETSA_BACKEND_URL || 'http://127.0.0.1:8000';
}

function deriveWsUrl(): string {
  const base = resolveBase().replace(/\/+$/, '');
  // https -> wss, http -> ws, so a TLS deployment keeps a secure socket
  // (a ws:// socket from an https page is blocked as mixed content).
  return base.replace(/^http/i, 'ws') + '/api/ws';
}

export const WS_URL = deriveWsUrl();

export const WS_URL_IS_LOOPBACK = /\/\/(127\.0\.0\.1|localhost)(:|\/)/.test(
  WS_URL,
);

// Surface the build-time misconfiguration in the browser console instead of
// leaving a silently-dead feed. Runs client-side only; harmless elsewhere.
if (
  typeof window !== 'undefined' &&
  process.env.NODE_ENV === 'production' &&
  WS_URL_IS_LOOPBACK
) {
  console.warn(
    '[ketsa] Live feed is pointed at localhost in a production build. Set ' +
      'NEXT_PUBLIC_KETSA_BACKEND_URL to the public API origin and rebuild, or use same-origin /api routing.',
  );
}
