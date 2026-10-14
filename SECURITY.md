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
   logs, the wandePay payment ledger, Resend send history, and `/admin` access
   for unknown mutations, payouts, or sends.
4. **Verify:** `git log --all -- backend/.env` returns nothing, and
   `git grep -I -n 'SERVICE_ROLE_KEY\|WANDE_TOKEN\|RESEND_API_KEY' $(git rev-list --all)`
   finds no live value.
5. **Prevent recurrence:** confirm the gitleaks workflow is green and enable
   GitHub push protection.

> Rotate first. History rewrite stops *future* re-discovery; it does not
> invalidate a key a third party already read.
