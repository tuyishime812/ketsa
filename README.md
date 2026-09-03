# Ketsa

A real-time **prediction market** landing page — trade on the odds, not the
opinions. Ketsa is a fast, design-faithful single-page site built as a
separated **FastAPI backend** (seed data over a JSON API) and a **Next.js 15**
frontend.

Originally a single static HTML file, this repo is the production-ready
split: the backend owns the data, the frontend renders it, and a
**password-gated admin panel** at `/admin` lets the site owner edit all
content from the browser instead of touching code.

---

## Architecture

```
ketsa/
├── backend/                 FastAPI + Pydantic data API
│   ├── app/
│   │   ├── main.py          App factory, routes, security headers, rate limit
│   │   ├── models.py        Pydantic wire-format models
│   │   ├── data.py          Seed market data
│   │   ├── database.py      SQLite schema + idempotent seeding + settings store
│   │   ├── store.py         Read/write helpers over SQLite
│   │   └── admin.py         Protected /api/admin router (auth + CRUD)
│   ├── tests/               pytest suite (API, security, data, admin)
│   └── requirements*.txt
├── frontend/                Next.js 15 + React 19 + Tailwind app
│   ├── app/                 App Router pages (server components)
│   │   └── admin/           Admin login + dashboard (sidebar, per-section editors)
│   ├── components/          Public UI sections (Hero, Markets, Dashboard, ...)
│   │   └── admin/           Admin editors (Markets, Hero, Ticker, Watch, ...)
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

### 3. Admin panel

With both services running, log in at **`http://localhost:3000/admin`**:

- The first login uses the password from `KETSA_ADMIN_PASSWORD`
  (default `ketsa-admin` for local dev — **set a real one for production**).
- The dashboard has a sidebar with editors for **Markets, Hero, Ticker,
  Watch, Dashboard, and Content** (hero/CTA copy, steps, footer, section
  headings).
- Edits are saved to SQLite immediately and appear on the public site right
  away — no code changes or redeploys required. Markets created here also show
  up on `/api/markets`.

---

## Tests

```bash
# Backend
cd backend
.venv\Scripts\python.exe -m pytest
# 42 tests: endpoints, models/seed consistency, 404/405, CORS,
# security headers, OpenAPI gating, rate limiting, admin auth + CRUD.

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
| `KETSA_ADMIN_PASSWORD`       | backend   | Password for the `/admin` panel (the only auth key)  | `ketsa-admin` |
| `KETSA_DB_PATH`              | backend   | Path to the SQLite database file                     | `backend/ketsa.db` |

---

## Security notes

**Posture.** The API is public and **read-only** for site visitors
(`allow_methods=["GET"]`, `allow_credentials=False`, CORS restricted to an
allowlist). **Writes** live only under `/api/admin/*` and are protected by a
bearer token obtained from `POST /api/admin/login` with `KETSA_ADMIN_PASSWORD`
(tokens last 12h with a sliding window). Admin endpoints are **not** covered by
the CORS allowlist restriction in the same way as reads, but they require the
token on every request. All dynamic content flows through React's escaping; a
codebase grep found **no** `dangerouslySetInnerHTML`, `eval`, or raw-HTML sinks
in app code.

**Admin password.** `KETSA_ADMIN_PASSWORD` is the only key to the whole site.
It is read from the environment (does **not** fall back to a committed secret),
defaults to `ketsa-admin` for local dev, and **must** be set to a strong,
unique value in production. Tokens are held in memory (no persistence), so a
backend restart revokes all sessions.

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
  set `KETSA_ALLOWED_ORIGINS` to the real frontend origin and
  `KETSA_ADMIN_PASSWORD` to a strong value. Point `KETSA_DB_PATH` at a
  **persistent volume** so admin-edited content survives redeploys.
- **All-in-one** — use `docker compose up --build` behind a TLS proxy.

See `DEPLOY.md` for the full admin + persistent-storage walkthrough.

---

## License

© 2026 Ketsa. All rights reserved.
