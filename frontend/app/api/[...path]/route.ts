// Runtime reverse proxy for every browser-side /api/* call.
//
// Why this exists (and why it replaces the old next.config.js rewrite):
//
//   The public pages fetch the backend **server-side** at request time, so a
//   runtime env var is enough for them. But the browser-side calls �?" auth
//   (login / register / OTP / social), admin, wallet, trades, payments and
//   notifications �?" all hit same-origin `/api/*` from the client bundle.
//
//   Those used to be handled by `next.config.js` �+' `rewrites()`, whose
//   destination is computed from `process.env.KETSA_BACKEND_URL` **at build
//   time**. On a host like Vercel the var is usually present only at runtime,
//   so the rewrite baked in `http://127.0.0.1:8000`. The edge then refuses to
//   proxy to a private host and answers
//   `404 DNS_HOSTNAME_RESOLVED_PRIVATE` �?" the "Log in"/"Create account"
//   buttons (and everything else that talks to the API from the browser) break
//   while the rest of the page still renders.
//
//   A route handler runs at **request** time, so it reads `KETSA_BACKEND_URL`
//   from the live environment and always reaches the real backend �?" no
//   build-time coupling.
//
// Security notes:
//   * The upstream origin is fixed from the environment; only the path + query
//     are forwarded, so a caller cannot retarget the proxy (no SSRF).
//   * Hop-by-hop headers are stripped both ways.
//   * **Admin session cookie.** `/api/admin/login` returns a bearer token; this
//     proxy moves it into an `HttpOnly; SameSite=Strict` cookie scoped to
//     `/api/admin` and strips it from the JSON body, so no admin credential is
//     ever readable by JavaScript (XSS can act in-session but cannot exfiltrate
//     or persist the token). Subsequent admin calls get the cookie re-attached
//     as `Authorization: Bearer ...` server-side. Cookie-authenticated unsafe
//     methods are additionally Origin/Sec-Fetch-Site checked (CSRF defence in
//     depth) and the cookie is cleared on logout/401/403.
//   * **Client IP.** The backend's rate limits and admin lockout key on the
//     caller IP, but this proxy would otherwise collapse every visitor into
//     one bucket. When `KETSA_PROXY_SECRET` is set (same value in both
//     services) the real client IP is HMAC-signed into
//     `X-Ketsa-Client-*` headers, which the backend verifies. Without the
//     secret the backend falls back to trusted-proxy CIDRs or the direct peer.
//   * The request body is buffered (bounded by the platform's request limit)
//     and streamed back unchanged; nothing is logged beyond a failure line.

import { createHmac } from 'node:crypto';
import { isIP } from 'node:net';
import { NextResponse } from 'next/server';

// Never cache or statically evaluate proxied API traffic.
export const dynamic = 'force-dynamic';
export const revalidate = 0;
export const fetchCache = 'force-no-store';
export const runtime = 'nodejs';

// Headers that describe a single hop and must not be forwarded.
const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
  'host',
  'content-length',
  'accept-encoding',
  // Not hop-by-hop in the RFC sense, but undici (Node's fetch) rejects the
  // `Expect` header outright, so forwarding a caller's `Expect: 100-continue`
  // makes the upstream request throw. Strip it and let fetch handle expectations.
  'expect',
]);

const ADMIN_COOKIE = 'ketsa_admin';
// Matches the backend's admin token TTL (12h, sliding).
const ADMIN_COOKIE_MAX_AGE = 12 * 60 * 60;
// `secrets.token_urlsafe(32)` => 43 URL-safe characters. Anything else is not
// a token we minted, so never place it in a header or cookie.
const ADMIN_TOKEN_RE = /^[A-Za-z0-9_-]{20,128}$/;
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
// Incoming client-IP headers are never trusted; they are stripped and then
// re-set from our own verification path only.
const CLIENT_IP_HEADERS = [
  'x-ketsa-client-ip',
  'x-ketsa-client-timestamp',
  'x-ketsa-client-signature',
];

/** Resolve the configured backend origin, or null when it is unset/invalid. */
function backendOrigin(): string | null {
  const raw =
    process.env.KETSA_BACKEND_URL || process.env.NEXT_PUBLIC_KETSA_BACKEND_URL;
  if (!raw) return null;
  try {
    const url = new URL(raw);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    return url.origin;
  } catch {
    return null;
  }
}

function methodHasNoBody(method: string): boolean {
  return method === 'GET' || method === 'HEAD' || method === 'OPTIONS';
}

function parseCookies(header: string | null): Map<string, string> {
  const cookies = new Map<string, string>();
  if (!header) return cookies;
  for (const part of header.split(';')) {
    const index = part.indexOf('=');
    if (index === -1) continue;
    const name = part.slice(0, index).trim();
    let value = part.slice(index + 1).trim();
    if (value.startsWith('"') && value.endsWith('"')) {
      value = value.slice(1, -1);
    }
    if (name && !cookies.has(name)) cookies.set(name, value);
  }
  return cookies;
}

function withoutCookie(header: string | null, name: string): string {
  if (!header) return '';
  return header
    .split(';')
    .map((part) => part.trim())
    .filter((part) => part && part.split('=')[0].trim() !== name)
    .join('; ');
}

/** Parse an address that may carry a port or IPv6 brackets. */
function normalizeIp(raw: string | null | undefined): string {
  if (!raw) return '';
  let value = raw.trim();
  if (!value) return '';
  if (value.startsWith('[')) {
    const end = value.indexOf(']');
    if (end === -1) return '';
    value = value.slice(1, end);
  } else if (value.split(':').length === 2) {
    const [host, port] = value.split(':');
    if (host && /^\d+$/.test(port)) value = host;
  }
  return isIP(value) ? value : '';
}

/**
 * The caller address as seen by the platform edge. The leftmost
 * `X-Forwarded-For` entry is the client; the edge rewrites this header, so a
 * value supplied by the caller is not preserved. If no platform header is
 * present we return '' rather than guessing (the backend then uses its peer).
 */
function incomingClientIp(request: Request): string {
  const forwarded = request.headers.get('x-forwarded-for');
  if (forwarded) {
    const first = normalizeIp(forwarded.split(',')[0]);
    if (first) return first;
  }
  return normalizeIp(request.headers.get('x-real-ip'));
}

/** Sign the client IP so the backend can trust it without knowing the egress IP. */
function signedClientIpHeaders(clientIp: string): Record<string, string> {
  const secret = process.env.KETSA_PROXY_SECRET;
  if (!secret || !clientIp) return {};
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const signature = createHmac('sha256', secret)
    .update(`${clientIp}\n${timestamp}`)
    .digest('hex');
  return {
    'x-ketsa-client-ip': clientIp,
    'x-ketsa-client-timestamp': timestamp,
    'x-ketsa-client-signature': signature,
  };
}

/**
 * CSRF guard for cookie-authenticated admin writes. Browsers always set
 * `Host` to the target, so comparing the `Origin` host to the host this
 * request actually arrived on rejects cross-site form/fetch attempts even if
 * SameSite were ever relaxed. `Sec-Fetch-Site` is checked as well when present.
 */
function isSameOrigin(request: Request, url: URL): boolean {
  const origin = request.headers.get('origin');
  if (origin) {
    let originHost: string;
    try {
      originHost = new URL(origin).host;
    } catch {
      return false;
    }
    const forwardedHost = request.headers.get('x-forwarded-host');
    const hostHeader = request.headers.get('host');
    const expectedHost = (forwardedHost || hostHeader || url.host)
      .split(',')[0]
      .trim();
    if (!expectedHost || originHost !== expectedHost) return false;
  }
  const site = request.headers.get('sec-fetch-site');
  if (site && site !== 'same-origin' && site !== 'none') return false;
  return true;
}

function adminCookie(value: string, maxAge: number, secure: boolean): string {
  return [
    `${ADMIN_COOKIE}=${value}`,
    'Path=/api/admin',
    'HttpOnly',
    'SameSite=Strict',
    `Max-Age=${maxAge}`,
    secure ? 'Secure' : '',
  ]
    .filter(Boolean)
    .join('; ');
}

function isSecureRequest(request: Request, url: URL): boolean {
  if (url.protocol === 'https:') return true;
  const forwardedProto = request.headers.get('x-forwarded-proto');
  return forwardedProto?.split(',')[0].trim() === 'https';
}

function withCookies(headers: Headers, cookies: string[]): Headers {
  for (const cookie of cookies) headers.append('set-cookie', cookie);
  return headers;
}

async function proxy(request: Request): Promise<Response> {
  const origin = backendOrigin();
  if (!origin) {
    return NextResponse.json(
      { detail: 'API service is not configured' },
      { status: 502 },
    );
  }

  const incoming = new URL(request.url);
  const method = request.method.toUpperCase();
  // `/api/<...>` is forwarded verbatim; the origin comes from the environment,
  // so the path can never change the destination host.
  const target = new URL(origin + incoming.pathname + incoming.search);

  const isAdminPath =
    incoming.pathname === '/api/admin' ||
    incoming.pathname.startsWith('/api/admin/');
  const isLogin = incoming.pathname === '/api/admin/login';
  const isLogout = incoming.pathname === '/api/admin/logout';
  const secure = isSecureRequest(request, incoming);

  // Cookie-authenticated writes need the CSRF check. Login is included: it is
  // a state-changing POST and the same check is harmless for a same-origin
  // browser request.
  if (
    isAdminPath &&
    UNSAFE_METHODS.has(method) &&
    !isSameOrigin(request, incoming)
  ) {
    return NextResponse.json({ detail: 'Cross-origin request rejected' }, { status: 403 });
  }

  const cookies = parseCookies(request.headers.get('cookie'));
  const adminToken = cookies.get(ADMIN_COOKIE) ?? '';
  const hasAdminToken = ADMIN_TOKEN_RE.test(adminToken);

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  });
  // Ask upstream for an uncompressed body: fetch decodes automatically and we
  // stream the decoded bytes back, so a stale Content-Encoding must not survive.
  headers.set('accept-encoding', 'identity');
  // Never let a caller forge the backend's proxy-trust headers.
  for (const name of CLIENT_IP_HEADERS) headers.delete(name);
  // The admin cookie is a browser-only container for the bearer token; it must
  // not travel upstream as a cookie, and it is re-attached as Authorization.
  const cookieHeader = withoutCookie(headers.get('cookie'), ADMIN_COOKIE);
  if (cookieHeader) headers.set('cookie', cookieHeader);
  else headers.delete('cookie');

  const clientHeaders = signedClientIpHeaders(incomingClientIp(request));
  for (const [name, value] of Object.entries(clientHeaders)) {
    headers.set(name, value);
  }

  if (isAdminPath) {
    // Ignore any client-supplied Authorization: the HttpOnly cookie is the
    // only credential this proxy will vouch for.
    headers.delete('authorization');
    if (!isLogin && hasAdminToken) {
      headers.set('authorization', `Bearer ${adminToken}`);
    }
  }

  const body = methodHasNoBody(method)
    ? undefined
    : await request.arrayBuffer();

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method,
      headers,
      body,
      redirect: 'manual',
      cache: 'no-store',
      signal: AbortSignal.timeout(60_000),
    });
  } catch (err) {
    console.error(`API proxy failed: ${method} ${target.pathname}`, err);
    return NextResponse.json(
      { detail: 'API service unavailable' },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (HOP_BY_HOP.has(lower)) return;
    // fetch already decoded the body, so do not pass through encoding/length
    // headers that describe the on-the-wire bytes rather than what we return.
    if (lower === 'content-encoding' || lower === 'content-length') return;
    responseHeaders.append(key, value);
  });

  // Login: move the bearer token into an HttpOnly cookie and return no token.
  if (isLogin) {
    const text = await upstream.text();
    if (upstream.ok) {
      let token = '';
      try {
        token = String(JSON.parse(text)?.token ?? '');
      } catch {
        token = '';
      }
      if (!ADMIN_TOKEN_RE.test(token)) {
        return NextResponse.json(
          { detail: 'Invalid login response' },
          { status: 502 },
        );
      }
      const responseBody = new Headers(responseHeaders);
      responseBody.set('content-type', 'application/json');
      withCookies(responseBody, [
        adminCookie(token, ADMIN_COOKIE_MAX_AGE, secure),
      ]);
      return new NextResponse(JSON.stringify({ ok: true }), {
        status: upstream.status,
        headers: responseBody,
      });
    }
    // Failed login: clear any stale cookie and pass the error through.
    withCookies(responseHeaders, [adminCookie('', 0, secure)]);
    return new NextResponse(text, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  }

  if (isAdminPath) {
    if (upstream.status === 401 || upstream.status === 403) {
      // Expired/revoked session: stop sending a dead cookie.
      withCookies(responseHeaders, [adminCookie('', 0, secure)]);
    } else if (upstream.ok && !isLogout && hasAdminToken) {
      // Sliding window, matching the backend's 12h token TTL.
      withCookies(responseHeaders, [
        adminCookie(adminToken, ADMIN_COOKIE_MAX_AGE, secure),
      ]);
    } else if (isLogout) {
      withCookies(responseHeaders, [adminCookie('', 0, secure)]);
    }
  }

  return new NextResponse(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const HEAD = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
