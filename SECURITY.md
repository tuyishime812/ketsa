# Security Policy

Ketsa moves real money (MWK via PayChangu) and stores PII (email / phone). Treat
every credential as production-grade and every write path as adversarial.

---

## Reporting a vulnerability

Do **not** open a public issue for a security problem. Email the maintainer
privately with: affected component, a reproduction, and the impact. Do not
include live credentials or PII in the report. We aim to acknowledge within
2 business days.

---

## Secret handling policy

- **No secret is ever committed.** Secrets live only in the host's secret
  manager / environment UI (Railway/Render/Fly/Vercel) or in the gitignored
  local files `backend/.env` and `frontend/.env.local`.
- The committed files `/.env.example`, `/.env.production.example` are
  **templates** and must contain placeholders only.
- CI runs **gitleaks** (`.github/workflows/gitleaks.yml`) on every push and PR
  and fails the build on a detected credential.
- Enable **GitHub → Settings → Code security → Secret scanning + Push
  protection** on the repository as defence in depth.

---

## Session, proxy and XSS controls

- **Admin session is not readable by JavaScript.** The runtime `/api` proxy
  exchanges the admin bearer token for an `HttpOnly; SameSite=Strict` cookie
  scoped to `/api/admin`, strips the token from the login response, and
  re-attaches it server-side. Cookie-authenticated writes also require a
  same-origin `Origin` / `Sec-Fetch-Site`; logout, 401 and 403 clear the cookie.
  There is no admin token in `localStorage`.
- **CSP uses a per-request nonce.** `frontend/middleware.ts` emits
  `script-src 'self' 'nonce-…' 'strict-dynamic'` (no `'unsafe-inline'` for
  scripts; `'unsafe-eval'` only in dev). `KETSA_CSP` can override, and
  `{nonce}` is substituted when present.
- **Per-IP controls survive the proxy.** `backend/app/netutil.py` resolves the
  caller from either the HMAC-signed `X-Ketsa-Client-*` headers (set by the
  frontend proxy using the shared `KETSA_PROXY_SECRET`) or trusted-proxy CIDRs
  (`KETSA_TRUSTED_PROXIES`); otherwise it uses the direct peer. Never trust a
  raw `X-Forwarded-For` from an unconfigured peer.
- Keep `KETSA_PROXY_SECRET` out of git and set the same value on both services.
  Rotating it only rejects in-flight proxy requests; no data changes.

---

## Privileged-action audit log

`backend/app/audit.py` records every privileged or money-moving action to an
**append-only** log; the table is `ketsa_audit` (Supabase) with a bounded
in-memory equivalent for dev.

- **What is recorded.** Admin login ok / failed / locked-out, logout, password
  change, content reset, config changes, market create/update/**resolve**
  (with outcome and payout totals), user password reset/delete, staff
  create/update/delete/upload/invite, broadcast start, and user-facing password
  changes. The action vocabulary lives in `audit.Actions` (stable strings).
- **Actor identity.** Recorded as a stable id — a prefix of the admin session
  digest, or the acting user id — never the token or password. The client IP
  comes from `netutil.client_ip` (proxy-aware, see above).
- **No secrets.** Passwords, OTP codes and bearer tokens are never written.
  Metadata holds only identifiers, field *names*, outcomes and totals.
- **Best-effort.** A failed write is logged and swallowed: auditing never
  breaks, or rolls back, the action it describes. Rows are written *after* the
  action succeeds.
- **Insert/read only.** No application path updates or deletes a row; a content
  reset never clears it. In Supabase, RLS with no policies denies the public
  anon key all access — only the backend's service role may read or write.
- **Read endpoint.** `GET /api/admin/audit?limit=&action=` (admin-gated) returns
  newest-first rows plus a total count. The page size is capped at 500.

---

## ACTIVE INCIDENT — live credentials committed in `backend/.env`

Commit **`de191c6`** added `backend/.env` to version control and it was pushed
to `origin/main`. That file contained **live** credentials:

| Variable | Exposure |
|----------|----------|
| `PAYCHANGU_SECRET_KEY` | real-money mobile-money gateway — issue payouts |
| `PAYCHANGU_WEBHOOK_SECRET` | forge payment-settled webhooks (still re-verified before crediting) |
| `SUPABASE_SERVICE_ROLE_KEY` | bypasses Row Level Security — full read/write on wallets, payments, users |
| `KETSA_RESEND_API_KEY` | send mail as the verified sending domain |
| `KETSA_AUTH0_CLIENT_SECRET` | OAuth client secret |
| `KETSA_ADMIN_PASSWORD` | break-glass owner key to `/admin` (settles real money); staff use per-account credentials |

The file is now **untracked** (`git rm --cached backend/.env`), but it is still
in git **history** and remote clones. Untracking alone does not un-leak it.

### Remediation checklist (complete before launch)

1. **Rotate every credential above, at the source.** Rotation — not the history
   rewrite — is what actually stops the bleed:
   - PayChangu: issue a new secret + webhook secret, revoke the old ones.
   - Supabase: rotate the `service_role` JWT secret (Project Settings → API), or
     create a fresh key and invalidate the old.
   - Resend: delete the exposed key in the dashboard, create a new one.
   - Auth0: rotate the application Client Secret.
   - Set a **new, strong `KETSA_ADMIN_PASSWORD`** (do not reuse the old value).
     Watch the shadowing gotcha: once the password has ever been changed in
     **Settings → Security**, a PBKDF2 hash is stored in the settings row and
     `KETSA_ADMIN_PASSWORD` is **ignored** for login (`_check_password` in
     `backend/app/admin.py`). Editing `.env` then is a silent no-op — rotate via
     the UI, or clear the stored hash, instead. To see which value is live:
     ```bash
     cd backend && python -c "import app.config as c; c.load_env_file(); \
       import app.storage as s; print(bool(s.get_setting('admin_password')))"
     # True  -> the stored (UI) password is authoritative: rotate there.
     # False -> KETSA_ADMIN_PASSWORD is authoritative: rotate the env value.
     ```
2. **Purge the values from history** and force-push (coordinate with anyone who
   has cloned the repo — their remotes will need to re-clone).

   > Removing `backend/.env` alone is **not** enough: the real admin password
   > also sat in `README.md` and `.env.production.example` in older blobs. The
   > purge must delete the file *and* blank the leaked values everywhere.

   The supported path is `scripts/purge-secrets-from-history.ps1` (wraps
   git-filter-repo — `pip install git-filter-repo`). It backs up a tag + bundle,
   derives the value list from the leaked blob, defaults to a safe dry run, and
   rewrites only with `-Execute`:

   ```powershell
   ./scripts/purge-secrets-from-history.ps1            # dry run + report
   ./scripts/purge-secrets-from-history.ps1 -Execute   # rewrite (does NOT push)
   git remote add origin https://github.com/tuyishime812/ketsa.git
   git push origin --force --all
   git push origin --force --tags
   ```

   Or by hand:

   ```bash
   git filter-repo --force --invert-paths --path backend/.env \
       --replace-text .git-secrets-to-scrub.txt
   git push origin --force --all && git push origin --force --tags
   ```

   (Alternatively use BFG Repo-Cleaner. Rotating is mandatory either way — the
   values were already fetchable.)
3. **Audit for abuse since the leak** (commit dated 2026-10-11): review Supabase
   logs, the PayChangu payment ledger, Resend send history, and `/admin` access
   for unknown mutations, payouts, or sends.
4. **Verify:** `git log --all -- backend/.env` returns nothing, and
   `git grep -I -n 'SERVICE_ROLE_KEY\|PAYCHANGU_SECRET_KEY\|PAYCHANGU_WEBHOOK_SECRET\|RESEND_API_KEY' $(git rev-list --all)`
   finds no live value.
5. **Prevent recurrence:** confirm the gitleaks workflow is green and enable
   GitHub push protection.

> Rotate first. History rewrite stops *future* re-discovery; it does not
> invalidate a key a third party already read.
