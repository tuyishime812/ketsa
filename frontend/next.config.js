/** @type {import('next').NextConfig} */
// Public backend origin, used only to build the browser CSP below. The
// browser-side /api/* traffic is handled by the runtime proxy in
// `app/api/[...path]/route.ts`, which resolves its own destination from the
// request-time environment — so routing no longer depends on build-time vars
// (the cause of `404 DNS_HOSTNAME_RESOLVED_PRIVATE` in production).
const publicBackendUrl =
  process.env.NEXT_PUBLIC_KETSA_BACKEND_URL ||
  process.env.KETSA_BACKEND_URL ||
  'http://127.0.0.1:8000';
// ws/wss variant of the backend origin for the live market feed.
const backendWs = publicBackendUrl.replace(/^http/, 'ws');

const nextConfig = {
  reactStrictMode: true,
  // Self-contained server output for a slim Docker runtime (Dockerfile.frontend).
  output: 'standalone',
  async headers() {
    // Browser security headers applied to every response the Next.js server
    // emits (HTML pages and static assets).
    //
    // CSP notes:
    //   * `script-src 'self' 'unsafe-inline'` is required for Next.js's inline
    //     React Server Component bootstrap scripts. That weakens script CSP vs
    //     a fully nonce-based policy; the upgrade path is to switch to
    //     per-request nonces via a middleware. We accept it here because all
    //     rendered dynamic content flows through React's escaping and no
    //     user-controlled HTML is ever injected.
    //   * `style-src 'unsafe-inline'` is required for React inline `style`
    //     attributes used throughout the UI (animations, progress widths).
    //   * `connect-src` additionally lists the backend HTTP + WS origins so the
    //     live order-book WebSocket feed can be reached directly from the
    //     browser. HTTP API calls go same-origin through the runtime proxy in
    //     `app/api/[...path]/route.ts`; WebSockets must connect to the backend
    //     directly, so its origin must be allowed here.
    // Development needs 'unsafe-eval': `next dev` builds webpack bundles with
    // devtool `eval-source-map`, so every module is executed through eval().
    // Without it the browser blocks all client JS and React never hydrates —
    // the HTML (and its buttons) render but no onClick ever fires. Production
    // builds use `source-map`, not eval, so the strict policy stays there.
    const isDev = process.env.NODE_ENV !== 'production';
    const scriptSrc = isDev
      ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
      : "script-src 'self' 'unsafe-inline'";

    const csp = process.env.KETSA_CSP || [
      "default-src 'self'",
      scriptSrc,
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data:",
      "font-src 'self'",
      `connect-src 'self' ${publicBackendUrl} ${backendWs}`,
      "base-uri 'self'",
      "form-action 'self'",
      "frame-ancestors 'none'",
      "object-src 'none'",
    ].join('; ');

    return [
      {
        source: '/:path*',
        headers: [
          { key: 'Content-Security-Policy', value: csp },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          {
            key: 'Permissions-Policy',
            value: 'camera=(), microphone=(), geolocation=()',
          },
          { key: 'X-Permitted-Cross-Domain-Policies', value: 'none' },
          { key: 'Cross-Origin-Opener-Policy', value: 'same-origin' },
          { key: 'Cross-Origin-Resource-Policy', value: 'same-origin' },
        ],
      },
      // The social-login callback receives a single-use ticket in the query
      // string. It is a bearer credential for the whole session, so nothing
      // from this page may be sent as a Referer — not even to our own origin
      // (sub-resources and client-side navigations would otherwise carry the
      // full URL). The page redeems the ticket immediately and replaces the
      // address bar; `no-referrer` closes the window before that happens.
      {
        source: '/auth/callback',
        headers: [{ key: 'Referrer-Policy', value: 'no-referrer' }],
      },
    ];
  },
};

module.exports = nextConfig;
