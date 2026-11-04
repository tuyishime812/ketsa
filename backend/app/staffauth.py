"""Credential lifecycle for per-staff admin accounts.

A staff member is a row in the team directory (``staff.py``). This module turns
that row into a login identity:

  * ``send_invite`` mints a single-use, expiring token and emails a link to the
    frontend set-password page. Only the token's SHA-256 digest is stored, so a
    database/memory dump cannot be replayed as a working link.
  * ``accept_invite`` burns the link (clearing the digest, so it is single-use
    even if two requests race — the second sees no token) and stores a PBKDF2
    password hash.
  * ``verify_credentials`` does a PBKDF2 check for staff login, including a
    dummy check for unknown/disarmed accounts so response timing does not
    reveal which emails exist.
  * ``issue_session`` / ``revoke_staff_sessions`` manage the bearer session
    digests in the shared auth store (``authstate.NS_STAFF_SESSION``).

Nothing here ever returns, logs or broadcasts a plaintext password or token.
The admin API layer (``admin.py``) owns HTTP status codes, throttling and audit
rows; this module only enforces the credential invariants.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from urllib.parse import quote

from . import auth, authstate, mailer, staff, store
from .models import StaffInviteResult

# Admin sessions (master and staff) share this lifetime. Kept in sync with
# admin.TOKEN_TTL and the Next proxy cookie's Max-Age.
SESSION_TTL = 12 * 3600

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256

# Same shape as a token_urlsafe(32) value. Bad shapes are rejected before any
# hashing/lookup work so a giant query string cannot make us do pointless work.
_INVITE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")

# Computed once, lazily, to equalise login timing for unknown emails.
_DUMMY_HASH: str | None = None

# Serialises the invite read-modify-write so one link cannot be redeemed twice
# by concurrent requests (see accept_invite).
_INVITE_LOCK = threading.Lock()


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = auth.hash_password(secrets.token_hex(16))
    return _DUMMY_HASH


def validate_password(password: str) -> None:
    """Raise ValueError unless ``password`` is an acceptable new password.

    The upper bound matters: PBKDF2 cost scales with input length, so an
    unbounded field is a cheap CPU-exhaustion primitive on a public endpoint.
    """
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters")


def hash_session_token(token: str) -> str:
    """Digest for a staff session token (namespaced away from user/master)."""
    return hashlib.sha256(("ketsa:staff:" + token).encode()).hexdigest()


def _hash_invite_token(token: str) -> str:
    return hashlib.sha256(("ketsa:staff-invite:" + token).encode()).hexdigest()


def invite_ttl_seconds() -> int:
    """Lifetime of an invite/reset link, env-tunable for tests/deployments."""
    try:
        value = int(os.getenv("KETSA_STAFF_INVITE_TTL_SECONDS", "86400"))
    except ValueError:
        value = 86400
    # Clamp: too short makes email latency fail the flow, too long leaves a
    # usable link in an inbox indefinitely.
    return max(300, min(value, 7 * 24 * 3600))


def public_base_url() -> str:
    """Origin of the public frontend, used to build the emailed link.

    Fixed from the environment (never from the request) so a Host-header
    attacker cannot turn an invite email into a link to their own domain.
    """
    raw = (
        os.getenv("KETSA_PUBLIC_URL")
        or os.getenv("KETSA_FRONTEND_URL")
        or "http://localhost:3000"
    ).strip()
    if not raw.startswith(("http://", "https://")):
        return "http://localhost:3000"
    return raw.rstrip("/")


def _invite_link(token: str) -> str:
    # The token goes in the URL *fragment*, not the query string: fragments are
    # never sent to the frontend server, its access logs, a CDN, or as a
    # Referer to any subresource. The set-password page reads and immediately
    # clears it before the user can submit anything.
    return f"{public_base_url()}/admin/set-password#token={quote(token, safe='')}"


def send_invite(member: dict, *, reset: bool = False) -> StaffInviteResult:
    """Mint a credential link, persist its digest and email it.

    The token is stored *before* sending so the link is valid the moment it
    leaves the building; a failed send simply leaves an unused digest that the
    next invite overwrites. Reports delivery honestly, like the directory
    invite path (``KETSA_EMAIL_DELIVERY=log`` means "logged, not delivered").
    """
    token = secrets.token_urlsafe(32)
    ttl = invite_ttl_seconds()
    now = time.time()
    member["invite_token_hash"] = _hash_invite_token(token)
    member["invite_expires"] = now + ttl
    member["invite_sent_ts"] = now
    member["updated"] = now
    store.upsert_staff(member)
    staff.emit_update(member)

    link = _invite_link(token)
    ok = mailer.send_staff_credentials_invite(
        member["email"],
        link,
        member.get("name", ""),
        member.get("role", "support"),
        ttl_minutes=max(1, ttl // 60),
        reset=reset,
    )
    delivered = bool(ok) and mailer.delivery_configured()
    if delivered:
        detail = "Password reset email sent." if reset else "Password setup email sent."
    elif ok:
        mode = mailer.email_status().get("delivery", "log")
        detail = (
            f"Email is not configured to deliver (delivery={mode}); the message "
            "was logged with the credential token redacted, not sent."
        )
    else:
        detail = "Email could not be sent — check the email transport configuration."
    return StaffInviteResult(ok=bool(ok), delivered=delivered, detail=detail)


def find_by_invite_token(token: str) -> dict | None:
    """Resolve a link token to a live, active staff record.

    Compares digests in constant time and rejects expired/disabled rows. An
    unknown, expired or already-used token is indistinguishable to the caller
    (all yield None), so the endpoint cannot be used as a token oracle.
    """
    if not token or not _INVITE_TOKEN_RE.match(token):
        return None
    digest = _hash_invite_token(token)
    now = time.time()
    for member in store.list_staff():
        stored = member.get("invite_token_hash")
        if not stored or not isinstance(stored, str):
            continue
        if not hmac.compare_digest(stored, digest):
            continue
        if not member.get("active", True):
            return None
        try:
            expires = float(member.get("invite_expires") or 0)
        except (TypeError, ValueError):
            return None
        return member if expires > now else None
    return None


def accept_invite(token: str, new_password: str) -> dict:
    """Consume an invite/reset link and set the new password.

    The token digest is cleared in the same write as the new password, so a
    replay afterwards finds no token at all. The read-modify-write is also
    serialised by a process lock: without it, two concurrent requests for the
    same link could both pass the token check and the last writer would win
    (CWE-362). Multi-worker deployments are already documented to run a single
    backend process while real money is in play (see DEPLOY.md).
    """
    validate_password(new_password)
    # Hash outside the lock: PBKDF2 is deliberately slow and would otherwise
    # serialise unrelated accepts behind one another.
    new_hash = auth.hash_password(new_password)
    with _INVITE_LOCK:
        member = find_by_invite_token(token)
        if member is None:
            raise ValueError(
                "This link is invalid or has expired. Ask an admin for a new one."
            )
        now = time.time()
        member["password_hash"] = new_hash
        member["password_updated"] = now
        member["invite_token_hash"] = None
        member["invite_expires"] = None
        member["updated"] = now
        store.upsert_staff(member)
        # Any session minted before this password existed is no longer trusted.
        revoke_staff_sessions(member["id"])
        staff.emit_update(member)
    return member


def verify_credentials(email: str, password: str) -> dict | None:
    """Return the active staff member for a valid email/password pair, or None.

    Unknown emails, disabled accounts and accounts without a password still pay
    for one PBKDF2 verification against a dummy hash, so the response time does
    not reveal which of those is the case (user enumeration / timing oracle).
    """
    normalized = " ".join(str(email or "").split()).lower()
    member = staff.find_by_email(normalized) if normalized else None
    stored = (member or {}).get("password_hash")
    password = password or ""
    if not member or not member.get("active", True) or not stored:
        auth.verify_password(password, _dummy_hash())
        return None
    if len(password) > MAX_PASSWORD_LENGTH:
        auth.verify_password(password, _dummy_hash())
        return None
    if not auth.verify_password(password, stored):
        return None
    return member


def issue_session(member: dict) -> str:
    """Mint a staff admin session token and record its digest."""
    token = secrets.token_urlsafe(32)
    digest = hash_session_token(token)
    now = time.time()
    authstate.put_staff_session(
        digest,
        member["id"],
        expires=now + SESSION_TTL,
        role=member.get("role", ""),
        name=member.get("name", ""),
        email=member.get("email", ""),
    )
    member["last_login_ts"] = now
    member["updated"] = now
    store.upsert_staff(member)
    staff.emit_update(member)
    return token


def revoke_session_token(token: str) -> None:
    if token:
        authstate.delete_staff_session(hash_session_token(token))


def revoke_staff_sessions(staff_id: str) -> int:
    if not staff_id:
        return 0
    return authstate.delete_staff_sessions(staff_id)


def change_password(member: dict, current: str, new_password: str) -> None:
    """Self-service password change for a logged-in staff member."""
    stored = member.get("password_hash")
    if not stored or not auth.verify_password(current or "", stored):
        raise ValueError("Current password is incorrect")
    validate_password(new_password)
    member["password_hash"] = auth.hash_password(new_password)
    member["password_updated"] = time.time()
    member["updated"] = member["password_updated"]
    store.upsert_staff(member)
    # Force every device (including this one) to sign in with the new password.
    revoke_staff_sessions(member["id"])
    staff.emit_update(member)
