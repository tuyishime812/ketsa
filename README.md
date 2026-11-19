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
│   │   ├── admin/           Admin login + dashboard (sidebar, per-section editors)
│   │   └── api/             Runtime /api/* proxy to the backend (browser calls)
│   ├── components/          Public UI sections (Hero, Markets, Dashboard, ...)
│   │   └── admin/           Admin editors (Markets, Hero, Ticker, Watch, ...)
│   └── lib/                 API client, types, utils
├── Dockerfile.backend
├── Dockerfile.frontend
└── docker-compose.yml
```

### Data flow

1. The Next.js page (`app/page.tsx`) is a **server component**; on each request
   it calls the backend `GET /api/home` via `lib/api.ts`.
2. There is **no bundled demo/fallback dataset**. If the API is unreachable the
   page catches the fetch error and renders `components/DataUnavailable.tsx`
   ("Temporarily unavailable"); the reason is logged server-side only and never
   reaches the browser. `app/error.tsx` backs that up for anything unexpected.
   This is deliberate: every figure on the site is presented to the user as a
   real price, so a placeholder number rendering as if it were live market data
   is worse than a visible error.
3. Browser-side calls — auth, admin, wallet, trades, payments and
   notifications — hit same-origin `/api/*`, which is served by the **runtime
   catch-all proxy** `app/api/[...path]/route.ts`. It forwards to
   `KETSA_BACKEND_URL`, read at **request** time, so no build-time backend URL
   is baked in and the browser only ever talks to the Next.js origin.

### Storage

The backend's data layer (`app/storage.py`) is pluggable and selected with
`KETSA_DB_BACKEND`:

- **`memory` (default)** — a fresh, seed-data-filled store in each process. Zero
  setup, ideal for local dev and previews; edits are lost on restart.
- **`supabase` (production)** — persists every market, watch/ticker row,
  dashboard series, stats, proof, the editable site settings, **wallet
  balances + payment ledger**, **user accounts**, the **per-wallet
  notification feed**, and the **append-only audit log** in Supabase Postgres
  (via the `supabase` Python SDK / PostgREST), so admin edits survive restarts
  and redeploys. Requires a Supabase project: set `SUPABASE_URL` +
  `SUPABASE_SERVICE_ROLE_KEY` and run `backend/db/schema.sql` once in the SQL
  editor.

The schema enables **Row Level Security** on every table, so the public
anon/publishable key can read and write nothing while the backend's
service-role key (which bypasses RLS) keeps full access.

**Where to put the values.** For local dev the backend loads `backend/.env`
(gitignored) at startup — that is the file to edit. The repo-root `.env` is a
documented mirror that nothing reads, and Next.js reads `frontend/.env.local`.
Real process env vars always win over the file, so a host's secret manager
takes precedence in production. The test suite pins the in-process `memory`
store (`backend/tests/conftest.py`), so `pytest` can never touch a live project.

The admin "reset content" endpoint re-seeds both backends to the original data
(preserving any stored admin password). Wallet balances and payment records are
**never** wiped by a content reset.

---

## Local development

> **One command (recommended).** From the repo root, `npm run dev` starts the
> FastAPI backend (port 8000) and the Next.js frontend (port 3000) together,
> so the site runs on the live demo data served by the API — no need to start
> two terminals. Ctrl+C stops both.
>
> **If either port is already taken** (another project, a stray process), move
> them — the launcher pins everything downstream, so nothing else needs editing:
>
> ```bash
> KETSA_API_PORT=8001 KETSA_WEB_PORT=3001 npm run dev     # macOS/Linux
> $env:KETSA_API_PORT=8001; $env:KETSA_WEB_PORT=3001; npm run dev   # PowerShell
> ```
>
> `KETSA_API_PORT` and `KETSA_WEB_PORT` feed the `/api/*` proxy, the
> WebSocket origin, and the backend's public/frontend origin settings used by
> the dev launcher, so nothing else needs editing when you move ports.

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

Open `http://localhost:3000`. The `/api/*` proxy talks to the backend on
`127.0.0.1:8000` by default (override with `KETSA_BACKEND_URL`, or use the
one-command launcher above if the ports are taken).

Note that only `NEXT_PUBLIC_*` variables are inlined into the client bundle.
`lib/api.ts` reads `KETSA_BACKEND_URL` for **server-side** fetches, which is
correct — the same-origin `AUTH_BASE = '/api/auth'` proxy carries every auth
and social-login call, so those never depend on a bundled backend URL. The
WebSocket origin (`lib/push.ts`, `components/market/MarketFeed.tsx`) does read
`NEXT_PUBLIC_KETSA_BACKEND_URL` in the browser, so that one is set for both
services by the launcher.

### 3. Admin panel

With both services running, log in at **`http://localhost:3000/admin`**:

- **Staff accounts (recommended).** Add people under **Staff**, then use
  **Set-password link** to email them a single-use link to
  `/admin/set-password`; they sign in with their email and password. Roles are
  enforced by the API — a support agent can read, a marketing editor can write
  content, and `owner` is the highest staff role — not merely hidden in the UI.
  Links expire (`KETSA_STAFF_INVITE_TTL_SECONDS`, default 24h) and can only be
  used once. If email delivery is not configured (`KETSA_EMAIL_DELIVERY=log`),
  bootstrap or recover an account from `backend/` with
  `python scripts/set_staff_password.py --email … --role owner` (it prompts for
  the password and stores only the PBKDF2 hash).
- **Break-glass owner login.** The **Owner** tab on `/admin` accepts
  `KETSA_ADMIN_PASSWORD`: the shared super-user path used to bootstrap the first
  staff account and to recover if staff credentials are lost. Keep it strong and
  unique (the local dev default is a throwaway); it is the only session allowed
  to change the master password or the security configuration.
- The dashboard has a sidebar with editors for **Markets, Hero, Ticker,
  Watch, Dashboard, Content, Users, Withdrawals, Staff, Broadcast, Settings**, and
  **Manage** (hero/CTA copy, steps, footer, section headings). The **Users**
  tab lists every account with live wallet equity and lets you reset a user's
  password (revokes their sessions) or delete the account entirely. The
  **Withdrawals** tab lets authorized operators review, approve, or reject
  pending payout requests.
- **Settings tab.** Operational controls that used to be env-only are editable
  here, live, without a restart:
  - **Payments** — deposit/withdrawal on-off switches and the per-transaction
    caps plus the daily withdrawal limit.
  - **Security** — the admin-password change form and the login brute-force
    lockout (max failures, lockout window).
  - **Staff roles** — the role allowlist used by the Staff directory and shown
    on the public team page.
  - **Market resolution** — a master switch and an optional guard that refuses
    to settle a market before its published `end_date`.
  These are stored separately from site content and are **never** exposed by the
  public API (`/api/home` whitelists only the content sections).
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

- **Simulated wallet.** Every visitor can create a play wallet (stored in
  `localStorage`) to explore the order books — but wallets **mint at zero**:
  no free-money seed. Real funds come from deposits.
- **Accounts.** Optional email **or phone** accounts (`/api/auth/register`)
  let you keep a name and identifier (email address or Malawian mobile number,
  e.g. `0991 234 567`) on a wallet. The wallet's **equity and positions live on
  the storage backend** and your `Authorization: Bearer` token (30-day sliding)
  locks the account to its own wallet — account-owned wallets return `401`
  without your token and `403` to any other account (deposits, withdrawals,
  ledger reads and trading are all account-scoped). Failed logins are throttled
  per identifier (`KETSA_AUTH_MAX_FAILURES` / `KETSA_AUTH_LOCKOUT_SECONDS`); you
  can change your password from the Portfolio ("Account" card), which revokes
  all other sessions and issues a fresh token.
  - **Money movement requires an account.** Deposits and withdrawals are only
    accepted for the authenticated account's own wallet, with per-transaction
    and daily caps (`KETSA_MAX_DEPOSIT_MWK`, `KETSA_MAX_WITHDRAWAL_MWK`,
    `KETSA_DAILY_WITHDRAWAL_LIMIT_MWK`). A withdrawal can only draw on
    **real money you actually deposited** — the wallet view reports this as
    `withdrawable`, and it is the ceiling on any payout. Play balance (a legacy
    free seed) and trading winnings are spendable on markets but are never
    cashable out, so the house can never be asked to pay out funds it did not
    receive.
  - **Email signups are immediate.** An email registration creates the account
    (and its wallet) straight away — there is no email-verification step, so an
    address is not proven to belong to the registrant (registration only checks
    it is not already taken). Resend powers **forgot-password**: enter the
    account email, enter the emailed code plus a new password ("Resend code"
    re-sends it, subject to the same cooldown), and all existing sessions are
    revoked. Phone-only accounts can't self-reset yet (no SMS provider) — an
    admin resets those from the dashboard. Without `KETSA_RESEND_API_KEY` the
    reset/sign-in flows still respond, but no mail goes out (codes land in the
    server log for local testing).
  - **Passwordless sign-in by email code.** The login modal also offers
    "Sign in with a code instead of a password": enter the account email and
    Resend delivers a 6-digit code ("Resend code" re-sends it, subject to the
    same cooldown). This is *additive* — password login is unchanged and
    phone-only accounts still sign in with a password, since this path needs
    an inbox. `POST /api/auth/login/code` answers `{"ok": true}` for **every**
    input — unknown address, phone number, malformed value, or a suppressed
    resend — so it cannot be used to discover which addresses are registered.
    Because the reply is deliberately uninformative, the UI shows the code
    step either way; that's the same trade-off `forgot-password` already makes.
    Codes are bound to one account, stored only as a SHA-256 digest, burned on
    use, attempt-capped and TTL'd by the same OTP engine as password reset.
  - **Broadcast (admin).** Admin → Broadcast emails one announcement to every
    account that has an email address (phone-only accounts are skipped). The
    send runs as a background job — `POST /api/admin/broadcast` returns a
    `job_id` immediately and `GET /api/admin/broadcast/<job_id>` reports
    progress — because a per-recipient HTTPS round trip takes far longer than
    an HTTP request may wait. Guards: admin token required, one job at a time,
    recipients de-duplicated and capped (`BROADCAST_MAX_RECIPIENTS`), one
    message per recipient (never a shared To/CC/Bcc, which would disclose the
    user list), and the admin's subject/body is HTML-escaped into the mail
    template so admin copy renders as text rather than as markup. There is no
    unsubscribe, so reserve it for genuinely important announcements.
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
  and withdrawal requests via PayChangu (paid out after administrator approval).
- **Live updates.** A WebSocket feed (`ws://…/api/ws`) streams market ticks,
  fills, **resolutions** and **leaderboard changes** to all open pages; clients
  can subscribe a wallet on the same socket to receive that wallet's private
  notification events. **Subscribing a wallet is authorized**, exactly like
  the HTTP notification endpoints: an account-owned wallet requires the
  account's bearer token in the `{"type":"sub","wallet_id":…,"token":…}` frame
  and is otherwise refused with a `sub_error` frame. The public market feed
  needs no token. Concurrent sockets are capped by
  `KETSA_WS_MAX_CONNECTIONS`. Order books and the trade tape refresh every few
  seconds as a fallback.
- **Persistence.** Today the engine keeps books and the trade tape in memory,
  but **wallets are persisted** through the storage backend — a funded balance
  survives a backend restart (use `KETSA_DB_BACKEND=supabase` in production
  when real money is involved).
- **Payments (PayChangu — MWK).** With `PAYCHANGU_SECRET_KEY` configured, the
  portfolio lets users top up their balance with real money via Airtel Money /
  TNM Mpamba and request payouts back to mobile money. Deposits settle through
  a signed webhook, status polling, or a background reconciler and are credited
  exactly once (idempotent — never double-credited). Withdrawal requests debit
  and reserve funds immediately, then wait for administrator approval before a
  payout is initiated; approved payouts settle through the same verification
  path, rejected withdrawals are refunded automatically, and failed payouts are
  refunded automatically. Without a secret key the payment endpoints return 503
  and the site runs purely on play money.

Note: when the backend is **not** reachable from the browser at the default
`127.0.0.1:8000` (e.g. a Vercel frontend + hosted backend), set
`NEXT_PUBLIC_KETSA_BACKEND_URL` so the WebSocket feed knows where to connect.
The `/api/*` HTTP calls go through the frontend's runtime proxy regardless.

---

## Tests

```bash
# Backend
cd backend
.venv\Scripts\python.exe -m pytest
# 374 tests: endpoints, models/seed consistency, 404/405, CORS,
# security headers, OpenAPI gating, rate limiting, admin auth + CRUD + user
# management, admin login brute-force throttling, the matching engine
# (wallets, books, execution, WS feed), settlement integrity (idempotent
# replay, crash mid-payout + resume, failed-write rollback, per-wallet payout
# markers, forge rejection), market-delete safety (open positions / in-flight
# settlement), readiness vs. liveness, account auth (register/login,
# sessions, throttling, change password, wallet-binding on writes),
# leaderboard + notifications, PayChangu payments (deposits, withdrawals,
# idempotent crediting, refunds, webhook + reconciler, transaction + daily caps), the
# withdrawable-balance rule (real money vs. play money, legacy seeds),
# WebSocket subscription authorization + connection cap, OTP email delivery
# policy (no-enumeration on
# account-discovery endpoints), passwordless
# email-code sign-in (single-use, account-bound, expiry, per-IP relay
# throttle), admin broadcast (admin-only, one job at a time, dedupe + cap,
# HTML-escaped copy, CRLF-safe subject, progress), market resolution
# (settlement/payout, trading locks, admin endpoint, wallet-scoped WS
# notification routing), trusted-proxy client-IP resolution (signed
# proxy header, CIDR chain, spoof/malformed fallbacks), and the append-only
# audit log (action vocabulary, actor/IP/target capture, no secrets, the
# admin-gated read endpoint, survival across a content reset, and the
# bounded in-memory backend).

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
| `KETSA_PROXY_SECRET`         | both      | Shared secret used by the frontend proxy to HMAC-sign the real client IP (`X-Ketsa-Client-*`), so rate limits and the admin lockout stay per-visitor behind the proxy. Set the **same** value on both services | — (fallback: trusted proxy CIDRs / direct peer) |
| `KETSA_TRUSTED_PROXIES`      | backend   | Comma-separated IPs/CIDRs whose `X-Forwarded-For` is trusted. Only used when `KETSA_PROXY_SECRET` is absent. Never `0.0.0.0/0` | — (direct peer) |
| `KETSA_WRITE_RATE_LIMIT_PER_MIN` | backend | Stricter per-IP budget for write endpoints (wallet mints, trades, payments) | `30` |
| `KETSA_WS_MAX_CONNECTIONS`   | backend   | Concurrent WebSocket client cap (memory guard)       | `2000` |
| `KETSA_MAX_DEPOSIT_MWK`      | backend   | Default max MWK per deposit transaction (admin Settings → Payments can override) | `1000000` |
| `KETSA_MAX_WITHDRAWAL_MWK`   | backend   | Default max MWK per withdrawal transaction (admin-overridable) | `1000000` |
| `KETSA_DAILY_WITHDRAWAL_LIMIT_MWK` | backend | Default max MWK withdrawn per wallet per rolling 24h (admin-overridable) | `3000000` |
| `KETSA_ADMIN_MAX_FAILURES`   | backend   | Default failed admin logins per IP before lockout (admin Settings → Security can override) | `10` |
| `KETSA_ADMIN_LOCKOUT_SECONDS` | backend  | Default admin lockout window after too many failures (admin-overridable) | `900` |
| `KETSA_BACKEND_URL`          | frontend  | Base URL of the FastAPI service (server-side fetch + the runtime `/api/*` proxy in `app/api/[...path]/route.ts`) | `http://127.0.0.1:8000` |
| `NEXT_PUBLIC_KETSA_BACKEND_URL` | frontend | Public backend origin embedded in the client bundle (WebSocket feed) | `http://127.0.0.1:8000` |
| `KETSA_API_PORT`             | dev only  | Port `npm run dev` gives the FastAPI backend | `8000` |
| `KETSA_WEB_PORT`             | dev only  | Port `npm run dev` gives Next.js | `3000` |
| `KETSA_CSP`                  | frontend  | Optional override for the nonce-based CSP emitted by `middleware.ts`. Use `{nonce}` to keep the per-request script nonce | built-in (nonce + `strict-dynamic`) |
| `KETSA_ADMIN_PASSWORD`       | backend   | **Break-glass owner password** for `/admin` (staff sign in with their own email + password) | `ketsa-admin` |
| `KETSA_PUBLIC_URL`           | backend   | Public frontend origin used to build staff set/reset-password links | `http://localhost:3000` |
| `KETSA_STAFF_INVITE_TTL_SECONDS` | backend | Lifetime of a single-use staff set/reset-password link, clamped to 5 minutes – 7 days | `86400` |
| `KETSA_DB_BACKEND`           | backend   | Storage backend: `memory` (default) or `supabase`   | `memory` |
| `SUPABASE_URL`               | backend   | Supabase project URL (Supabase only)                | — |
| `SUPABASE_SERVICE_ROLE_KEY`  | backend   | Supabase secret service-role key (Supabase only)    | — |
| `PAYCHANGU_SECRET_KEY`       | backend   | PayChangu secret API key for MWK deposits/withdrawals (secret; absent ⇒ payments 503) | — (payments off) |
| `PAYCHANGU_WEBHOOK_SECRET`   | backend   | PayChangu webhook signing secret (secret; absent ⇒ webhook 503) | — (webhook off) |
| `PAYCHANGU_BASE_URL`         | backend   | PayChangu API base URL                             | `https://api.paychangu.com` |
| `KETSA_AUTH_MAX_FAILURES`    | backend   | Failed logins per email/phone before a temporary lockout  | `5` |
| `KETSA_AUTH_LOCKOUT_SECONDS` | backend   | Lockout window after too many failed logins         | `900` |
| `KETSA_RESEND_API_KEY`       | backend   | Resend API key — emails password-reset and sign-in OTPs, plus admin broadcasts (absent ⇒ no mail sent; codes logged for dev) | — (email OTP off) |
| `KETSA_RESEND_FROM`          | backend   | "From" address for OTP + broadcast emails; must be on a domain verified in Resend (the default sandbox sender only accepts `delivered@resend.dev`) | `Ketsa <onboarding@resend.dev>` |
| `KETSA_EMAIL_DELIVERY`       | backend   | Transport for OTP/broadcast email: `auto` (Resend when a key is set, else log), `resend` (always send; missing key is a hard 502), or `log` (never send; write the code to the server log — **local dev only**) | `auto` |
| `NEXT_PUBLIC_KETSA_CONTACT_EMAIL` | frontend | Contact address shown on the Terms/Privacy pages | — (generic "via the app" wording) |
| `KETSA_OTP_TTL_SECONDS`      | backend   | One-time code lifetime                                   | `600` |
| `KETSA_OTP_MAX_ATTEMPTS`     | backend   | Wrong entries before a code is burned                     | `5` |
| `KETSA_OTP_RESEND_SECONDS`   | backend   | Cooldown before a new code is emailed to the same address | `60` |
| `KETSA_CODE_REQUEST_MAX`     | backend   | Sign-in code requests allowed per IP per window (stops the endpoint being used as a mail relay) | `5` |
| `KETSA_CODE_REQUEST_WINDOW`  | backend   | That per-IP window, in seconds                            | `900` |

---

## Security notes

**Posture.** The API is public and **read-only** for site visitors
(`allow_methods=["GET"]`, `allow_credentials=False`, CORS restricted to an
allowlist). The trading features add two **public write** endpoints —
`POST /api/wallet` and `POST /api/trade` — which run on a simulated-wallet
ledger (no real funds unless payments are configured) and are gated by the
per-IP rate limiter. The payments endpoints (`POST /api/payments/deposits`,
`POST /api/payments/withdrawals`, `GET /api/payments/{id}`) move **real money
in MWK** and require `PAYCHANGU_SECRET_KEY`; without it they respond `503` so the
site degrades to play-money mode. Payment state is guarded: deposits are
credited idempotently against the payment record and failed withdrawals are
refunded, so restarting or double-polling cannot double-credit funds. Wallet
balances and the payment ledger are persisted in the storage backend (memory
in dev, Supabase in production). **Content writes** live only under
`/api/admin/*` and are protected by a bearer token obtained from
`POST /api/admin/login` — either a per-staff email + password or the break-glass
`KETSA_ADMIN_PASSWORD` (tokens last 12h with a sliding window, and staff
sessions are re-checked against the live role/active record on every request).
Admin endpoints are **not** covered by the CORS allowlist restriction in the
same way as reads, but they require the token on every request and each route
declares the capability it needs. All dynamic content flows through React's
escaping; a codebase grep found **no** `dangerouslySetInnerHTML`, `eval`, or
raw-HTML sinks in app code.

**Staff credentials and the owner password.** Staff cannot be created with a
password by an admin: the account receives a single-use, expiring link, and
only the SHA-256 digest of its token is stored. The link is emailed to the
address on the staff record (the server never returns it in an API response),
and the set-password endpoint burns it on first use. Password hashes and invite
digests never leave the backend, and the dev email-log transport redacts the
token. `KETSA_ADMIN_PASSWORD` remains the break-glass super-user: it is read
from the environment (does **not** fall back to a committed secret), defaults to
`ketsa-admin` for local dev, and **must** be set to a strong, unique value in
production. If changed from the `/api/admin/password` endpoint the new password
is hashed (PBKDF2-HMAC-SHA256) and stored in the backend, taking precedence over
the environment value; only a live master session may do this. Token **digests**
live in the shared auth store (memory in dev, Supabase in production), so a
restart does not log anyone out; a password change or account deactivation
revokes the relevant sessions immediately.

The browser never receives that bearer token in JavaScript. The runtime `/api`
proxy (`frontend/app/api/[...path]/route.ts`) exchanges it for an
`HttpOnly; SameSite=Strict` cookie scoped to `/api/admin`, strips it from the
login response body, and re-attaches it as `Authorization` on subsequent admin
calls. Cookie-authenticated writes are also Origin / `Sec-Fetch-Site` checked,
and the cookie is cleared on logout, 401 or 403. An XSS bug can still act
inside the live session, but it can no longer read or exfiltrate the admin
credential.

`POST /api/admin/login` is **brute-force throttled per client IP**
(`KETSA_ADMIN_MAX_FAILURES`, default 10 failures →
`KETSA_ADMIN_LOCKOUT_SECONDS`, default 900s lockout, cleared on success).
This matters more than the account throttle: the admin password can delete
accounts, reset any user's password, and resolve markets — which settles real
money — so unlimited guessing is not an acceptable posture. PBKDF2 at 100k
iterations makes each guess expensive but does not bound how many are
attempted.

**Audit log.** Every privileged and money-moving action is written to an
**append-only** log (see `SECURITY.md` → "Privileged-action audit log"). Admin
login (ok/failed/locked-out), logout, password change, content reset, config
changes, market create/update/**resolve** (with payout totals), user
password-reset/delete, staff operations, broadcast starts and user-facing
password changes each record an actor id, client IP, target and a small
metadata blob — never a password, OTP code or token. The log is never cleared
by a content reset, and `GET /api/admin/audit` (admin-gated) reads it
newest-first. In Supabase the `ketsa_audit` table is insert/read only under RLS.

**Single-replica requirement.** Run **exactly one** backend process while real
money is in play. The engine's order books and trade tape live in memory, and
the lock that serializes every balance mutation (trades, deposit credits,
withdrawal debits and refunds, settlement payouts) is an `asyncio.Lock` — it
serializes *within one process only*. Running `uvicorn --workers N`, or two
replicas behind a load balancer, gives each process its own divergent books
and its own view of the same persisted balance, so the same funds can be spent
twice and the per-transaction/daily MWK caps multiply by the replica count.
The startup guard (`backend/app/replica.py`) detects common worker hints
(`WEB_CONCURRENCY`, `UVICORN_WORKERS`, `GUNICORN_WORKERS`, `KETSA_WORKERS`,
`KETSA_REPLICAS`) and **refuses to start** in a multi-process configuration
unless `KETSA_ALLOW_MULTI_WORKER=1` is set or Postgres row locking is active.
For cross-process safety set `KETSA_DB_URL` to a Postgres connection string and
install `psycopg[binary]`; deposit/withdrawal and refund balance mutations then
use `SELECT ... FOR UPDATE` inside a transaction (`backend/app/dblock.py`).
The trade path still requires a single process until fully migrated.
**Never** set `KETSA_ALLOW_MULTI_WORKER=1` with real money unless every wallet
mutation is serialized in the database.

**HTTP security headers (both services).**
- `Content-Security-Policy`: emitted per request by `frontend/middleware.ts`
  with a fresh 128-bit nonce. `script-src 'self' 'nonce-…' 'strict-dynamic'`
  (plus `'unsafe-eval'` in dev only) — **no `'unsafe-inline'` for scripts**.
  `style-src 'unsafe-inline'` remains because React uses inline `style`
  attributes. `frame-ancestors 'none'`, `object-src 'none'`. `KETSA_CSP` can
  override the policy; include `{nonce}` to keep the nonce.
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Cross-Origin-Opener-Policy: same-origin`,
  `Cross-Origin-Resource-Policy: same-origin`,
  `X-Permitted-Cross-Domain-Policies: none`, `Referrer-Policy`,
  `Permissions-Policy`.

**Client-IP trust (rate limits + admin lockout).** The security controls key on
the caller's IP, but browser traffic reaches the backend through the Next.js
runtime proxy. Reading the transport peer there would collapse every visitor
into one bucket: one caller could exhaust the shared write budget, and anyone
could trip the admin lockout and deny the site owner access to `/admin`. Set
the **same** `KETSA_PROXY_SECRET` on the frontend and backend; the proxy then
HMAC-signs the real client IP into `X-Ketsa-Client-*` (with a 5-minute
timestamp window) and the backend verifies it before using it. Alternative:
`KETSA_TRUSTED_PROXIES` lists IPs/CIDRs whose `X-Forwarded-For` is trusted
(rightmost untrusted hop wins, so a caller-prepended spoof is discarded). With
neither configured, the direct peer is used — the safe default for a locally
exposed backend. `backend/app/netutil.py` holds the resolver and
`backend/tests/test_netutil.py` pins the contract.

**Health vs. readiness.** `GET /api/health` is a **liveness** probe: it answers
`200` while the process is running, and deliberately keeps doing so during a
brief storage outage (startup tolerates a transient Supabase/DNS failure so a
blip cannot crash-loop the service). `GET /api/ready` is the **readiness**
probe: it performs one trivial storage read and returns `503` when the backend
is unreachable, so an orchestrator stops routing traffic to a container that
would render "temporarily unavailable" for every page. Point PaaS/Docker health
checks at `/api/ready` (the backend image's `HEALTHCHECK` and `docker-compose.yml`
already do).

**OpenAPI docs are off by default** (`KETSA_EXPOSE_DOCS=0`) to avoid leaking
the API schema publicly. Turn them on only for debugging.

**Rate limiting.** A per-instance in-memory fixed-window limiter (default 120
req/min/IP) returns `429` past the limit. Write endpoints (wallet mints,
trades, deposits, withdrawals) additionally get a stricter per-IP budget
(`KETSA_WRITE_RATE_LIMIT_PER_MIN`, default 30). Neither is a substitute for a
distributed limiter when scaling horizontally — put a shared limiter (e.g.
Caddy rate limit / NGINX) in front for production. See
**Single-replica requirement** above for why the balance-mutation lock needs
the same treatment.

**Withdrawal ceiling (real vs. play money).** Every wallet tracks two pools:
`balance` (spendable on markets) and `withdrawable` (real money that actually
arrived through PayChangu, plus refunds). Only the second can be paid out. This
is what stops a wallet persisted under the old free-money seed — or a trader
running up winnings on house money — from cashing out funds the house never
received. Wallets persisted before this field existed read `withdrawable` as
`0.0`, so any legacy seed automatically becomes play-only with no data
migration.

**Storage lookups.** The account lookup that backs *every* authenticated
request (resolving the caller by wallet id) uses a PostgREST
`value->>wallet_id=eq.…` filter, not a full-table read, so
`schema.sql`'s expression indexes are actually used. `schema.sql` now creates
`ketsa_users_wallet_id_idx` for that path and makes the `phone` index
**unique** (a plain index could not express the uniqueness that application
code assumed, so a concurrent-registration race could slip past it). Re-run
`schema.sql` once — it is idempotent and changes no data.

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
  the hosted API. The API is **required** at runtime: every page fetches live
  data and renders `components/DataUnavailable.tsx` if it cannot be reached, so
  a missing or wrong `KETSA_BACKEND_URL` shows the "temporarily unavailable"
  page rather than the site.
- **Backend** — Railway/Render/Fly: run `uvicorn app.main:app`, expose `8000`,
  set `KETSA_ALLOWED_ORIGINS` to the real frontend origin and
  `KETSA_ADMIN_PASSWORD` to a strong value. For persistence across redeploys
  set `KETSA_DB_BACKEND=supabase` with `SUPABASE_URL` +
  `SUPABASE_SERVICE_ROLE_KEY` (run `backend/db/schema.sql` once in the
  Supabase SQL editor).
  To enable real-money payments, inject `PAYCHANGU_SECRET_KEY` (and
  `PAYCHANGU_WEBHOOK_SECRET`) via your host's secret manager (never in code) —
  and keep `KETSA_DB_BACKEND=supabase` so funded balances and the payment
  ledger persist.
- **All-in-one** — use `docker compose up --build` behind a TLS proxy.

See `DEPLOY.md` for the full admin + persistent-storage walkthrough.

---

## License

© 2026 Ketsa. All rights reserved.
