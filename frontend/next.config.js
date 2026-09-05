/** @type {import('next').NextConfig} */
const backendUrl = process.env.KETSA_BACKEND_URL || 'http://127.0.0.1:8000';
// ws/wss variant of the backend origin for the live market feed.
const backendWs = backendUrl.replace(/^http/, 'ws');

const nextConfig = {
  reactStrictMode: true,
  // Self-contained server output for a slim Docker runtime (Dockerfile.frontend).
  output: 'standalone',
  async rewrites() {
    // In development, proxy /api calls to the FastAPI backend.
    const backend = backendUrl;
    return [
      {
        source: '/api/:path*',
        destination: `${backend}/api/:path*`,
      },
    ];
  },
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
    //     trading API and the live order-book feed can be reached directly from
    //     the browser (the same-origin /api rewrite proxies most HTTP calls,
    //     but WebSockets must connect to the backend directly).
    const csp = process.env.KETSA_CSP || [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data:",
      "font-src 'self'",
      `connect-src 'self' ${backendUrl} ${backendWs}`,
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
    ];
  },
};

module.exports = nextConfig;
