/** @type {import('next').NextConfig} */
// Browser security headers.
//
// The Content-Security-Policy is emitted by `middleware.ts`, not here: it needs
// a fresh nonce per request (a static header cannot provide one), and Next.js
// must see the policy while rendering so it can stamp its inline bootstrap
// scripts. Two CSP headers would be enforced as an intersection, so the
// nonce-less one would block the app's own bundles.
const nextConfig = {
  reactStrictMode: true,
  // Self-contained server output for a slim Docker runtime (Dockerfile.frontend).
  output: 'standalone',
  async headers() {
    // Static headers applied to every response (HTML pages and static
    // assets). See middleware.ts for the nonce-based CSP.
    return [
      {
        source: '/:path*',
        headers: [
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
