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
│   │   ├── storage.py       Pluggable storage backends (memory / Supabase)
│   │   ├── store.py         Read/write helpers over the active backend
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

### Storage

The backend's data layer (`app/storage.py`) is pluggable and selected with
`KETSA_DB_BACKEND`:

- **`memory` (default)** — a fresh, seed-data-filled store in each process. Zero
  setup, ideal for local dev and previews; edits are lost on restart.
- **`supabase` (production)** — persists every market, watch/ticker row,
  dashboard series, stats, proof, the editable site settings, **wallet
  balances + payment ledger**, **user accounts**, and the **per-wallet
  notification feed** in Supabase Postgres (via the `supabase` Python
  SDK / PostgREST), so admin edits survive restarts and redeploys. Requires a
  Supabase project: set `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` and run
  `backend/db/schema.sql` once in the SQL editor.

The admin "reset content" endpoint re-seeds both backends to the original data
(preserving any stored admin password). Wallet balances and payment records are
**never** wiped by a content reset.

---

## Local development

> **One command (recommended).** From the repo root, `npm run dev` starts the
> FastAPI backend (port 8000) and the Next.js frontend (port 3000) together,
> so the site runs on the live demo data served by the API — no need to start
> two terminals. Ctrl+C stops both.

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
  Watch, Dashboard, Content, Users**, and **Manage** (hero/CTA copy, steps,
  footer, section headings). The **Users** tab lists every account with live
  wallet equity and lets you reset a user's password (revokes their sessions)
  or delete the account entirely.
- **Resolving markets.** The Markets editor has a **Resolve** action per
  market (once a market's status is `resolved` the button is hidden). Picking
  YES/NO settles every holder immediately: winning shares pay $1 each into the
  wallet balance, losing shares expire to zero, open positions are cleared,
  the winning outcome + final price are stored on the market, and each affected
  wallet gets a settlement notification. Resolved markets show their final
  answer everywhere (banner, order book, trade widget is disabled) and are
  locked against further trading.
- Edits are saved to the storage backend immediately and appear on the public
  site right away — no code changes or redeploys required. Markets created
  here also show up on `/api/markets`.
- The backend also supports changing the admin password and resetting all
  content back to the seed defaults (see `DEPLOY.md` for the persistence
  story).

### 4. Trading (Polymarket-style simulation)

With both services running you can trade each market for real on the site:

- **Play money.** Every visitor gets a simulated wallet seeded with **MK 1,000**
  (stored in `localStorage`). Click **Connect wallet** in the nav to create one.
- **Accounts.** Optional email accounts (`/api/auth/register`) let you keep a
  name and email on a wallet. The wallet's **equity and positions live on the
  storage backend** and your `Authorization: Bearer` token (30-day sliding)
  locks the account to its own wallet — trading or paying into another wallet
  returns `403`. Failed logins are throttled per email (`KETSA_AUTH_MAX_FAILURES`
  / `KETSA_AUTH_LOCKOUT_SECONDS`); you can change your password from the
  Portfolio ("Account" card), which revokes all other sessions and issues a
  fresh token.
- **Leaderboard.** `/leaderboard` ranks every wallet that has traded by live
  equity (P&L shown per row); refresh every 30s and immediately whenever a
  market resolves or a deposit/refund lands.
- **Notifications.** The bell in the nav (when a wallet is connected) lists the
  latest fills, deposits, withdrawal and settlement events per wallet, with
  unread badges and "mark all read". Live notifications arrive over the
  WebSocket (wallet-scoped) without needing a page refresh.
- **Resolution.** When an admin resolves a market, positions settle
  automatically — winning shares pay out at $1 each, losers expire, and the
  market locks at its final answer (see the panel docs above).
- **Markets.** `/markets` lists all markets with search, category filters and
  sorting (volume, liquidity, ending soon, newest). `/markets/<id>` has a price
  chart, a live YES/NO order book, a trade widget and a recent-trades tape.
- **Portfolio.** `/portfolio` tracks wallet balance, open positions, and realized
  + unrealized P&L against live prices, plus a **payments** panel for deposits
  and withdrawals via wandePay.
- **Live updates.** A WebSocket feed (`ws://…/api/ws`) streams market ticks,
  fills, **resolutions** and **leaderboard changes** to all open pages; clients
  can subscribe a wallet on the same socket to receive that wallet's private
  notification events. Order books and the trade tape refresh every few
  seconds as a fallback.
- **Persistence.** Today the engine keeps books and the trade tape in memory,
  but **wallets are persisted** through the storage backend — a funded balance
  survives a backend restart (use `KETSA_DB_BACKEND=supabase` in production
  when real money is involved).
- **Payments (wandePay — MWK).** With `KETSA_WANDE_TOKEN` configured, the
  portfolio lets users top up their balance with real money via Airtel Money /
  TNM Mpamba and payout back to mobile money. Deposits are credited when the
  wandePay order completes (idempotent — never double-credited); failed payouts
  are refunded automatically. Without a token the payment endpoints return 503
  and the site runs purely on play money.

Note: when the backend is **not** reachable from the browser at the default
`127.0.0.1:8000` (e.g. a Vercel frontend + hosted backend), set
`NEXT_PUBLIC_KETSA_BACKEND_URL` so the WebSocket feed knows where to connect.
The `/api/*` HTTP calls go through Next's rewrite proxy regardless.

---

## Tests

```bash
# Backend
cd backend
.venv\Scripts\python.exe -m pytest
# 117 tests: endpoints, models/seed consistency, 404/405, CORS,
# security headers, OpenAPI gating, rate limiting, admin auth + CRUD + user
# management, the matching engine (wallets, books, execution, WS feed),
# account auth (register/login, sessions, throttling, change password,
# wallet-binding on writes), leaderboard + notifications, wandePay
# payments (deposits, withdrawals, idempotent crediting, refunds), and
# market resolution (settlement/payout, trading locks, admin endpoint,
# wallet-scoped WS notification routing).

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
| `NEXT_PUBLIC_KETSA_BACKEND_URL` | frontend | Public backend origin embedded in the client bundle (WebSocket feed) | `http://127.0.0.1:8000` |
| `KETSA_CSP`                  | frontend  | Optional override for the emitted CSP header         | built-in policy |
| `KETSA_ADMIN_PASSWORD`       | backend   | Password for the `/admin` panel (the only auth key)  | `ketsa-admin` |
| `KETSA_DB_BACKEND`           | backend   | Storage backend: `memory` (default) or `supabase`   | `memory` |
| `SUPABASE_URL`               | backend   | Supabase project URL (Supabase only)                | — |
| `SUPABASE_SERVICE_ROLE_KEY`  | backend   | Supabase secret service-role key (Supabase only)    | — |
| `KETSA_WANDE_TOKEN`          | backend   | wandePay API token for MWK deposits/withdrawals (secret; absent ⇒ payments 503) | — (payments off) |
| `KETSA_WANDE_BASE_URL`       | backend   | wandePay API base URL                              | `https://apiv1.wandepay.site/api/` |
| `KETSA_AUTH_MAX_FAILURES`    | backend   | Failed logins per email before a temporary lockout  | `5` |
| `KETSA_AUTH_LOCKOUT_SECONDS` | backend   | Lockout window after too many failed logins         | `900` |

---

## Security notes

**Posture.** The API is public and **read-only** for site visitors
(`allow_methods=["GET"]`, `allow_credentials=False`, CORS restricted to an
allowlist). The trading features add two **public write** endpoints —
`POST /api/wallet` and `POST /api/trade` — which run on a simulated-wallet
ledger (no real funds unless payments are configured) and are gated by the
per-IP rate limiter. The payments endpoints (`POST /api/payments/deposits`,
`POST /api/payments/withdrawals`, `GET /api/payments/{id}`) move **real money
in MWK** and require `KETSA_WANDE_TOKEN`; without it they respond `503` so the
site degrades to play-money mode. Payment state is guarded: deposits are
credited idempotently against the payment record and failed withdrawals are
refunded, so restarting or double-polling cannot double-credit funds. Wallet
balances and the payment ledger are persisted in the storage backend (memory
in dev, Supabase in production). **Content writes** live only under
`/api/admin/*` and are protected by a bearer token obtained from
`POST /api/admin/login` with
`KETSA_ADMIN_PASSWORD` (tokens last 12h with a sliding window). Admin
endpoints are **not** covered by the CORS allowlist restriction in the same
way as reads, but they require the token on every request. All dynamic content
flows through React's escaping; a codebase grep found **no**
`dangerouslySetInnerHTML`, `eval`, or raw-HTML sinks in app code.

**Admin password.** `KETSA_ADMIN_PASSWORD` is the only key to the whole site.
It is read from the environment (does **not** fall back to a committed secret),
defaults to `ketsa-admin` for local dev, and **must** be set to a strong,
unique value in production. If set from the `/api/admin/password` endpoint the
new password is hashed (PBKDF2-HMAC-SHA256) and stored in the backend, taking
precedence over the environment value. Tokens are held in memory (no
persistence), so a backend restart revokes all sessions.

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
  `KETSA_ADMIN_PASSWORD` to a strong value. For persistence across redeploys
  set `KETSA_DB_BACKEND=supabase` with `SUPABASE_URL` +
  `SUPABASE_SERVICE_ROLE_KEY` (run `backend/db/schema.sql` once in the
  Supabase SQL editor).
  To enable real-money payments, inject `KETSA_WANDE_TOKEN` via your host's
  secret manager (never in code) — and keep `KETSA_DB_BACKEND=supabase` so
  funded balances and the payment ledger persist.
- **All-in-one** — use `docker compose up --build` behind a TLS proxy.

See `DEPLOY.md` for the full admin + persistent-storage walkthrough.

---

## License

© 2026 Ketsa. All rights reserved.
