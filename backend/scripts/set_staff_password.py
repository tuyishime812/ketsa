#!/usr/bin/env python3
"""Create or repair a per-staff admin account (bootstrap / recovery).

Normal onboarding should use **Staff → Set-password link**: the person receives
a single-use link and chooses their own password. This script exists for the
cases where that is not possible:

* local development, where ``KETSA_EMAIL_DELIVERY=log`` deliberately redacts the
  credential link (so the link cannot be recovered from the server log);
* first-owner bootstrap before any staff account can sign in;
* recovery when the only owner lost their password and email delivery is down.

Only the PBKDF2 hash is written. The plaintext password is read with
``getpass`` (or from stdin with ``--password-stdin`` for automation), never from
a command-line argument — argv is visible in the process list and shell history.

The account row is written through the same storage backend as the app
(``KETSA_DB_BACKEND``: ``memory`` in dev, ``supabase`` in production) and the
same ``backend/.env`` / repo ``.env`` files are loaded.

Examples::

    cd backend
    python scripts/set_staff_password.py --email owner@example.com --name Owner --role owner

    # non-interactive, e.g. piping a secret from a secret manager:
    printf '%s\\n' "$STAFF_PASSWORD" | \\
        python scripts/set_staff_password.py --email owner@example.com --password-stdin

The ``owner`` role is the highest *staff* role. Only the break-glass master
session (``KETSA_ADMIN_PASSWORD``, "Owner" tab on /admin) can change the master
password or the security/staff-role configuration; a staff owner cannot.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import secrets
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Deliberately simple: real validation/normalisation lives in app.staff, but we
# bypass the role allowlist here so an operator with server access can always
# bootstrap/recover the owner account even if the allowlist was edited.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def load_dotenv() -> None:
    """Load backend/.env then repo .env without overriding real env vars."""
    for path in (BACKEND / ".env", REPO / ".env"):
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


def _fail(message: str) -> int:
    print(f"[staff:password] error: {message}", file=sys.stderr)
    return 1


def read_password(from_stdin: bool) -> str:
    if from_stdin:
        value = sys.stdin.readline()
        if not value:
            sys.exit("[staff:password] error: --password-stdin was given but stdin was empty")
        return value.rstrip("\r\n")
    first = getpass.getpass("New password: ")
    second = getpass.getpass("Repeat password: ")
    if first != second:
        sys.exit("[staff:password] error: passwords do not match")
    return first


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create/repair a staff admin account and set its password."
    )
    parser.add_argument("--email", required=True, help="staff email (login identifier)")
    parser.add_argument(
        "--name",
        default="",
        help="display name (default: the part before @ in the email)",
    )
    parser.add_argument(
        "--role",
        default="owner",
        help="staff role (default: owner); must be one of the built-in roles",
    )
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the password from stdin instead of prompting (automation)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate input and report what would change, then exit",
    )
    args = parser.parse_args()

    load_dotenv()

    from app import audit, auth, staff, staffauth, store
    from app.audit import Actions as Audit
    from app.models import STAFF_ROLES

    email = (args.email or "").strip().lower()
    if not email or len(email) > 200 or not _EMAIL_RE.match(email):
        return _fail(f"invalid email: {args.email!r}")

    role = (args.role or "").strip().lower()
    if role not in STAFF_ROLES:
        return _fail(f"unknown role {role!r}; choose one of: {', '.join(STAFF_ROLES)}")

    password = read_password(args.password_stdin)
    try:
        staffauth.validate_password(password)
    except ValueError as exc:
        return _fail(str(exc))

    mode = (os.getenv("KETSA_DB_BACKEND") or "memory").strip().lower()
    try:
        existing = staff.find_by_email(email)
    except Exception as exc:  # bad/missing Supabase config, schema not applied, ...
        return _fail(f"could not read the storage backend ({mode}): {exc}")

    name = (args.name or email.split("@", 1)[0]).strip()[:80]
    if existing is None:
        now = time.time()
        member = {
            "id": "staff_" + secrets.token_hex(8),
            "name": name,
            "email": email,
            "phone": None,
            "role": role,
            "active": True,
            "created": now,
            "updated": now,
            "invited_ts": None,
        }
        action = "create"
    else:
        member = dict(existing)
        member["name"] = name
        member["role"] = role
        member["active"] = True
        action = "update"

    if args.dry_run:
        print(
            f"[staff:password] dry-run: would {action} {email} as {role!r} "
            f"in the {mode!r} backend"
        )
        return 0

    now = time.time()
    member["password_hash"] = auth.hash_password(password)
    member["password_updated"] = now
    member["invite_token_hash"] = None
    member["invite_expires"] = None
    member["invite_sent_ts"] = None
    member["updated"] = now

    try:
        store.upsert_staff(member)
        # A password set out-of-band must invalidate any session minted with the
        # old one, even if the previous credential was never used.
        staffauth.revoke_staff_sessions(member["id"])
    except Exception as exc:
        return _fail(f"could not write the account ({mode}): {exc}")

    try:
        audit.record(
            Audit.STAFF_PASSWORD_SET,
            actor_type="system",
            target_type="staff",
            target_id=str(member["id"]),
            metadata={"bootstrap": True, "role": role},
        )
    except Exception as exc:  # never hide a successful password change
        print(f"[staff:password] warning: audit row not written: {exc}", file=sys.stderr)

    print(
        f"[staff:password] {action}d {email} as role {role!r} "
        f"(id={member['id']}, backend={mode})"
    )
    print("[staff:password] password set; sign in at /admin with the Staff account tab.")
    if mode in ("", "memory", "sqlite"):
        print(
            "[staff:password] WARNING: this backend is ephemeral. The account "
            "disappears on restart; set KETSA_DB_BACKEND=supabase for a durable one.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
