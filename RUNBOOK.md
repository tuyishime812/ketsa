# Ketsa — production redeploy runbook

Operational checklist to bring the **hosted** site in line with `main`. This is
the release procedure, not the full hosting walkthrough — for "where do these
values go", see [`DEPLOY.md`](./DEPLOY.md).

Run it top to bottom. The gates marked **GO / NO-GO** are launch blockers; do not
skip past a NO-GO.

---

## Why this runbook exists

The live site is **stale** and does not match the repository. As of the last
audit, `https://ketsa.vercel.app` served a build from **~2026-08-30** that
predates the runtime `/api` proxy (`fix(api): proxy /api/* at runtime…`). It
*looks* live because it renders bundled demo data, but:

| Probe | Live result | Correct result |
|-------|-------------|----------------|
| `GET /` footer | "Demo using bundled data — start the FastAPI backend to go live" (string deleted from source) | live market data, no "bundled" copy |
| `GET /robots.txt` | `Host: http://localhost:3000` | your real frontend origin |
| `GET /sitemap.xml` | `<loc>http://localhost:3000</loc>` | your real frontend origin |
| `GET /api/health` | **404** (route absent) | `{"status":"ok"}` |

A **404 on `/api/health`** means the catch-all proxy
(`frontend/app/api/[...path]/route.ts`) is **not deployed**. Every browser-side
call — `/api/auth/*`, `/api/admin/*`, wallet, trades, payments, notifications —
therefore 404s in production. **Login, registration and all money paths are
broken on the deployed URL right now.**

The goal of this runbook: deploy the current `main` with correct configuration
so the hardened code is what is actually exposed.

---

## Preconditions

- [ ] Push access to the repo (`origin` = `github.com/tuyishime812/ketsa`).
- [ ] Admin access to the **Vercel** project `ketsa`.
- [ ] Admin access to the **backend host** (Railway / Render / Fly / VPS).
- [ ] Access to the **Supabase** project (`SUPABASE_URL` + service-role key).
- [ ] Access to the **Resend** dashboard and the DNS host for the sending domain.
- [ ] Access to the **Auth0** tenant and the **wandePay** account.
- [ ] Confirm the backend will run as **exactly one** replica/worker (see
      `DEPLOY.md` → "Run exactly ONE backend process while real money is in play").

Record the real origins you will use everywhere below:

```text
FRONTEND_ORIGIN = https://<your-app-domain>        # e.g. https://ketsa.vercel.app
BACKEND_ORIGIN  = https://<your-backend-domain>    # e.g. https://ketsa-api.onrender.com
```

---

## Step −1 — Rotate the leaked credentials (**BLOCKER, do first**)

`backend/.env` with **live** secrets (wandePay token, Supabase service-role key,
Resend key, Auth0 client secret, admin password) was committed in `de191c6` and
pushed to `origin/main`. The file is now untracked, but the values are still in
history and must be treated as publicly known.

**Do not proceed past this gate until every one of those credentials has been
rotated at the source and the file purged from history.** Full procedure and the
audit checklist: [`SECURITY.md`](./SECURITY.md) → "ACTIVE INCIDENT".

---

## Step 0 — Snapshot (2 min)

Before changing anything, record the current live state so you can prove the
improvement and have a rollback reference.

```bash
curl -s  "$FRONTEND_ORIGIN/robots.txt"
curl -s  "$FRONTEND_ORIGIN/sitemap.xml"
curl -si "$FRONTEND_ORIGIN/api/health" | head -1     # expect 404 today
curl -si "$BACKEND_ORIGIN/api/health"  | head -1     # backend may be fine already
```

In the host dashboard, copy the **current env vars** and the currently deployed
**commit SHA** (Vercel → Deployment → Source, or the host's release log) to a
scratch file. That SHA is your rollback target.

---

## Step 1 — Ship the current `main`

Two commits are in scope:

- `10f6c23` — the runtime `/api` proxy (the fix the stale deploy is missing).
- `5b04fe3` — docs/comments aligned to that proxy (no behavior change).

```bash
git switch main
git fetch origin
git status            # expect: clean, nothing to commit
git log --oneline origin/main..HEAD   # list any unpushed commits
git push origin main
```

**GO / NO-GO:** CI must be green on `main` before you deploy. The workflows are
`backend` (pytest) and `frontend` (lint + build). If the repo is private, check
the Actions tab in the browser.

> Note: pushing does **not** by itself fix production if the host is not wired to
> auto-deploy `main`. Steps 2–6 are what actually move production.

---

## Step 2 — Backend host environment

Set these on the backend service, then confirm each is **non-empty** in the
host's env UI. Full descriptions are in `.env.production.example`.

| Var | Required? | Value |
|-----|-----------|-------|
| `KETSA_ALLOWED_ORIGINS` | yes | `$FRONTEND_ORIGIN` (comma-separate extras; no trailing slash) |
| `KETSA_ADMIN_PASSWORD` | **yes** | strong, unique — the only key to `/admin` |
| `KETSA_EXPOSE_DOCS` | yes | `0` |
| `KETSA_DB_BACKEND` | **yes for persistence** | `supabase` |
| `SUPABASE_URL` | if supabase | `https://<ref>.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | if supabase | service-role secret (secret manager only) |
| `KETSA_WANDE_TOKEN` | if payments | wandePay token (secret manager only) |
| `KETSA_WANDE_BASE_URL` | if payments | `https://apiv1.wandepay.site/api/` |
| `KETSA_RESEND_API_KEY` | **yes for email accounts** | Resend key (secret manager only) |
| `KETSA_RESEND_FROM` | **yes for email accounts** | verified-domain sender — see Step 5 |
| `KETSA_EMAIL_DELIVERY` | if sending email | `resend` (the default `auto` also sends when a key is set; never leave `log` in production) |
| `KETSA_PUBLIC_BASE_URL` | if social login | `$BACKEND_ORIGIN` (**public** origin, not a container hostname) |
| `KETSA_FRONTEND_URL` | if social login | `$FRONTEND_ORIGIN` |
| `KETSA_AUTH0_DOMAIN` | if social login | `https://<tenant>.auth0.com` host |
| `KETSA_AUTH0_CLIENT_ID` | if social login | Regular Web Application client id |
| `KETSA_AUTH0_CLIENT_SECRET` | if social login | client secret (secret manager only) |
| `KETSA_AUTH0_CONNECTION` | if social login | `google-oauth2` (must match the enabled connection) |

Optional tuning (defaults are fine): money caps `KETSA_MAX_DEPOSIT_MWK` /
`KETSA_MAX_WITHDRAWAL_MWK` / `KETSA_DAILY_WITHDRAWAL_LIMIT_MWK`; throttles
`KETSA_RATE_LIMIT_PER_MIN` / `KETSA_WRITE_RATE_LIMIT_PER_MIN` /
`KETSA_ADMIN_MAX_FAILURES` / `KETSA_ADMIN_LOCKOUT_SECONDS`; WS cap
`KETSA_WS_MAX_CONNECTIONS`; OTP tuning `KETSA_OTP_*`.

**GO / NO-GO:** if you are taking real money, `KETSA_DB_BACKEND=supabase` **and**
`KETSA_WANDE_TOKEN` must both be set, and the backend must run one replica.

---

## Step 3 — Frontend (Vercel) environment

Vercel → Project `ketsa` → Settings → Environment Variables. Set for **Production**
(add Preview too if you use preview URLs). These are **build-time** and require a
redeploy to take effect.

| Var | Value |
|-----|-------|
| `KETSA_BACKEND_URL` | `$BACKEND_ORIGIN` (runtime; server components + the `/api` proxy) |
| `NEXT_PUBLIC_KETSA_BACKEND_URL` | `$BACKEND_ORIGIN` (build-time; embedded for the WebSocket feed) |
| `KETSA_SITE_URL` | `$FRONTEND_ORIGIN` (build-time; `robots.txt` / `sitemap.xml` / Open Graph) |
| `KETSA_CSP` | optional override |

**Why the build-time ones matter here:** the stale live build emitted
`localhost` in `robots.txt`/`sitemap.xml` precisely because `KETSA_SITE_URL` was
unset when it built. Set it **before** the redeploy.

> `KETSA_BACKEND_URL` is read at request time by the proxy, but Vercel still needs
> the variable present in the environment that runs the function. Set it in
> Production (and Preview if used).

---

## Step 4 — Supabase schema (re-run, idempotent)

The schema gained an expression index (`ketsa_users_wallet_id_idx`) and made the
`phone` and `auth0_sub` indexes **unique**. Re-run it once so the uniqueness
those columns claim is actually enforced.

Supabase → SQL editor → run, **in order**, one file per query:

1. `backend/db/schema.sql` — tables + RLS (required for `KETSA_DB_BACKEND=supabase`)
2. `backend/db/realtime.sql` — optional Supabase Realtime publication (skip unless used)

Both are idempotent and touch no data. Verify:

```sql
select indexname from pg_indexes where tablename = 'ketsa_users';
-- expect: ketsa_users_wallet_id_idx, and unique indexes on phone + auth0_sub
```

---

## Step 5 — Resend sending domain — **GO / NO-GO for email accounts**

The current local value is `KETSA_RESEND_FROM=Ketsa <onboarding@resend.dev>`.
**That is Resend's sandbox sender and only delivers to Resend's own test inbox.**
With it, every code-bearing flow fails silently for real users:

- signup verification (email registration stays pending forever),
- forgot-password reset codes,
- passwordless sign-in codes,
- admin → Broadcast.

**To clear the gate:**

1. Add and **verify a sending domain** in Resend (Resend → Domains).
2. Add the SPF/DKIM DNS records at your DNS host; wait for "Verified".
3. Set `KETSA_RESEND_FROM=Ketsa <no-reply@yourdomain.com>` (on your verified domain)
   in the backend host's env.

**If you are NOT shipping email accounts yet:** you may launch with the sandbox
sender, but keep email registration effectively off (or accept that email users
never receive codes). Phone-only accounts do not need Resend.

> Phone-only accounts cannot self-reset (no SMS provider) — reset them from the
> admin panel. That is a known, documented gap, not a regression.

> **Local dev vs production.** `backend/.env` sets `KETSA_EMAIL_DELIVERY=log`,
> so locally every OTP is written to the uvicorn log instead of being sent —
> register/verify works for any address with no sending domain. The backend
> prints a startup banner naming the active transport; if it says `log`, or
> warns that the sender is Resend's sandbox, email signup cannot reach real
> users. Production must use `resend` with a verified domain.

---

## Step 5b — Legal pages — **review before launch**

`/terms` and `/privacy` ship with good-faith baseline copy (operator "Ketsa",
no entity/jurisdiction, contact via `NEXT_PUBLIC_KETSA_CONTACT_EMAIL`). Before
launch, have counsel review them for your jurisdiction and set the operator
entity and contact address. They are linked structurally from the site footer,
so they are always reachable.

---

## Step 6 — Deploy (backend first, then frontend)

1. **Backend:** deploy the backend service from `main`. Start command:
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT` — **no `--workers`**.
2. Wait for it to boot, then check it directly:
   ```bash
   curl -s "$BACKEND_ORIGIN/api/health"      # {"status":"ok"}
   curl -s "$BACKEND_ORIGIN/api/home" | head -c 200
   ```
3. **Frontend:** trigger a **Production redeploy** in Vercel *after* the Step 3
   variables are saved (the build-time vars must be present at build). If the
   project is connected to the repo, push already queued it — otherwise use
   "Redeploy".

---

## Step 7 — Verify (fill in, all must pass)

| # | Check | Command / action | Expect |
|---|-------|------------------|--------|
| 1 | Frontend health via proxy | `curl -s "$FRONTEND_ORIGIN/api/health"` | `{"status":"ok"}` (was 404) |
| 2 | Live data, no bundled fallback | open `$FRONTEND_ORIGIN/` | real markets; **no** "bundled data" copy |
| 3 | robots + sitemap on real domain | `curl -s "$FRONTEND_ORIGIN/robots.txt"` | `Host: $FRONTEND_ORIGIN` |
| 4 | Admin login | open `$FRONTEND_ORIGIN/admin` | wrong password rejected; `KETSA_ADMIN_PASSWORD` accepted |
| 5 | Edit persists | change a market/hero, restart backend, reload | edit survives (proves Supabase) |
| 6 | Email signup | register an email account (if Step 5 passed) | code arrives in inbox |
| 7 | Social login | "Continue with Google" (if Auth0 set) | returns to `$FRONTEND_ORIGIN/auth/callback`, logged in |
| 8 | Payments | `/portfolio` → deposit (if wandePay set) | no error; `KETSA_WANDE_TOKEN` set in host, **not** in repo |
| 9 | WS live feed | open a market page, watch the order book | ticks update without refresh |
| 10 | Security headers | devtools → Network → document response | `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` |
| 11 | Proxy path for auth | `curl -si -X POST "$FRONTEND_ORIGIN/api/auth/social/login" \| head -1` | not `404` (route exists; `503` if Auth0 unset) |

---

## Step 8 — Auth0 callback (only if social login is enabled)

The callback URI is **derived**: `${KETSA_PUBLIC_BASE_URL}/api/auth/social/callback`.
In Auth0 → Applications → your app → Settings:

- Allowed Callback URLs: `$BACKEND_ORIGIN/api/auth/social/callback`
- Allowed Logout URLs: `$FRONTEND_ORIGIN`
- Allowed Web Origins: `$FRONTEND_ORIGIN`

Enable the **Google** connection; keep `KETSA_AUTH0_CONNECTION=google-oauth2`
unless you deliberately enable and pin a different one.

---

## Step 9 — Rollback

If a gate fails hard:

1. **Frontend:** Vercel → Deployments → the pre-change deployment (Step 0 SHA) →
   **Promote to Production**.
2. **Backend:** redeploy the previous release on the host.
3. Env-var mistakes usually revert by fixing the value and redeploying — no data
   migration is involved (`schema.sql` changed indexes only, not data).

Rollback is safe for money state: wallet balances and the payment ledger are
append-only/idempotent, and a content "reset" never touches them.

---

## Step 10 — Watch after launch

- **`KETSA_RESEND_FROM` still sandbox?** Re-check within a day; real users
  silently get nothing otherwise.
- **One replica still true?** Autoscaling or a second worker reintroduces the
  double-spend window (per-process `asyncio.Lock`).
- **Dependency advisory** `GHSA-qx2v-qp2m-jg93` (postcss vendored in Next 15.5.x,
  build-time only). Re-check when a stable Next `>= 16.3` or a fixed 15.x patch
  ships; bump then.
- **Shared rate limiting / DB-backed locking** are prerequisites before any
  horizontal scale-out.
