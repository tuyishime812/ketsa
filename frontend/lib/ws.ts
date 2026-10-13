// Single source of truth for the live-feed WebSocket URL.
//
// The browser connects to the backend DIRECTLY for the feed: the Next runtime
// proxy in `app/api/[...path]/route.ts` handles normal HTTP but does not proxy
// WebSocket upgrades. That means the public API origin must be present in the
// CLIENT bundle — and `NEXT_PUBLIC_*` values are inlined by Next at BUILD time.
//
// The trap this guards against: `KETSA_BACKEND_URL` is server-only, so a
// production build that sets only that (and not
// `NEXT_PUBLIC_KETSA_BACKEND_URL`) compiles the browser fallback —
// ws://127.0.0.1:8000 — and the live market feed, notifications and leaderboard
// silently stop updating in production. See `.env.production.example`.

function deriveWsUrl(): string {
  const base =
    process.env.NEXT_PUBLIC_KETSA_BACKEND_URL || 'http://127.0.0.1:8000';
  // https -> wss, http -> ws, so a TLS deployment keeps a secure socket
  // (a ws:// socket from an https page is blocked as mixed content).
  return base.replace(/^http/, 'ws') + '/api/ws';
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
      'NEXT_PUBLIC_KETSA_BACKEND_URL to the public API origin and rebuild.',
  );
}
