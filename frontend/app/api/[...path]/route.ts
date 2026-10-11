// Runtime reverse proxy for every browser-side /api/* call.
//
// Why this exists (and why it replaces the old next.config.js rewrite):
//
//   The public pages fetch the backend **server-side** at request time, so a
//   runtime env var is enough for them. But the browser-side calls — auth
//   (login / register / OTP / social), admin, wallet, trades, payments and
//   notifications — all hit same-origin `/api/*` from the client bundle.
//
//   Those used to be handled by `next.config.js` → `rewrites()`, whose
//   destination is computed from `process.env.KETSA_BACKEND_URL` **at build
//   time**. On a host like Vercel the var is usually present only at runtime,
//   so the rewrite baked in `http://127.0.0.1:8000`. The edge then refuses to
//   proxy to a private host and answers
//   `404 DNS_HOSTNAME_RESOLVED_PRIVATE` — the "Log in"/"Create account"
//   buttons (and everything else that talks to the API from the browser) break
//   while the rest of the page still renders.
//
//   A route handler runs at **request** time, so it reads `KETSA_BACKEND_URL`
//   from the live environment and always reaches the real backend — no
//   build-time coupling.
//
// Security notes:
//   * The upstream origin is fixed from the environment; only the path + query
//     are forwarded, so a caller cannot retarget the proxy (no SSRF).
//   * Hop-by-hop headers are stripped both ways; the remaining request headers
//     (including `authorization`) are forwarded unchanged. Note the backend
//     keys its per-IP limits on the connection peer, so behind this proxy those
//     limits are enforced per proxy instance, not per visitor.
//   * The request body is buffered (bounded by the platform's request limit)
//     and streamed back unchanged; nothing is logged beyond a failure line.

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
]);

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

async function proxy(request: Request): Promise<Response> {
  const origin = backendOrigin();
  if (!origin) {
    return NextResponse.json(
      { detail: 'API service is not configured' },
      { status: 502 },
    );
  }

  const incoming = new URL(request.url);
  // `/api/<...>` is forwarded verbatim; the origin comes from the environment,
  // so the path can never change the destination host.
  const target = new URL(origin + incoming.pathname + incoming.search);

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  });
  // Ask upstream for an uncompressed body: fetch decodes automatically and we
  // stream the decoded bytes back, so a stale Content-Encoding must not survive.
  headers.set('accept-encoding', 'identity');

  const method = request.method.toUpperCase();
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
