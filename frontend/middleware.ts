import { NextRequest, NextResponse } from 'next/server';

/**
 * Per-request Content-Security-Policy with a cryptographic nonce.
 *
 * The previous policy allowed `script-src 'unsafe-inline'`, which defeats the
 * main purpose of CSP: any HTML-injection bug (or a compromised third-party
 * script) could execute inline JavaScript. That mattered because the admin
 * session grants real-money controls. Next.js emits inline bootstrap scripts,
 * so instead of allowing every inline script we mint a fresh nonce per request
 * and hand it to Next via the request headers; Next stamps its own script tags
 * with it. `'strict-dynamic'` then lets those trusted scripts load the rest of
 * the chunks.
 *
 * `style-src` keeps `'unsafe-inline'` because React uses inline `style`
 * attributes throughout the UI (and style injection is a much smaller risk
 * than script injection).
 *
 * Set `KETSA_CSP` (optionally with a `{nonce}` placeholder) to override the
 * built-in policy. If the override contains no nonce, it is used verbatim.
 */
function buildCsp(nonce: string): string {
  const override = process.env.KETSA_CSP;
  if (override && override.trim()) {
    return override.replaceAll('{nonce}', nonce);
  }

  // The browser talks to the backend directly only for the live WebSocket
  // feed; HTTP API calls are same-origin through /api/*. On Vercel services the
  // feed may use same-origin /api/ws (routed to the backend), so 'self' covers
  // it; an explicit public backend origin (if configured) is added for
  // cross-origin deployments.
  const backend =
    process.env.NEXT_PUBLIC_KETSA_BACKEND_URL ||
    process.env.KETSA_BACKEND_URL ||
    '';
  const backendWs = backend ? backend.replace(/^http/i, 'ws') : '';
  const isDev = process.env.NODE_ENV !== 'production';

  const scriptSrc = [
    "'self'",
    `'nonce-${nonce}'`,
    "'strict-dynamic'",
    // `next dev` compiles modules with eval-source-map; production builds use
    // source maps and do not need it.
    ...(isDev ? ["'unsafe-eval'"] : []),
  ].join(' ');

  return [
    "default-src 'self'",
    `script-src ${scriptSrc}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    `connect-src 'self'${backend ? ` ${backend}` : ''}${backendWs ? ` ${backendWs}` : ''}`,
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
  ].join('; ');
}

function makeNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

export function middleware(request: NextRequest): NextResponse {
  const nonce = makeNonce();
  const csp = buildCsp(nonce);

  // Next.js reads the policy/nonce from the request headers when rendering the
  // document and adds the nonce to its inline bootstrap scripts.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set('x-nonce', nonce);
  requestHeaders.set('content-security-policy', csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set('Content-Security-Policy', csp);
  return response;
}

export const config = {
  // Documents only: API proxy responses and static assets do not need a page
  // CSP, and skipping them avoids the middleware overhead.
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};
