# Deploying Ketsa

This walks you through putting the Ketsa prediction-market site live:
**frontend → Vercel**, **backend → Railway/Render/Fly**. Everything below is
verified against the codebase's actual data-flow (see "How data gets from
backend → page" at the bottom so you understand *why* the values are set).

Prerequisites: code is on GitHub (`origin/main`), and CI is green.

---

## Step 0 — Everything is optional, nothing breaks

The frontend **gracefully falls back** to bundled seed data when it can't reach
the backend. So you can deploy the frontend alone and it will still render —
it just won't show "live" data. Add the backend whenever you're ready.

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
   | `KETSA_DB_PATH` | **recommended** — point at a persistent disk/volume path so admin edits survive redeploys (see Step 2b) |
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
   - `KETSA_SITE_URL` → `https://<your-app>.vercel.app` or your custom domain
     (**build-time**; used by `robots.txt`, `sitemap.xml`, Open Graph — set it
     before the final build so the metadata uses the real domain).
   - Optional: `KETSA_CSP` to override the Content-Security-Policy.
5. Deploy → open `https://<your-app>.vercel.app`.

**Verify it's truly live (not fallback):**
- No "Demo using bundled data" badge in the bottom-right corner.
- `curl https://<your-app>.vercel.app/api/health` returns ok (the product
  proxy isn't required for data, but confirms routing).

---

## Step 2b — Admin panel and persistent data

The `/admin` dashboard lets site owners edit all content (markets, hero,
ticker, watch, dashboard, footer, CTA/steps/section copy) from the browser
with no code changes. It lives on the **frontend** but talks to the backend's
protected `/api/admin/*` through the same-origin `/api` path.

**Make sure these backend env vars are set (see Step 1), then:**

1. **Persistent storage (do this first).** `KETSA_DB_PATH` defaults to
   `backend/ketsa.db`, which is wiped on every redeploy on most PaaS unless
   you attach a volume. Add a persistent volume and set
   `KETSA_DB_PATH=/data/ketsa.db` (or similar) so saved edits survive. Without
   this, admin changes are lost whenever the backend restarts/redeploys.
   - **Railway:** add a *Volume* on the service and mount it, then set the path
     to a file inside the mount.
   - **Render:** add a *Persistent Disk*, then set `KETSA_DB_PATH` to a path
     under the disk mount (e.g. `/var/data/ketsa.db`).
   - **Fly.io:** add a *volume* and reference it via the env var.
2. **Set the password.** `KETSA_ADMIN_PASSWORD` must be a strong, unique
   value. It is the only key to the whole site. The backend reads it from the
   environment and **never** falls back to a committed secret. In production it
   does **not** default to `ketsa-admin` — leave it unset only for local dev.
3. **Log in.** Open `https://<your-frontend>/admin`, enter the password, and
   you'll get the dashboard with a sidebar of editors. Changes save
   immediately and appear on the public site.

> **Note on the dev rewrite vs. production.** In local dev, `next.config.js`
> rewrites `/api/*` → the backend so the browser calls it same-origin. In
> **production**, the public page fetches the backend **server-side** directly
> (see "How data gets from backend → page"), so `/admin` uses the frontend's
> own `/api` path which Vercel routes as a serverless function that proxies to
> `KETSA_BACKEND_URL`. Because the admin API is same-origin to the frontend,
> the backend's CORS allowlist does not need to grant the admin origin, and the
> CSP header (`default-src 'self'`) already permits `/api` calls. Admin
> requests still require the bearer token from login.

---

## Step 3 — Custom domain (optional)

- **Frontend:** add the domain in Vercel → Project → Settings → Domains.
- **Backend:** point a CNAME/record at the provider's endpoint, or use their
  default subdomain.

---

## Step 4 — Post-deploy checklist

- [ ] GitHub Actions CI is green on `main`.
- [ ] `https://<frontend>` renders, no fallback badge.
- [ ] `https://<frontend>/robots.txt` shows the real domain (confirms
      `KETSA_SITE_URL` was set at build time).
- [ ] `https://<frontend>/sitemap.xml` returns an XML urlset.
- [ ] Backend health check returns `ok`.
- [ ] `https://<frontend>/admin` loads the login page; a wrong password is
      rejected and the correct `KETSA_ADMIN_PASSWORD` logs in.
- [ ] Admin edit persists after a backend restart (i.e. `KETSA_DB_PATH` points
      at a real persistent volume — see Step 2b).
- [ ] Headers present in browser devtools on the homepage: `Content-Security-Policy`,
      `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`.

---

## How data gets from backend → page (why the values above work)

1. `frontend/app/page.tsx` is a **server component** marked `force-dynamic`.
   On every page request Vercel's server function calls
   `lib/api.ts → fetchHomeData()` → `GET {KETSA_BACKEND_URL}/api/home`.
2. This is a **server-to-server** call — no CORS applies, so the backend only
   needs its own `KETSA_ALLOWED_ORIGINS` set if you ever call it from a browser
   (e.g. debugging). It's set anyway as defense-in-depth.
3. If the backend is down/unreachable, the page renders `lib/fallbackData.ts`
   and shows the "using bundled data" badge. Nothing 500s.

### Why there's no `/api` rewrite in production
In **local dev**, `next.config.js` rewrites `/api/*` → the backend so your
browser can call the API same-origin. In **production** the browser never calls
`/api` — the server component fetches the backend directly over the network and
passes data down as props. The client components (`Markets`, `Dashboard`,
`WatchPanel`) render from those props and update locally for the live-price
"feel". This is exactly the design already in the repo — no extra proxy config
is required.

### Admin writes in production
The **admin panel is the one place the browser does call `/api`** in production:
`/admin` posts JSON to `/api/admin/*`, which Vercel's serverless functions
route to `KETSA_BACKEND_URL` same-origin to the frontend origin. Auth is a
bearer token from `POST /api/admin/login` (password = `KETSA_ADMIN_PASSWORD`),
held in `localStorage`. Writes update the backend's SQLite, so a page refresh
(and every subsequent visitor) sees the change.

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
`KETSA_ADMIN_PASSWORD` in `docker-compose.yml` (or the compose env), and mount
the named volume to `KETSA_DB_PATH` so admin edits persist. Both images run as
non-root users.
