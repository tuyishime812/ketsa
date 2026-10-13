"""Cross-process auth state: sessions, OTPs, SSO tickets and throttles.

Historically all of these lived in module-level dicts (``auth._sessions``,
``auth._otps``, ``admin._tokens``, …), which made them per-process and lost on
every restart or redeploy: a new backend process logged everyone out, voided
every pending signup/recovery code and silently reset every brute-force fence.

They now live in the active storage backend — in-process dicts in dev and the
test suite (``KETSA_DB_BACKEND=memory``), a real Postgres table
(``ketsa_auth`` in ``db/schema.sql``) in production (``supabase``). That gives:

  * restart/deploy survival — a session, pending OTP or ticket is still valid
    after the process dies or a new replica comes up;
  * one shared view across workers — the first half of the multi-process story
    (the trading engine's in-memory order book is the other half; see
    DEPLOY.md "Run exactly ONE backend process while real money is in play");
  * atomic single-use consumption — OTPs and tickets burn on a conditional
    DELETE in the shared backend, so two workers racing to burn the same code
    or ticket cannot both win (the loser's DELETE matches zero rows).

Layout: a single table, one `id` primary key that carries its namespace
("session:<digest>", "otp:<scope>", "ticket:<t>", "throttle:<bucket>",
"admin_session:<digest>"), plus indexed ``expires`` (Unix epoch seconds) so one
sweep cleans every namespace. Rows are swept lazily on the issue/access paths;
nothing here assumes a background cleaner exists.
"""

from __future__ import annotations

import time
from typing import Any

from . import store

NS_SESSION = "session"
NS_OTP = "otp"
NS_TICKET = "ticket"
NS_THROTTLE = "throttle"
NS_ADMIN_SESSION = "admin_session"


def _b() -> Any:
    return store.get_backend()


# --- lifecycle ---------------------------------------------------------------

def reset() -> None:
    """Drop every row of shared auth state (tests / explicit teardown)."""
    _b().auth_clear()


def sweep(now: float | None = None) -> None:
    """Delete expired rows across every namespace (lazy, opportunistic)."""
    _b().auth_sweep(time.time() if now is None else now)


# --- user sessions -----------------------------------------------------------

def put_session(digest: str, user_id: str, *, issued: float, expires: float) -> None:
    _b().auth_put(
        f"{NS_SESSION}:{digest}",
        NS_SESSION,
        user_id=user_id,
        issued=issued,
        expires=expires,
    )


def get_session(digest: str) -> tuple[float, str] | None:
    row = _b().auth_get(f"{NS_SESSION}:{digest}")
    if row is None:
        return None
    return (float(row["expires"]), str(row.get("user_id") or ""))


def touch_session(digest: str, expires: float) -> None:
    _b().auth_update(f"{NS_SESSION}:{digest}", {"expires": float(expires)})


def delete_session(digest: str) -> None:
    _b().auth_delete(f"{NS_SESSION}:{digest}")


def delete_sessions_for_user(user_id: str) -> int:
    return _b().auth_delete_for_user(NS_SESSION, user_id)


def session_count() -> int:
    return _b().auth_count(NS_SESSION)


# --- admin sessions ----------------------------------------------------------

def put_admin_session(digest: str, expires: float) -> None:
    _b().auth_put(
        f"{NS_ADMIN_SESSION}:{digest}",
        NS_ADMIN_SESSION,
        issued=time.time(),
        expires=expires,
    )


def get_admin_session(digest: str) -> float | None:
    row = _b().auth_get(f"{NS_ADMIN_SESSION}:{digest}")
    if row is None:
        return None
    return float(row["expires"])


def touch_admin_session(digest: str, expires: float) -> None:
    _b().auth_update(f"{NS_ADMIN_SESSION}:{digest}", {"expires": float(expires)})


def delete_admin_session(digest: str) -> None:
    _b().auth_delete(f"{NS_ADMIN_SESSION}:{digest}")


# --- Auth0 SSO tickets -------------------------------------------------------

def put_ticket(ticket: str, user_id: str, *, issued: float, expires: float) -> None:
    _b().auth_put(
        f"{NS_TICKET}:{ticket}",
        NS_TICKET,
        user_id=user_id,
        issued=issued,
        expires=expires,
    )


def take_ticket(ticket: str) -> dict | None:
    """Atomically claim and delete a ticket. Single use, even across workers.

    Returns the row (including ``user_id`` and ``expires``) or None if it was
    already taken. The caller checks expiry — the delete itself is unconditional
    so an abandoned ticket cannot linger past redemption.
    """
    return _b().auth_take(f"{NS_TICKET}:{ticket}")


def delete_ticket(ticket: str) -> None:
    _b().auth_delete(f"{NS_TICKET}:{ticket}")


def ticket_count() -> int:
    return _b().auth_count(NS_TICKET)


def oldest_tickets(limit: int) -> list[str]:
    """Raw ticket names of the oldest tickets, issuance order (for the hard cap).

    Names are returned *without* the namespace prefix, so callers can feed
    them straight back into ``delete_ticket``/``expire_ticket``.
    """
    prefix = f"{NS_TICKET}:"
    return [auth_id[len(prefix):] for auth_id in _b().auth_ids_oldest(NS_TICKET, limit)]


def expire_ticket(ticket: str, when: float) -> None:
    """Test helper: force a ticket's expiry stamp."""
    _b().auth_update(f"{NS_TICKET}:{ticket}", {"expires": float(when)})


# --- OTPs --------------------------------------------------------------------

def put_otp(
    key: str, secret_hash: str, payload: Any, *, issued: float, expires: float
) -> None:
    _b().auth_put(
        f"{NS_OTP}:{key}",
        NS_OTP,
        secret_hash=secret_hash,
        payload=payload,
        issued=issued,
        expires=expires,
    )


def delete_otp(key: str) -> None:
    _b().auth_delete(f"{NS_OTP}:{key}")


def get_otp(key: str) -> dict | None:
    return _b().auth_get(f"{NS_OTP}:{key}")


def consume_otp(
    key: str, secret_hash: str, *, max_attempts: int, now: float
) -> dict | None:
    """Burn the OTP iff the digest matches, it is unexpired and it is not past
    the attempt cap.

    One atomic DELETE in the shared backend: two workers presenting the same
    correct code cannot both consume it. Returns the deleted row (with the
    pending ``payload``) or None on any failure.
    """
    return _b().auth_consume_otp(
        f"{NS_OTP}:{key}",
        secret_hash=secret_hash,
        max_attempts=max_attempts,
        now=now,
    )


def bump_otp_attempts(key: str, *, max_attempts: int, now: float) -> None:
    """Count one failed guess, unless the code is already past its cap.

    The cap itself is enforced atomically by ``consume_otp``'s filter; this
    write is best-effort. A lost race costs at most a couple of extra guesses,
    which the cap filter still stops from ever succeeding.
    """
    row = _b().auth_get(f"{NS_OTP}:{key}")
    if row is None or row["expires"] <= now:
        return
    attempts = int(row.get("attempts") or 0)
    if attempts >= max_attempts:
        return
    _b().auth_update(f"{NS_OTP}:{key}", {"attempts": attempts + 1})


def expire_otp(key: str, when: float) -> None:
    """Test helper: force an OTP's expiry stamp."""
    _b().auth_update(f"{NS_OTP}:{key}", {"expires": float(when)})


def age_otp(key: str, issued: float) -> None:
    """Test helper: rewind an OTP's issued stamp (resend-cooldown tests)."""
    _b().auth_update(f"{NS_OTP}:{key}", {"issued": float(issued)})


def expire_all_otps(when: float) -> None:
    """Test helper: expire every pending OTP."""
    for auth_id in _b().auth_ids(NS_OTP):
        _b().auth_update(auth_id, {"expires": float(when)})


# --- throttles ---------------------------------------------------------------

def throttle_get(bucket_id: str) -> list[float]:
    """Failure/request stamps for a throttle bucket (window filtering is the
    caller's job — the store only keeps the newest row)."""
    row = _b().auth_get(bucket_id)
    if row is None:
        return []
    stamps = (row.get("payload") or {}).get("stamps") or []
    return [float(t) for t in stamps]


def throttle_set(bucket_id: str, stamps: list[float], window: float) -> None:
    """Record stamps for a bucket; the row expires after ``window`` seconds."""
    now = time.time()
    _b().auth_put(
        bucket_id,
        NS_THROTTLE,
        payload={"stamps": [float(t) for t in stamps]},
        issued=now,
        expires=now + float(window),
    )


def throttle_clear(bucket_id: str) -> None:
    _b().auth_delete(bucket_id)