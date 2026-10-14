# Deploying Ketsa

This walks you through putting the Ketsa prediction-market site live:
**frontend → Vercel**, **backend → Railway/Render/Fly**. Everything below is
verified against the codebase's actual data-flow (see "How data gets from
backend → page" at the bottom so you understand *why* the values are set).

Prerequisites: code is on GitHub (`origin/main`), and CI is green.

---

## Step 0 — The backend is required

The frontend has **no bundled demo dataset** — every page fetches live data
from the API and renders `components/DataUnavailable.tsx` ("Temporarily
unavailable") when it can't. Deploy the backend first and set
`KETSA_BACKEND_URL`; deploying the frontend alone will render only the
unavailable page.

---

## Step 1 — Deploy the backend (do this first, so the frontend has a data URL)

Pick one host (Railway, Render, or Fly). All run the same FastAPI app.

1. **Import** the GitHub repo. Set the **Root Directory** to `backend` if the
   platform asks (the repo root contains both `backend/` and `frontend/`; the
   backend lives in `backend/`).
2. **Build/Run command** (start command):
   ```
   uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
   (Swap `$PORT` for `${PORT:-8000}` on some providers; Railway/Render inject
   `PORT` automatically.)
3. **Python version:** the project was developed on 3.14; 3.12+ works. Set it
   in the platform's runtime settings.
4. **Environment variables** (all documented in `.env.production.example`):
   | Var | Value |
   |-----|-------|
   | `KETSA_ALLOWED_ORIGINS` | your real frontend origin → set in Step 2, e.g. `https://ketsa.vercel.app` (comma-separated for extras) |
   | `KETSA_EXPOSE_DOCS` | `0` (keep the public API schema hidden) |
   | `KETSA_RATE_LIMIT_PER_MIN` | `120` (or `0` if the provider's proxy handles throttling) |
   | `KETSA_ADMIN_PASSWORD` | **required** — a strong, unique password for the `/admin` panel (see Step 2b) |
   | `KETSA_DB_BACKEND` | `supabase` if you want admin edits to persist across redeploys (and — required for payments — wallet balances + ledger). Defaults to `memory`, which resets on every restart. |
   | `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | (**Supabase only** — see Step 2b) the project URL and secret service-role key |
   | `KETSA_WANDE_TOKEN` | (**payments** — see Step 2b) wandePay API token for MWK deposits/withdrawals; inject via secret manager, never in code. Absent ⇒ payments `503` |
   | `KETSA_WANDE_BASE_URL` | (**payments**) wandePay API base URL (defaults to `https://apiv1.wandepay.site/api/`) |
5. Deploy → note the **public HTTPS URL** (e.g. `https://ketsa-api.onrender.com`).
   Sanity check: `curl https://<your-backend>/api/health` → `{"status":"ok"}`.

---

## Step 2 — Deploy the frontend (Vercel)

1. **vercel.com → Add New Project → Import** the `ketsa` repo.
2. **Root Directory:** `frontend`.
3. Vercel auto-detects **Next.js** — keep the default build settings.
4. **Environment variables** — add these in the project settings (Vercel → your
   project → Settings → Environment Variables), then **redeploy**:
   - `KETSA_BACKEND_URL` → `https://<your-backend-from-step-1>` (runtime; this
     is what the server component uses to fetch live data).
   - `NEXT_PUBLIC_KETSA_BACKEND_URL` → `https://<your-backend-from-step-1>`
     (**build-time**; embedded in the client bundle so the browser can open the
     live WebSocket market feed at `wss://<your-backend>/api/ws`. Required for
     trading to show live prices when the browser can't reach
     `127.0.0.1:8000`).
   - `KETSA_SITE_URL` → `https://<your-app>.vercel.app` or your custom domain
     (**build-time**; used by `robots.txt`, `sitemap.xml`, Open Graph — set it
     before the final build so the metadata uses the real domain).
   - Optional: `KETSA_CSP` to override the Content-Security-Policy.
5. Deploy → open `https://<your-app>.vercel.app`.

**Verify the data is live:**
- The homepage renders real market cards and the ticker (not the
  "Temporarily unavailable" page from `components/DataUnavailable.tsx`).
- `curl https://<your-app>.vercel.app/api/health` returns ok (the product
  proxy isn't required for data, but confirms routing).

---

## Step 2b — Admin panel and persistent data

The `/admin` dashboard lets site owners edit all content (markets, hero,
ticker, watch, dashboard, footer, CTA/steps/section copy) from the browser
with no code changes. It lives on the **frontend** but talks to the backend's
protected `/api/admin/*` through the same-origin `/api` path.

**Make sure these backend env vars are set (see Step 1), then:**

1. **Persistent storage (do this first).** The backend defaults to an
   in-process **memory** store seeded from the static content: admin edits work,
   but everything resets whenever the backend restarts/redeploys. To keep edits
   permanently, set `KETSA_DB_BACKEND=supabase` and provide
   `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` (Settings → API in the Supabase
   dashboard; keep the key in your host's secret manager — the service role
   bypasses Row Level Security). The backend then persists all
   markets/watch/ticker/dashboard/settings — **plus wallet balances and the
   payment ledger** — in Supabase Postgres; no disk volume needed on your host.
   Note: the "reset content" admin action re-seeds markets/settings only and
   never touches wallets or payment records.
   - Create a free Supabase project (supabase.com), then in the **SQL editor**
     run the checked-in schema **once**: `backend/db/schema.sql`. It creates the
     tables (`ketsa_kv`, `ketsa_wallets`, `ketsa_payments`, `ketsa_users`,
     `ketsa_notifications`, `ketsa_auth`, `ketsa_staff`) and enables Row Level
     Security on all of them, so
     the public anon/publishable key can read and write nothing while the
     service role keeps full access. It is idempotent and never touches existing
     data. The backend seeds the content itself on first boot — no further
     schema setup is required.
   - **Order matters:** run `backend/db/schema.sql` **before**
     `backend/db/realtime.sql`. `realtime.sql` (optional — live browser
     updates via Supabase Realtime: the channel "ketsa_live" for watched-marker
     changes, "ketsa_notify_<wallet>" for notifications) only turns on logical
     replication + publication for the tables from `schema.sql`, so it must
     come second. The default live feed is the backend's in-process
     `/api/ws` + SSE — that path needs **no** SQL at all; `realtime.sql` is
     purely for the Supabase Realtime wiring.
   - **Run order summary (Supabase SQL editor, one file per query):**
     1️⃣ `backend/db/schema.sql` — tables + RLS (required for
     `KETSA_DB_BACKEND=supabase`)
     2️⃣ `backend/db/realtime.sql` — optional live-updates publication
     (skip unless you're wiring Supabase Realtime into the frontend)
     Then set `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` in the backend env.
     > **Local dev:** the backend loads `backend/.env` (gitignored) at startup.
     > The repo-root `.env` is a documented mirror only — nothing reads it.
2. **Set the password.** `KETSA_ADMIN_PASSWORD` must be a strong, unique
   value. It is the only key to the whole site. The backend reads it from the
   environment and **never** falls back to a committed secret. In production it
   does **not** default to `ketsa-admin` — leave it unset only for local dev.
3. **Enable payments (optional).** To let users fund their wallet with real
   money (MWK) and withdraw to mobile money, set **`KETSA_WANDE_TOKEN`** (from
   wandePay) via your host's secret manager — never in code — and
   `KETSA_WANDE_BASE_URL` (defaults to the production API). Keep
   `KETSA_DB_BACKEND=supabase` so funded balances and the payment ledger
   survive restarts. Without the token the payment endpoints return `503` and
   the site runs purely on play money.
4. **Social login via Auth0 — "Continue with Google" (optional).** Set
   `KETSA_AUTH0_DOMAIN`, `KETSA_AUTH0_CLIENT_ID`, `KETSA_AUTH0_CLIENT_SECRET`
   (Auth0 application type **Regular Web Application** — the backend runs the
   whole Authorization Code flow server-side, so no Auth0 SDK ships in the
   browser). Also set `KETSA_PUBLIC_BASE_URL` to the **public** origin of the
   backend — the Auth0 callback URI
   (`https://<backend>/api/auth/social/callback`) must match exactly — and
   `KETSA_FRONTEND_URL` to the frontend origin the browser returns to. In the
   Auth0 dashboard (Applications → Settings):
   - Allowed Callback URLs: `https://<backend>/api/auth/social/callback`
   - Allowed Logout URLs: `https://<frontend>`
   - Allowed Web Origins: `https://<frontend>`
   Then enable the **Google** connection (Authentication → Social → Google)
   for this application. If the Auth0 env vars are absent the button flow
   returns `503` and the modal hides nothing — the site just keeps
   email/password auth.

   > **Only the `google-oauth2` connection can complete a login.** The backend
   > checks that the token's subject starts with `KETSA_AUTH0_CONNECTION`
   > (default `google-oauth2`). This is deliberate: a valid Auth0 signature
   > only proves *some* connection in your tenant signed the token, and
   > `/authorize` does not bind `state` to a connection — so without the
   > check, a token from a second connection (Auth0's built-in database, an
   > enterprise SAML/OIDC connection, a sandbox member added for testing)
   > would be accepted and linked by email to an existing account, wallet and
   > balance included.
   >
   > You do not need to remove other connections from the tenant; they are
   > simply inert here. If you deliberately add a provider, enable it **and**
   > set `KETSA_AUTH0_CONNECTION` to its name.
5. **Transactional email via Resend (recommended).** These flows depend on
   it: **email-OTP signup verification** (an email registration is held
   pending — no account, no seeded wallet — until the user enters the 6-digit
   code), **forgot-password** (reset code emailed to the account's email),
   **passwordless sign-in** (`POST /api/auth/login/code` emails a 6-digit
   sign-in code), and **admin → Broadcast** (one announcement per account that
   has an email). Set `KETSA_RESEND_API_KEY` (from https://resend.com/api-keys)
   and `KETSA_RESEND_FROM` to an address on a domain you've **verified in
   Resend** (Resend's default sandbox domain only delivers to your own inbox).
   Without the key no mail is sent: the API still answers normally but codes
   only land in the server log — fine for local testing, never acceptable in
   production. Optional tuning: `KETSA_OTP_TTL_SECONDS` (default 600),
   `KETSA_OTP_MAX_ATTEMPTS` (default 5), `KETSA_OTP_RESEND_SECONDS`
   (default 60), and `KETSA_CODE_REQUEST_MAX` (default 5) /
   `KETSA_CODE_REQUEST_WINDOW` (default 900s) — the per-IP sign-in-code request
   throttle that keeps `/api/auth/login/code` from becoming an open mail relay.
   Phone-only accounts cannot self-reset (no SMS provider wired) — reset them
   from the admin dashboard.
6. **Log in.** Open `https://<your-frontend>/admin`, enter the password, and
   you'll get the dashboard with a sidebar of editors. Changes save
   immediately and appear on the public site.

> **How the browser reaches the API.** Every browser-side call — auth
> (`/api/auth/*`), admin (`/api/admin/*`), wallet, trades, payments and
> notifications — is same-origin to the frontend and handled by a **runtime
> catch-all proxy** at `app/api/[...path]/route.ts`, which forwards to
> `KETSA_BACKEND_URL` read at **request** time. Because the proxy runs
> server-side and same-origin, the backend's CORS allowlist does not need to
> grant the frontend origin for these calls, and the CSP already permits
> same-origin `/api`. Requests still require the bearer token where applicable.
>
> (This proxy replaces the old `next.config.js` rewrite, which was evaluated at
> **build** time and therefore baked in `http://127.0.0.1:8000` on hosts where
> `KETSA_BACKEND_URL` is present only at runtime — Vercel then answered every
> `/api/*` request with `404 DNS_HOSTNAME_RESOLVED_PRIVATE`, which broke the
> Log in / Create account buttons while the server-rendered page still worked.)

---

## Step 3 — Custom domain (optional)

- **Frontend:** add the domain in Vercel → Project → Settings → Domains.
- **Backend:** point a CNAME/record at the provider's endpoint, or use their
  default subdomain.

---

## Step 4 — Post-deploy checklist

- [ ] GitHub Actions CI is green on `main`.
- [ ] `https://<frontend>` renders live data (not the "Temporarily unavailable"
      page).
- [ ] `https://<frontend>/robots.txt` shows the real domain (confirms
      `KETSA_SITE_URL` was set at build time).
- [ ] `https://<frontend>/sitemap.xml` returns an XML urlset.
- [ ] Backend health check returns `ok`.
- [ ] `https://<frontend>/admin` loads the login page; a wrong password is
      rejected and the correct `KETSA_ADMIN_PASSWORD` logs in.
- [ ] Admin edit persists after a backend restart (i.e. `KETSA_DB_BACKEND=supabase`
      with valid credentials — see Step 2b).
- [ ] (If payments enabled) `/portfolio` shows the Payments panel and creating a
      deposit/withdrawal does not error; `KETSA_WANDE_TOKEN` is set in the host's
      secret manager and **not** committed to the repo.
- [ ] **The backend runs a single replica/worker.** See the warning below — this
      is a correctness requirement, not a scaling preference.
- [ ] (If Supabase) `schema.sql` has been re-run since the `ketsa_users_wallet_id_idx`
      / unique `phone` + `auth0_sub` indexes were added. Verify with
      `select indexname from pg_indexes where tablename = 'ketsa_users';`
- [ ] Headers present in browser devtools on the homepage: `Content-Security-Policy`,
      `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`.

---

## ⚠ Run exactly ONE backend process while real money is in play

This is the single most important operational constraint in this file.

The engine's order books and trade tape are **in-memory**, and every
balance-mutating operation (trades, deposit credits, withdrawal debits and
refunds, resolution settlement payouts) is serialized behind one
`asyncio.Lock`. That lock is **per process**. So with `uvicorn --workers N`, or
two replicas behind a load balancer:

- each process keeps its **own** order books and trade tape, so prices and
  matching diverge between them;
- each process resolves the same persisted wallet balance independently, so
  **the same funds can be spent twice** (classic double-spend);
- the per-transaction and daily MWK caps (`KETSA_MAX_DEPOSIT_MWK`,
  `KETSA_MAX_WITHDRAWAL_LIMIT_MWK`, `KETSA_DAILY_WITHDRAWAL_LIMIT_MWK`) are
  enforced per process, so your real limits are effectively **N×** what you
  configured;
- the in-memory rate limiters are per-instance too, so they multiply the same way.

**Do:** run one instance (`uvicorn app.main:app --port 8000`, no `--workers`).
Put a shared rate limiter in front (Caddy / NGINX / Cloudflare) if you need
edge throttling. Vertical scale first.

**Before scaling out:** move the engine's authoritative state into Postgres and
take row-level locks (`SELECT … FOR UPDATE`) on the wallet row inside the same
transaction that mutates it, and move the limits/rate limiting to shared
storage (Redis). Until that exists, a second replica is a double-spend bug with
extra steps.

---

## How data gets from backend → page (why the values above work)

1. `frontend/app/page.tsx` is a **server component** marked `force-dynamic`.
   On every page request Vercel's server function calls
   `lib/api.ts → fetchHomeData()` → `GET {KETSA_BACKEND_URL}/api/home`.
2. This is a **server-to-server** call — no CORS applies, so the backend only
   needs its own `KETSA_ALLOWED_ORIGINS` set if you ever call it from a browser
   (e.g. debugging). It's set anyway as defense-in-depth.
3. If the backend is down/unreachable the page catches the fetch error and
   renders `components/DataUnavailable.tsx` ("Temporarily unavailable") with a
   retry link. There is no bundled seed data to fall back to by design — a
   placeholder price rendered as if it were live is the failure mode this
   avoids. The upstream error is logged on the server and never sent to the
   browser.

### How `/api` reaches the backend
Server-rendered data (`/api/home`, `/api/markets`, …) is fetched
server-to-server by the server components. Browser-side calls — auth, admin,
wallet, trades, payments and notifications — are handled by the runtime
catch-all proxy `app/api/[...path]/route.ts`, which forwards to the same
`KETSA_BACKEND_URL`, read at request time. The client components (`Markets`,
`Dashboard`, `WatchPanel`) render from the server props and update locally for
the live-price "feel"; the live WebSocket feed connects directly to the backend
origin in `NEXT_PUBLIC_KETSA_BACKEND_URL`.

### Admin writes in production
The `/admin` dashboard posts JSON to same-origin `/api/admin/*`, which the
runtime proxy (above) forwards to `KETSA_BACKEND_URL`. Auth is a bearer token
from `POST /api/admin/login` (password = `KETSA_ADMIN_PASSWORD`), held in
`localStorage`. Writes update the backend's storage (Supabase in production,
memory in dev), so a page refresh (and every subsequent visitor) sees the change.

### Payments are chosen + executed server-side
The **browser never talks to wandePay**. The portfolio panel only submits
intent to the backend (`POST /api/payments/deposits` / `withdrawals`); the
backend calls wandePay's API with the token server-to-server, stores a payment
record, and credits/refunds the wallet only after polling confirms completion.
Deposits are idempotent (a completed record credits exactly once) and failed
withdrawals are refunded automatically.

---

## Alternative: run everything with Docker (no Vercel)

If you prefer a single VPS instead of Vercel + a PaaS:

```bash
docker compose up --build -d
# frontend: http://<host>:3000
# api:      http://<host>:8000
```

Place a TLS-terminating reverse proxy (Caddy/Nginx/Traefik) in front. Set
`KETSA_ALLOWED_ORIGINS`, `KETSA_BACKEND_URL`, and a strong
`KETSA_ADMIN_PASSWORD` in `docker-compose.yml` (or the compose env). For
persistent admin edits set `KETSA_DB_BACKEND=supabase` and supply
`SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` (run `backend/db/schema.sql`
once in the Supabase SQL editor); with the default memory backend, edits reset
on restart. To enable
payments add `KETSA_WANDE_TOKEN` (from a secret store) via the compose env.
Both images run as non-root users.
