# Security Policy

Ketsa moves real money (MWK via wandePay) and stores PII (email / phone). Treat
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

## ACTIVE INCIDENT — live credentials committed in `backend/.env`

Commit **`de191c6`** added `backend/.env` to version control and it was pushed
to `origin/main`. That file contained **live** credentials:

| Variable | Exposure |
|----------|----------|
| `KETSA_WANDE_TOKEN` | real-money mobile-money gateway — issue payouts |
| `SUPABASE_SERVICE_ROLE_KEY` | bypasses Row Level Security — full read/write on wallets, payments, users |
| `KETSA_RESEND_API_KEY` | send mail as the verified sending domain |
| `KETSA_AUTH0_CLIENT_SECRET` | OAuth client secret |
| `KETSA_ADMIN_PASSWORD` | the single key to `/admin` (settles real money) |

The file is now **untracked** (`git rm --cached backend/.env`), but it is still
in git **history** and remote clones. Untracking alone does not un-leak it.

### Remediation checklist (complete before launch)

1. **Rotate every credential above, at the source.** Rotation — not the history
   rewrite — is what actually stops the bleed:
   - wandePay: issue a new token, revoke the old one.
   - Supabase: rotate the `service_role` JWT secret (Project Settings → API), or
     create a fresh key and invalidate the old.
   - Resend: delete the exposed key in the dashboard, create a new one.
   - Auth0: rotate the application Client Secret.
   - Set a **new, strong `KETSA_ADMIN_PASSWORD`** (do not reuse the old value).
2. **Purge the file from history** and force-push (coordinate with anyone who
   has cloned the repo — their remotes will need to re-clone):
   ```bash
   # git-filter-repo is the supported path (pip install git-filter-repo)
   git filter-repo --path backend/.env --invert-paths
   git push origin --force --all
   git push origin --force --tags
   ```
   (Alternatively use BFG Repo-Cleaner. Rotating is mandatory either way — the
   values were already fetchable.)
3. **Audit for abuse since the leak** (commit dated 2026-10-11): review Supabase
   logs, the wandePay payment ledger, Resend send history, and `/admin` access
   for unknown mutations, payouts, or sends.
4. **Verify:** `git log --all -- backend/.env` returns nothing, and
   `git grep -I -n 'SERVICE_ROLE_KEY\|WANDE_TOKEN\|RESEND_API_KEY' $(git rev-list --all)`
   finds no live value.
5. **Prevent recurrence:** confirm the gitleaks workflow is green and enable
   GitHub push protection.

> Rotate first. History rewrite stops *future* re-discovery; it does not
> invalidate a key a third party already read.
