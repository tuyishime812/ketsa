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

---

## Alternative: run everything with Docker (no Vercel)

If you prefer a single VPS instead of Vercel + a PaaS:

```bash
docker compose up --build -d
# frontend: http://<host>:3000
# api:      http://<host>:8000
```

Place a TLS-terminating reverse proxy (Caddy/Nginx/Traefik) in front. Set
`KETSA_ALLOWED_ORIGINS` and `KETSA_BACKEND_URL` in `docker-compose.yml` (or the
compose env). Both images run as non-root users.
