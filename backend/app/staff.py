"""Staff directory: validation, bulk upload, invites and realtime events.

A *staff member* is an operator of the platform (support, finance, …) — a
separate concept from a trader *account* (`store.list_users`). The directory is
admin-only to edit and publicly readable in a reduced form (name + role; never
email/phone, which are PII).

Every mutation emits a single ``{"type": "staff", ...}`` event onto the engine
event stream. main.py's pump broadcasts it to all WebSocket clients, so an
admin adding/removing staff updates every open admin panel *and* the public
team page without a refresh. The event payload is deliberately the PUBLIC view
(id/name/role/active) — the socket is unauthenticated, so contact details must
never ride on it (CWE-200). Admin clients re-fetch the full list on a staff
event.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import secrets
import time
from typing import Any, Iterable

from . import mailer, siteconfig, store
from .engine import engine
from .models import StaffInviteResult, StaffUploadResult

log = logging.getLogger("ketsa.staff")

# Bounded and pragmatic: one @, no whitespace, a dotted domain. The DB unique
# index is the real dedupe guard; this only rejects obvious garbage early.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

MAX_UPLOAD_ROWS = 1000
MAX_ERRORS = 50

# Header aliases so a hand-made spreadsheet still maps. Keys are compared
# lower-cased and whitespace-collapsed.
_HEADER_ALIASES = {
    "name": "name",
    "full name": "name",
    "fullname": "name",
    "staff": "name",
    "staff name": "name",
    "email": "email",
    "e-mail": "email",
    "email address": "email",
    "mail": "email",
    "phone": "phone",
    "phone number": "phone",
    "mobile": "phone",
    "mobile number": "phone",
    "tel": "phone",
    "role": "role",
    "position": "role",
    "title": "role",
    "job title": "role",
}


def _now() -> float:
    return time.time()


def _clean(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split())


def normalize_phone(raw: Any) -> str | None:
    """Canonicalise a phone number, or None when blank.

    Stored form is ``[+]<digits>`` so the ``ketsa_staff`` unique index actually
    prevents duplicate entries that differ only in spacing/punctuation.
    Raises ValueError on a value that has digits but is implausibly short/long.
    """
    text = _clean(raw)
    if not text:
        return None
    plus = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    if not 7 <= len(digits) <= 15:
        raise ValueError(f"invalid phone number {text!r}")
    return ("+" if plus else "") + digits


def _coerce(raw: dict, roles: Iterable[str] | None = None) -> dict:
    """Validate one row into canonical staff fields, or raise ValueError.

    ``roles`` is the admin-configured allowlist. Callers validating a batch
    fetch it once (``siteconfig.staff_roles()``) and pass it in, so a bulk
    upload of N rows costs one settings read rather than N.
    """
    norm: dict[str, Any] = {}
    for key, value in raw.items():
        canon = _HEADER_ALIASES.get(_clean(key).lower())
        if canon and canon not in norm:
            norm[canon] = value

    name = _clean(norm.get("name"))
    if not name:
        raise ValueError("name is required")
    if len(name) > 80:
        name = name[:80]

    email = _clean(norm.get("email")).lower()
    if not email:
        raise ValueError("email is required")
    if len(email) > 200 or not _EMAIL_RE.match(email):
        raise ValueError(f"invalid email {email!r}")

    phone = normalize_phone(norm.get("phone"))

    role_allowed = list(roles) if roles is not None else siteconfig.staff_roles()
    # Default to the first configured role (rather than a hard-coded "support")
    # so removing a role from the allowlist can't break rows that omit one.
    role = _clean(norm.get("role")).lower() or (role_allowed[0] if role_allowed else "support")
    if role not in role_allowed:
        raise ValueError(
            f"unknown role {role!r} (one of: {', '.join(role_allowed)})"
        )

    return {"name": name, "email": email, "phone": phone, "role": role}


# --- reads ------------------------------------------------------------------

def list_staff() -> list[dict]:
    return sorted(store.list_staff(), key=lambda s: _clean(s.get("name")).lower())


def get_staff(staff_id: str) -> dict | None:
    return store.get_staff(staff_id)


def find_by_email(email: str) -> dict | None:
    needle = _clean(email).lower()
    if not needle:
        return None
    for s in store.list_staff():
        if _clean(s.get("email")).lower() == needle:
            return s
    return None


def find_by_phone(phone: str) -> dict | None:
    try:
        needle = normalize_phone(phone)
    except ValueError:
        return None
    if not needle:
        return None
    for s in store.list_staff():
        try:
            if normalize_phone(s.get("phone")) == needle:
                return s
        except ValueError:
            continue
    return None


def public_view(member: dict) -> dict:
    """The reduced, PII-free projection safe to broadcast publicly."""
    return {
        "id": member.get("id"),
        "name": member.get("name"),
        "role": member.get("role"),
        "active": bool(member.get("active", True)),
    }


def list_public() -> list[dict]:
    return [
        {"id": s["id"], "name": s["name"], "role": s["role"]}
        for s in list_staff()
        if s.get("active", True)
    ]


# --- realtime ---------------------------------------------------------------

def _emit(action: str, member: dict | None = None, staff_id: str | None = None) -> None:
    payload: dict[str, Any] = {
        "type": "staff",
        "action": action,
        "staff": public_view(member) if member else None,
    }
    sid = staff_id or (member.get("id") if member else None)
    if sid:
        payload["id"] = sid
    engine.emit(payload)


# --- writes -----------------------------------------------------------------

def _new_member(fields: dict) -> dict:
    now = _now()
    return {
        "id": "staff_" + secrets.token_hex(8),
        **fields,
        "active": True,
        "created": now,
        "updated": now,
        "invited_ts": None,
    }


def create_staff(
    name: str,
    email: str,
    phone: Any = None,
    role: str = "support",
) -> dict:
    """Add one staff member. Raises ValueError on invalid or duplicate input."""
    fields = _coerce({"name": name, "email": email, "phone": phone, "role": role})
    if find_by_email(fields["email"]):
        raise ValueError("a staff member with that email already exists")
    if fields["phone"] and find_by_phone(fields["phone"]):
        raise ValueError("a staff member with that phone already exists")
    member = _new_member(fields)
    store.upsert_staff(member)
    _emit("add", member)
    return member


def update_staff(staff_id: str, patch: dict) -> dict | None:
    """Apply a partial update (e.g. toggle `active`). None if not found."""
    member = store.get_staff(staff_id)
    if member is None:
        return None
    # Allow the member's current role even if it has since been removed from the
    # allowlist, so unrelated edits (e.g. toggling `active`) don't fail on it.
    roles = siteconfig.staff_roles()
    current_role = _clean(member.get("role")).lower()
    if current_role and current_role not in roles:
        roles = roles + [current_role]
    fields = _coerce(
        {
            "name": patch.get("name", member.get("name")),
            "email": patch.get("email", member.get("email")),
            "phone": patch.get("phone", member.get("phone")),
            "role": patch.get("role", member.get("role")),
        },
        roles,
    )
    other = find_by_email(fields["email"])
    if other and other.get("id") != staff_id:
        raise ValueError("a staff member with that email already exists")
    if fields["phone"]:
        other = find_by_phone(fields["phone"])
        if other and other.get("id") != staff_id:
            raise ValueError("a staff member with that phone already exists")

    member.update(fields)
    if patch.get("active") is not None:
        member["active"] = bool(patch["active"])
    member["updated"] = _now()
    store.upsert_staff(member)
    _emit("update", member)
    return member


def delete_staff(staff_id: str) -> bool:
    if store.get_staff(staff_id) is None:
        return False
    store.delete_staff(staff_id)
    _emit("remove", staff_id=staff_id)
    return True


def invite_staff(staff_id: str) -> StaffInviteResult:
    """Send the welcome/notification email to a staff member.

    Reports honestly: ``delivered`` is True only when the transport can really
    deliver (Resend configured). In local ``log`` mode the mailer writes the
    message to the server log and we say so, rather than promising an email
    that never left the building.
    """
    member = store.get_staff(staff_id)
    if member is None:
        raise KeyError(staff_id)
    ok = mailer.send_staff_invite(
        member["email"], member.get("name", ""), member.get("role", "support")
    )
    delivered = bool(ok) and mailer.delivery_configured()
    if delivered:
        member["invited_ts"] = _now()
        member["updated"] = _now()
        store.upsert_staff(member)
        _emit("invite", member)
        detail = "Invite email sent."
    elif ok:
        mode = mailer.email_status().get("delivery", "log")
        detail = (
            f"Email is not configured to deliver (delivery={mode}); the invite "
            "was logged on the server, not sent."
        )
    else:
        detail = "Invite could not be sent — check the email transport configuration."
    return StaffInviteResult(ok=bool(ok), delivered=delivered, detail=detail)


# --- bulk upload ------------------------------------------------------------

def _parse(text: str | None, rows: Iterable[dict] | None) -> list[dict]:
    if rows is not None:
        return [dict(r) for r in rows if isinstance(r, dict)]
    raw = (text or "").strip()
    if not raw:
        return []
    if raw[0] in "[{":
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc.msg}") from exc
        if isinstance(loaded, dict):
            loaded = loaded.get("staff") or loaded.get("rows") or [loaded]
        if not isinstance(loaded, list):
            raise ValueError("JSON upload must be a list of objects")
        return [dict(r) for r in loaded if isinstance(r, dict)]
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        raise ValueError("CSV upload has no header row")
    return [dict(r) for r in reader]


def upload(
    text: str | None = None,
    rows: Iterable[dict] | None = None,
) -> StaffUploadResult:
    """Bulk add/update from CSV or JSON text (or pre-parsed ``rows``)."""
    try:
        parsed = _parse(text, rows)
    except ValueError as exc:
        result = StaffUploadResult()
        result.errors = [str(exc)]
        return result

    if len(parsed) > MAX_UPLOAD_ROWS:
        result = StaffUploadResult()
        result.errors = [f"too many rows (max {MAX_UPLOAD_ROWS})"]
        return result

    result = StaffUploadResult()
    errors: list[str] = []
    seen_emails: set[str] = set()
    seen_phones: set[str] = set()
    # One settings read for the whole batch (see _coerce).
    roles = siteconfig.staff_roles()

    for index, row in enumerate(parsed, start=1):
        try:
            fields = _coerce(row, roles)
        except ValueError as exc:
            errors.append(f"row {index}: {exc}")
            result.skipped += 1
            continue

        email = fields["email"]
        phone = fields["phone"]
        if email in seen_emails or (phone and phone in seen_phones):
            errors.append(f"row {index}: duplicate of an earlier row ({email})")
            result.skipped += 1
            continue
        seen_emails.add(email)
        if phone:
            seen_phones.add(phone)

        by_email = find_by_email(email)
        by_phone = find_by_phone(phone) if phone else None
        if by_email and by_phone and by_email.get("id") != by_phone.get("id"):
            errors.append(
                f"row {index}: email and phone already belong to different staff"
            )
            result.skipped += 1
            continue
        existing = by_email or by_phone
        # Mutate without emitting: the batch fires a single "upload" event below.
        if existing:
            existing.update(fields)
            existing["updated"] = _now()
            store.upsert_staff(existing)
            result.updated += 1
        else:
            store.upsert_staff(_new_member(fields))
            result.added += 1

    result.errors = errors[:MAX_ERRORS]
    # ONE event for the whole batch: clients re-fetch once rather than N times.
    if result.added or result.updated:
        _emit("upload")
    return result
