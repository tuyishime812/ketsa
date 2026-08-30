# Ketsa

A real-time **prediction market** landing page — trade on the odds, not the
opinions. Ketsa is a fast, design-faithful single-page site built as a
separated **FastAPI backend** (seed data over a read-only JSON API) and a
**Next.js 15** frontend.

Originally a single static HTML file, this repo is the production-ready
split: the backend owns the data, the frontend renders it, and both are
built, tested, and deployable.

---

## Architecture

```
ketsa/
├── backend/                 FastAPI + Pydantic read-only data API
│   ├── app/
│   │   ├── main.py          App factory, routes, security headers, rate limit
│   │   ├── models.py        Pydantic wire-format models
│   │   └── data.py          Seed market data
│   ├── tests/               pytest suite (API, security, data)
│   └── requirements*.txt
├── frontend/                Next.js 15 + React 19 + Tailwind app
│   ├── app/                 App Router pages (server components)
│   ├── components/          UI sections (Hero, Markets, Dashboard, ...)
│   └── lib/                 API client, types, fallback data, utils
├── Dockerfile.backend
├── Dockerfile.frontend
└── docker-compose.yml
```

### Data flow

1. The Next.js page (`app/page.tsx`) is a **server component**; on each request
   it calls the backend `GET /api/home` via `lib/api.ts`.
2. If the backend is unreachable it renders bundled **fallback data**
   (`lib/fallbackData.ts`) so the page never blanks out, and shows a small
   "using bundled data" badge.
3. In local dev, `next.config.js` **rewrites** `/api/*` to the backend, so the
   browser only ever talks to the Next.js origin.

---

## Local development

### 1. Backend (FastAPI)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows (PowerShell)
# source .venv/bin/activate      # macOS/Linux

pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

Verify: `http://127.0.0.1:8000/api/health` → `{"status":"ok"}`.

### 2. Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. The `/api/*` rewrite talks to the backend on
`127.0.0.1:8000` by default (override with `KETSA_BACKEND_URL`).

---

## Tests

```bash
# Backend
cd backend
.venv\Scripts\python.exe -m pytest
# 35 tests: endpoints, models/seed consistency, 404/405, CORS,
# security headers, OpenAPI gating, rate limiting.

# Frontend
cd frontend
npm run build                     # type-check + production build
```

---

## Docker (recommended for deploy)

```bash
docker compose up --build
# Frontend:  http://localhost:3000
# API:       http://localhost:8000/api/health
```

Environment variables for both services are documented in `.env.example`
and wired through `docker-compose.yml`.

---

## Configuration / environment

| Variable                     | Where     | Purpose                                              | Default |
|------------------------------|-----------|------------------------------------------------------|---------|
| `KETSA_ALLOWED_ORIGINS`      | backend   | Comma-separated CORS origin allowlist                | `http://localhost:3000,http://127.0.0.1:3000` |
| `KETSA_EXPOSE_DOCS`          | backend   | `1` to enable `/docs` `/redoc` `/openapi.json`       | `0` (off) |
| `KETSA_RATE_LIMIT_PER_MIN`   | backend   | Requests/IP/60s fixed window (`0` disables)          | `120` |
| `KETSA_BACKEND_URL`          | frontend  | Base URL of the FastAPI service (server-side fetch)  | `http://127.0.0.1:8000` |
| `KETSA_CSP`                  | frontend  | Optional override for the emitted CSP header         | built-in policy |

---

## Security notes

**Posture.** The API is public and **read-only** (`allow_methods=["GET"]`,
`allow_credentials=False`, CORS restricted to an allowlist). All dynamic
content flows through React's escaping; a codebase grep found **no**
`dangerouslySetInnerHTML`, `eval`, or raw-HTML sinks in app code.

**HTTP security headers (both services).**
- `Content-Security-Policy`: `default-src 'self'` plus the allowances Next.js
  needs (`script-src 'unsafe-inline'` for RSC bootstrap, `style-src
  'unsafe-inline'` for React inline styles). `frame-ancestors 'none'`,
  `object-src 'none'`.
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Cross-Origin-Opener-Policy: same-origin`,
  `Cross-Origin-Resource-Policy: same-origin`,
  `X-Permitted-Cross-Domain-Policies: none`, `Referrer-Policy`,
  `Permissions-Policy`.

**OpenAPI docs are off by default** (`KETSA_EXPOSE_DOCS=0`) to avoid leaking
the API schema publicly. Turn them on only for debugging.

**Rate limiting.** A per-instance in-memory fixed-window limiter (default 120
req/min/IP) returns `429` past the limit. It is not a substitute for a
distributed limiter when scaling horizontally — put a shared limiter (e.g.
Caddy rate limit / NGINX) in front for production.

**Known dependency note (PostCSS).** `npm audit` reports a high/moderate
finding for **postcss bundled inside `next@15.5.x`** (`GHSA-qx2v-qp2m-jg93`).
Context:
- It is **build-time only** and **not exploitable** for Next.js consumers
  (it requires building from already-compromised source, per Vercel's
  advisory note). The top-level `postcss` dependency is already on the fixed
  `8.5.26`.
- npm's `overrides` cannot replace the postcss **vendored deep inside** Next,
  and Next has no stable 15.x release carrying the fix yet (the fix landed in
  the 16.3 canary line).
- **Resolution path:** upgrade Next to a stable release `>= 16.3.0-canary.6`
  once available, or pin `next` to a future 15.x patch that ships
  `postcss >= 8.5.10`.

**Docker.** Both images run as **non-root** users; the backend user has no
shell and no default login. The backend `requirements.txt` is pinned.

---

## Deploying

Any Node + Python PaaS works:

- **Frontend** — Vercel/deploy: build `frontend/`, set `KETSA_BACKEND_URL` to
  the hosted API. Since the page **falls back** to bundled data, it also works
  as a purely static/standalone site, though live data needs the API.
- **Backend** — Railway/Render/Fly: run `uvicorn app.main:app`, expose `8000`,
  set `KETSA_ALLOWED_ORIGINS` to the real frontend origin.
- **All-in-one** — use `docker compose up --build` behind a TLS proxy.

---

## License

© 2026 Ketsa. All rights reserved.
