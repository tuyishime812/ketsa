#!/usr/bin/env python3
"""Apply the Ketsa Postgres schema to a Supabase project.

Idempotent: everything in ``backend/db/schema.sql`` uses ``IF NOT EXISTS`` /
``ALTER ... ENABLE ROW LEVEL SECURITY`` (itself idempotent), so re-running is
safe and touches no data.

Two transports, tried in order (no third-party packages required):

  1. Supabase Management API  (recommended -- no local Postgres client)
         export SUPABASE_ACCESS_TOKEN=sbp_...        # dashboard -> Account -> Access Tokens
         python backend/scripts/apply_schema.py
     The target project is taken from KETSA_SUPABASE_PROJECT_REF, else parsed
     from SUPABASE_URL (``https://<ref>.supabase.co``).

  2. Direct Postgres via ``psql``  (needs psql on PATH + the DB password)
         export KETSA_DATABASE_URL=postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres
         python backend/scripts/apply_schema.py

If neither is available it prints the manual SQL-editor steps and exits 2.

Environment is loaded from ``backend/.env`` then ``.env`` (never overriding
values already set in the real environment, matching app/config.py). Token and
password values are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DB_DIR = REPO / "backend" / "db"

# Files run in this order (matches RUNBOOK Step 4). realtime.sql is optional.
DEFAULT_FILES = ["schema.sql"]


def load_dotenv() -> None:
    """Minimal .env loader that never overrides existing env vars."""
    for path in (REPO / "backend" / ".env", REPO / ".env"):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, val)


def project_ref() -> str | None:
    ref = (os.getenv("KETSA_SUPABASE_PROJECT_REF") or "").strip()
    if ref:
        return ref
    url = (os.getenv("SUPABASE_URL") or "").strip()
    m = re.match(r"https?://([a-z0-9]+)\.supabase\.(co|in)", url)
    return m.group(1) if m else None


def read_sql(files: list[str]) -> str:
    chunks = []
    for name in files:
        path = DB_DIR / name
        if not path.is_file():
            sys.exit(f"error: {path} not found")
        chunks.append(f"-- ==== {name} ====\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(chunks)


def apply_via_management_api(ref: str, token: str, sql: str) -> None:
    url = f"https://api.supabase.com/v1/projects/{ref}/database/query"
    req = urllib.request.Request(
        url,
        data=json.dumps({"query": sql}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    print(f"[db:apply] POST {url} ({len(sql)} bytes of SQL, project {ref})")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = resp.read().decode("utf-8", "replace")
            print(f"[db:apply] HTTP {resp.status} -> {body[:400]}")
        print("[db:apply] schema applied via Management API.")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        print(f"[db:apply] HTTP {exc.code}: {detail[:600]}", file=sys.stderr)
        if exc.code in (401, 403):
            print(
                "[db:apply] token rejected -- create one at Supabase -> Account -> "
                "Access Tokens and set SUPABASE_ACCESS_TOKEN.",
                file=sys.stderr,
            )
        sys.exit(1)
    except urllib.error.URLError as exc:
        sys.exit(f"[db:apply] network error: {exc.reason}")


def apply_via_psql(dsn: str, sql: str) -> None:
    psql = shutil.which("psql")
    if not psql:
        sys.exit("[db:apply] KETSA_DATABASE_URL is set but psql is not on PATH.")
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False, encoding="utf-8") as fh:
        fh.write(sql)
        tmp = fh.name
    print(f"[db:apply] psql -f <schema> (dsn host hidden)")
    try:
        proc = subprocess.run(
            [psql, dsn, "-v", "ON_ERROR_STOP=1", "-f", tmp],
            capture_output=True,
            text=True,
        )
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if proc.stdout:
        print(proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        sys.exit(f"[db:apply] psql exited {proc.returncode}")
    print("[db:apply] schema applied via psql.")


def print_manual_steps() -> None:
    print(
        """[db:apply] No Management token or DB URL found. Apply the schema manually:

  1. Open your Supabase project -> SQL editor -> New query.
  2. Paste the contents of backend/db/schema.sql and run it.
  3. (optional) Repeat for backend/db/realtime.sql if you use Realtime.

  Or automate it with EITHER:
    export SUPABASE_ACCESS_TOKEN=sbp_...     # Account -> Access Tokens
    python backend/scripts/apply_schema.py

    export KETSA_DATABASE_URL=postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres
    python backend/scripts/apply_schema.py
""",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply the Ketsa Supabase schema.")
    parser.add_argument(
        "--file",
        action="append",
        default=None,
        help="SQL file in backend/db to apply (repeatable). Default: schema.sql",
    )
    parser.add_argument(
        "--with-realtime",
        action="store_true",
        help="Also apply backend/db/realtime.sql (optional Supabase Realtime publication).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print what would run and exit.")
    args = parser.parse_args()

    load_dotenv()

    files = args.file or list(DEFAULT_FILES)
    if args.with_realtime and "realtime.sql" not in files:
        files.append("realtime.sql")

    sql = read_sql(files)
    token = (os.getenv("SUPABASE_ACCESS_TOKEN") or "").strip()
    dsn = (
        os.getenv("KETSA_DATABASE_URL")
        or os.getenv("SUPABASE_DB_URL")
        or os.getenv("DATABASE_URL")
        or ""
    ).strip()
    ref = project_ref()

    print(f"[db:apply] files: {', '.join(files)}  ({len(sql)} bytes)")
    if args.dry_run:
        print("[db:apply] dry-run: would use "
              + ("Management API" if token and ref else "psql" if dsn else "manual steps"))
        return 0

    if token and ref:
        apply_via_management_api(ref, token, sql)
        return 0
    if dsn:
        apply_via_psql(dsn, sql)
        return 0

    print_manual_steps()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
