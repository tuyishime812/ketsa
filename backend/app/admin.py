"""Protected admin API for managing the Ketsa site content.

Two kinds of principal may authenticate:

* **Per-staff accounts** (email + password) created in the Staff directory.
  Their role maps to capabilities in `permissions.py`; the server enforces
  every capability and the dashboard only hides what a role cannot use.
* **The shared break-glass password** (`KETSA_ADMIN_PASSWORD`), treated as an
  `owner` super-user so losing staff credentials can never lock the operator
  out. Only this master session may change the master password or the security
  configuration.

On login the client receives a server-issued bearer token which must be sent on
every subsequent request via `Authorization: Bearer <token>`. Tokens are random
and only their digests live in the shared auth store (authstate.py), so a
restart/redeploy does not log anyone out and every worker validates the same
token. Staff and master sessions use separate namespaces, so one can be revoked
without touching the other.

Both login paths are brute-force throttled (per IP, and per email for staff
accounts) exactly like user account login in `auth.py`.
"""

import asyncio
import csv
import hashlib
import io
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from . import audit, authstate, mailer, netutil, permissions, siteconfig, staff, staffauth, store
from .audit import Actions as Audit
from .auth import hash_password, lookup_user_by_identifier, revoke_user_sessions
from .engine import engine
from .models import (
    AdminUserView,
    MarketInput,
    StaffAcceptInvite,
    StaffChangePassword,
    StaffCreate,
    StaffForgotPassword,
    StaffInviteResult,
    StaffMember,
    StaffUpdate,
    StaffUpload,
    StaffUploadResult,
)
from .storage import (
    RESERVED_KV_KEYS,
    get_all_settings,
    get_setting,
    reset_db,
    set_setting,
)

logger = logging.getLogger("ketsa.admin")

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Admin tokens last 12h (sliding). Digests live in the shared auth store —
# same restart-survival and multi-worker story as user sessions (authstate.py).
TOKEN_TTL = 12 * 3600

# Password hashing (PBKDF2-HMAC-SHA256) for the optional stored admin password.
_SALT_LEN = 16
_PBKDF2_ITER = 100_000

# Brute-force throttle for POST /login, keyed by client IP. Stamps live in the
# shared store so a redeploy doesn't reset the fence and all workers count the
# same failures.
#
# These are only the *fallbacks*: the effective values come from the admin
# Settings → Security section (siteconfig.security()), which itself defaults to
# the KETSA_ADMIN_* env vars. Reading them per call means an admin change takes
# effect without a restart.
LOGIN_MAX_FAILURES = 10
LOGIN_LOCKOUT_SECONDS = 900


def _login_window() -> int:
    try:
        return int(siteconfig.security()["admin_lockout_seconds"])
    except (KeyError, TypeError, ValueError):
        return LOGIN_LOCKOUT_SECONDS


def _login_max_failures() -> int:
    try:
        return int(siteconfig.security()["admin_max_failures"])
    except (KeyError, TypeError, ValueError):
        return LOGIN_MAX_FAILURES


def _client_ip(request: Request) -> str:
    # Trusted-proxy aware: see netutil.py. Using ``request.client.host`` here
    # would let one shared proxy IP turn the admin lockout into a DoS against
    # the site owner (any caller could trip it for everyone).
    return netutil.client_ip(request)


def _env_password() -> str:
    return os.getenv("KETSA_ADMIN_PASSWORD") or "ketsa-admin"


def _stored_password_hash() -> str | None:
    return get_setting("admin_password")


def _set_stored_password(password: str) -> None:
    salt = os.urandom(_SALT_LEN)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITER)
    set_setting("admin_password", f"{salt.hex()}${dk.hex()}")


def _verify_stored_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITER)
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(dk.hex(), hash_hex)


def _check_password(password: str) -> bool:
    stored = _stored_password_hash()
    if stored is not None:
        return _verify_stored_password(password, stored)
    # No stored password yet: fall back to the env/default value.
    return secrets.compare_digest(password.encode(), _env_password().encode())


def _hash_token(token: str) -> str:
    # Store only a HMAC-style hash of the token in memory so a memory dump
    # doesn't leak usable tokens. Token entropy makes this safe enough.
    return hashlib.sha256(("ketsa:" + token).encode()).hexdigest()


def _master_principal(digest: str, now: float) -> dict | None:
    expiry = authstate.get_admin_session(digest)
    if expiry is None or expiry < now:
        # Purge expired digest for hygiene.
        authstate.delete_admin_session(digest)
        return None
    authstate.touch_admin_session(digest, now + TOKEN_TTL)  # sliding window
    return {
        "kind": "master",
        "id": "master",
        "role": "owner",
        "name": "Owner",
        "email": "",
        "actor": digest[:16],
        "capabilities": sorted(permissions.ALL_CAPABILITIES),
    }


def _staff_principal(digest: str, now: float) -> dict | None:
    session = authstate.get_staff_session(digest)
    if session is None:
        return None
    if session["expires"] < now:
        authstate.delete_staff_session(digest)
        return None
    member = store.get_staff(session["staff_id"])
    # The session is only a claim on the staff id. Deactivation, deletion or a
    # credential reset must take effect immediately, so the live record is the
    # authority for both existence and role.
    if (
        member is None
        or not member.get("active", True)
        or not member.get("password_hash")
    ):
        staffauth.revoke_staff_sessions(session["staff_id"])
        return None
    authstate.touch_staff_session(digest, now + TOKEN_TTL)
    role = str(member.get("role") or "support").strip().lower()
    return {
        "kind": "staff",
        "id": str(member.get("id") or ""),
        "role": role,
        "name": str(member.get("name") or ""),
        "email": str(member.get("email") or ""),
        "actor": f"staff:{member.get('id')}",
        "capabilities": sorted(permissions.capabilities_for_role(role)),
    }


def resolve_admin_principal(authorization: str | None) -> dict:
    """Resolve a bearer token to a master or per-staff principal.

    Master-password sessions and staff sessions live in separate namespaces and
    use different token digests, so a token minted for one can never be replayed
    as the other. A missing/invalid/expired credential is always a 401 with no
    hint about which kind of token was attempted.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    now = time.time()
    principal = _master_principal(_hash_token(token), now)
    if principal is None:
        principal = _staff_principal(staffauth.hash_session_token(token), now)
    if principal is None:
        raise HTTPException(
            status_code=401, detail="Session expired, please log in again"
        )
    return principal


def require_principal(
    authorization: str | None = Header(default=None),
) -> dict:
    """FastAPI dependency: the full authenticated principal (shape + role)."""
    return resolve_admin_principal(authorization)


def require_admin(authorization: str | None = Header(default=None)) -> str:
    """Validate any admin bearer token and return a stable actor id.

    Master sessions keep returning the session-digest prefix (unchanged audit
    format). Staff sessions return ``staff:<id>`` so the audit log can tell
    which operator acted without a second lookup.
    """
    return resolve_admin_principal(authorization)["actor"]


def _deny(principal: dict, capability: str, request: Request) -> HTTPException:
    """Audit and build a 403 for a capability the principal does not hold."""
    audit.record(
        Audit.ADMIN_ACCESS_DENIED,
        actor_type=principal.get("kind", "admin"),
        actor_id=principal.get("actor"),
        ip=netutil.client_ip(request),
        target_type="capability",
        target_id=capability,
        metadata={"role": principal.get("role")},
    )
    return HTTPException(
        status_code=403,
        detail="Your role does not allow this action",
    )


def require_capability(capability: str):
    """Dependency factory: authenticate **and** authorise one capability.

    Returns the actor id (same format as :func:`require_admin`) so a route can
    both gate and audit with one dependency. Unknown capability names are
    denied by ``permissions.is_allowed``.
    """

    def _dependency(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> str:
        principal = resolve_admin_principal(authorization)
        if not permissions.is_allowed(principal["role"], capability):
            raise _deny(principal, capability, request)
        return principal["actor"]

    return _dependency


def require_capability_principal(capability: str):
    """Like :func:`require_capability` but returns the full principal.

    Staff-directory routes need the principal (not just an actor id) to enforce
    object-level rules that a capability alone cannot express — e.g. a non-master
    operator must not be able to reset or re-role an ``owner`` account.
    """

    def _dependency(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict:
        principal = resolve_admin_principal(authorization)
        if not permissions.is_allowed(principal["role"], capability):
            raise _deny(principal, capability, request)
        return principal

    return _dependency



def require_master(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    """Only the break-glass master-password session may pass.

    The shared password, the login lockout and the role allowlist are the last
    line of defence; a staff admin session must not be able to change them (or
    its own guard) even if its role is ``owner``.
    """
    principal = resolve_admin_principal(authorization)
    if principal["kind"] != "master":
        raise _deny(principal, "master:only", request)
    return principal["actor"]


def require_staff_principal(
    authorization: str | None = Header(default=None),
) -> dict:
    """Dependency for staff self-service routes (e.g. change own password)."""
    principal = resolve_admin_principal(authorization)
    if principal["kind"] != "staff":
        raise HTTPException(
            status_code=403,
            detail="This action is only available to staff accounts",
        )
    return principal


def _record_admin(
    action: str,
    actor: str,
    request: Request | None = None,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Convenience wrapper for auditing an admin action (see audit.py)."""
    if actor.startswith("staff:"):
        actor_type = "staff"
        actor_id = actor.split(":", 1)[1]
    else:
        actor_type = "admin"
        actor_id = actor
    audit.record(
        action,
        actor_type=actor_type,
        actor_id=actor_id,
        ip=_client_ip(request) if request is not None else None,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
    )



class LoginRequest(BaseModel):
    # ``email`` selects a per-staff account. Omitting it keeps the legacy
    # shared master-password login working unchanged (break-glass path).
    password: str = Field(min_length=1, max_length=256)
    email: str | None = Field(default=None, max_length=200)


class LoginResponse(BaseModel):
    token: str


class ChangePasswordRequest(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(max_length=256)


class MessageResponse(BaseModel):
    ok: bool = True
    detail: str | None = None


# --- Auth -------------------------------------------------------------------

def _record_staff_failure(email: str, ip: str, buckets: list[str], now: float, window: float) -> None:
    """Count one failed staff login in every relevant throttle bucket.

    The audit row stores a hash prefix rather than the submitted address: a
    failed-login log is an attractive place to harvest staff emails (PII), and
    the prefix is enough to correlate repeats without retaining the address.
    """
    largest = 0
    for bucket in buckets:
        stamps = [t for t in authstate.throttle_get(bucket) if now - t < window]
        stamps.append(now)
        authstate.throttle_set(bucket, stamps, window)
        largest = max(largest, len(stamps))
    account = hashlib.sha256((email or "").encode()).hexdigest()[:16]
    audit.record(
        Audit.STAFF_LOGIN_FAILED,
        actor_type="anonymous",
        ip=ip,
        metadata={"account": account, "failures": largest},
    )


def _staff_login(
    body: LoginRequest, request: Request, now: float, window: int, max_failures: int
) -> LoginResponse:
    """Email + password login for a per-staff admin account.

    Throttled twice: per client IP (stops one host hammering many accounts) and
    per submitted email (stops a distributed spray against one account). Both
    buckets are created even for unknown emails, so the lockout response itself
    cannot be used to test whether an address exists.
    """
    ip = _client_ip(request)
    email = (body.email or "").strip().lower()
    account_digest = hashlib.sha256(email.encode()).hexdigest()
    buckets = [f"throttle:staff_ip:{ip}", f"throttle:staff_acct:{account_digest}"]

    for bucket in buckets:
        fails = [t for t in authstate.throttle_get(bucket) if now - t < window]
        if len(fails) >= max_failures:
            retry_in = max(1, int(window - (now - min(fails))))
            audit.record(
                Audit.STAFF_LOGIN_LOCKED,
                actor_type="anonymous",
                ip=ip,
                metadata={"retry_in": retry_in, "failures": len(fails)},
            )
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed attempts. Try again in {retry_in}s.",
            )

    member = staffauth.verify_credentials(email, body.password)
    if member is None:
        _record_staff_failure(email, ip, buckets, now, window)
        # Deliberately identical for unknown, disabled and wrong-password:
        # this response must not tell the caller which case it hit.
        raise HTTPException(status_code=401, detail="Invalid email or password")

    for bucket in buckets:
        authstate.throttle_clear(bucket)
    token = staffauth.issue_session(member)
    audit.record(
        Audit.STAFF_LOGIN_OK,
        actor_type="staff",
        actor_id=str(member.get("id") or ""),
        ip=ip,
        metadata={"role": member.get("role")},
    )
    return LoginResponse(token=token)


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request) -> LoginResponse:
    now = time.time()
    window = _login_window()
    max_failures = _login_max_failures()
    authstate.sweep(now)

    if body.email and body.email.strip():
        return _staff_login(body, request, now, window, max_failures)

    # --- Shared master password (break-glass super-user) --------------------
    ip = _client_ip(request)
    bucket = f"throttle:admin:{ip}"
    fails = [t for t in authstate.throttle_get(bucket) if now - t < window]
    if len(fails) >= max_failures:
        retry_in = max(1, int(window - (now - min(fails))))
        audit.record(
            Audit.ADMIN_LOGIN_LOCKED,
            actor_type="anonymous",
            ip=ip,
            metadata={"retry_in": retry_in, "failures": len(fails)},
        )
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {retry_in}s.",
        )

    # Constant-time-ish comparison to reduce trivial timing signal.
    if not _check_password(body.password):
        stamps = [t for t in authstate.throttle_get(bucket) if now - t < window]
        stamps.append(now)
        authstate.throttle_set(bucket, stamps, window)
        audit.record(
            Audit.ADMIN_LOGIN_FAILED,
            actor_type="anonymous",
            ip=ip,
            metadata={"failures": len(stamps)},
        )
        raise HTTPException(status_code=401, detail="Invalid password")

    authstate.throttle_clear(bucket)
    token = secrets.token_urlsafe(32)
    digest = _hash_token(token)
    authstate.put_admin_session(digest, time.time() + TOKEN_TTL)
    audit.record(
        Audit.ADMIN_LOGIN_OK,
        actor_type="admin",
        actor_id=digest[:16],
        ip=ip,
    )
    return LoginResponse(token=token)


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    actor: str = Depends(require_admin),
    authorization: str | None = Header(default=None),
) -> MessageResponse:
    token = authorization.removeprefix("Bearer ").strip()
    # A token can only live in one namespace, but deleting from both is
    # idempotent and makes logout correct without re-resolving the principal.
    authstate.delete_admin_session(_hash_token(token))
    staffauth.revoke_session_token(token)
    _record_admin(
        Audit.STAFF_LOGOUT if actor.startswith("staff:") else Audit.ADMIN_LOGOUT,
        actor,
        request,
    )
    return MessageResponse()


@router.get("/me", dependencies=[Depends(require_admin)])
async def me() -> dict:
    # Kept exactly as before for older clients (and an existing test asserts the
    # exact body). New clients use /session below for role information.
    return {"authenticated": True}


@router.get("/session")
async def session(principal: dict = Depends(require_principal)) -> dict:
    """Current principal: identity, role and the capabilities the UI may show.

    The server still enforces every capability; this is only so the admin
    dashboard can hide tabs the signed-in staff member cannot use.
    """
    return {
        "authenticated": True,
        "kind": principal["kind"],
        "id": principal["id"],
        "role": principal["role"],
        "name": principal["name"],
        "email": principal["email"],
        "capabilities": principal["capabilities"],
    }


@router.post("/password", response_model=MessageResponse)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    actor: str = Depends(require_master),
) -> MessageResponse:
    if not _check_password(body.current):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(body.new) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    if len(body.new) > 256:
        raise HTTPException(status_code=400, detail="New password is too long")
    _set_stored_password(body.new)
    # Recorded without the password (only that it changed).
    _record_admin(Audit.ADMIN_PASSWORD_CHANGED, actor, request)
    return MessageResponse()


@router.post("/staff/password", response_model=MessageResponse)
async def staff_change_password(
    body: StaffChangePassword,
    request: Request,
    principal: dict = Depends(require_staff_principal),
) -> MessageResponse:
    """Self-service password change for a logged-in staff account."""
    member = store.get_staff(principal["id"])
    if member is None:
        raise HTTPException(status_code=401, detail="Account not found")
    try:
        staffauth.change_password(member, body.current, body.new)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit.record(
        Audit.STAFF_PASSWORD_CHANGED,
        actor_type="staff",
        actor_id=str(member.get("id") or ""),
        ip=_client_ip(request),
        metadata={"role": member.get("role")},
    )
    return MessageResponse(detail="Password changed — please sign in again")



@router.post("/reset", response_model=MessageResponse)
async def reset_content(
    request: Request,
    actor: str = Depends(require_capability(permissions.CONFIG_WRITE)),
) -> MessageResponse:
    reset_db()
    engine.reset()
    _record_admin(Audit.ADMIN_CONTENT_RESET, actor, request)
    return MessageResponse(detail="Content reset to defaults")


# --- Markets ----------------------------------------------------------------

# Fields the content/markets editor owns. Engine and settlement fields are
# deliberately excluded: `markets:write` must not be able to forge a payout
# result (that is the separate `markets:resolve` capability's job).
_EDITABLE_MARKET_FIELDS = frozenset(
    {
        "id",
        "cat",
        "tag",
        "q",
        "yes",
        "no",
        "meta",
        "trend",
        "pts",
        "description",
        "end_date",
        "created",
        "volume",
        "liquidity",
        "status",
    }
)
_SETTLEMENT_FIELDS = frozenset(
    {"last_price", "resolved_outcome", "resolved_price", "resolved_ts"}
)


def _save_market(m: MarketInput, *, create_only: bool = False) -> dict:
    """Persist a validated market and refresh the in-process order book.

    The store shares its primary key space with editable content (watch, ticker,
    settings, ...), so a market id must never be allowed to shadow one of those
    keys. `MarketInput` handles shape/range validation; this is the last guard
    before the write.

    Updates merge onto the stored record. The Markets editor deliberately does
    not own engine/settlement fields (`last_price`, `resolved_outcome`,
    `resolved_price`, `resolved_ts`); replacing the whole row would erase them.
    """
    market_id = m.id
    if market_id in RESERVED_KV_KEYS:
        raise HTTPException(status_code=400, detail="That market id is reserved")

    # Mass-assignment guard: reject attempts to write engine/settlement fields
    # through the content endpoint instead of silently dropping them.
    if m.model_fields_set & _SETTLEMENT_FIELDS:
        raise HTTPException(
            status_code=400,
            detail="Settlement fields are managed by the resolve action",
        )

    incoming = {
        key: value
        for key, value in m.model_dump(exclude_unset=True).items()
        if key in _EDITABLE_MARKET_FIELDS
    }

    existing = store.get_market(market_id)
    if create_only and existing is not None:
        raise HTTPException(
            status_code=409, detail="A market with that id already exists"
        )

    if existing is not None and existing.get("status") == "resolved":
        # A settled market is immutable in the only field that matters for
        # payouts. Content edits are still allowed; reopening is not.
        if incoming.get("status") not in (None, "resolved"):
            raise HTTPException(
                status_code=400, detail="Resolved markets cannot be reopened"
            )
        incoming["status"] = "resolved"
    elif incoming.get("status") == "resolved":
        raise HTTPException(
            status_code=400,
            detail="Use the Resolve action to settle a market",
        )

    if existing is None:
        payload = {
            key: value
            for key, value in m.model_dump().items()
            if key in _EDITABLE_MARKET_FIELDS
        }
    else:
        payload = {**existing, **incoming}

    if not payload.get("created"):
        # "Newest" sorting on the marketplace reads this field. Stamp it for
        # API clients that create a market without supplying a listing time.
        payload["created"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    try:
        store.upsert_market(payload)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not save market")
    engine.reseed_market(market_id)
    return payload


@router.post("/markets", response_model=MessageResponse)
async def admin_markets_create(
    m: MarketInput, request: Request,
    actor: str = Depends(require_capability(permissions.MARKETS_WRITE)),
) -> MessageResponse:
    payload = _save_market(m, create_only=True)
    _record_admin(
        Audit.MARKET_CREATED, actor, request,
        target_type="market", target_id=payload["id"],
    )
    return MessageResponse()


@router.put("/markets", response_model=MessageResponse)
async def admin_markets_update(
    m: MarketInput, request: Request,
    actor: str = Depends(require_capability(permissions.MARKETS_WRITE)),
) -> MessageResponse:
    payload = _save_market(m)
    _record_admin(
        Audit.MARKET_UPDATED, actor, request,
        target_type="market", target_id=payload["id"],
    )
    return MessageResponse()


@router.delete("/markets/{market_id}", response_model=MessageResponse)
async def admin_markets_delete(
    market_id: str, request: Request,
    actor: str = Depends(require_capability(permissions.MARKETS_WRITE)),
) -> MessageResponse:
    if market_id in RESERVED_KV_KEYS:
        raise HTTPException(status_code=400, detail="That market id is reserved")
    deleted = store.delete_market(market_id)
    engine.remove_market(market_id)
    _record_admin(
        Audit.MARKET_DELETED, actor, request,
        target_type="market", target_id=market_id,
        metadata={"deleted": deleted},
    )
    return MessageResponse(ok=True, detail=("deleted" if deleted else "not found"))


# --- Watch ------------------------------------------------------------------

@router.put("/watch", response_model=MessageResponse, dependencies=[Depends(require_capability(permissions.CONTENT_WRITE))])
async def admin_watch_replace(items: list[dict]) -> MessageResponse:
    store.replace_watch(items)
    return MessageResponse()


# --- Ticker -----------------------------------------------------------------

@router.put("/ticker", response_model=MessageResponse, dependencies=[Depends(require_capability(permissions.CONTENT_WRITE))])
async def admin_ticker_replace(items: list[dict]) -> MessageResponse:
    store.replace_ticker(items)
    return MessageResponse()


# --- Dashboard / stats / proof ---------------------------------------------

@router.put("/dashboard", response_model=MessageResponse, dependencies=[Depends(require_capability(permissions.CONTENT_WRITE))])
async def admin_dashboard_save(body: dict) -> MessageResponse:
    store.save_dashboard(body)
    return MessageResponse()


@router.put("/stats", response_model=MessageResponse, dependencies=[Depends(require_capability(permissions.CONTENT_WRITE))])
async def admin_stats_save(body: dict) -> MessageResponse:
    store.save_stats(body)
    return MessageResponse()


@router.put("/proof", response_model=MessageResponse, dependencies=[Depends(require_capability(permissions.CONTENT_WRITE))])
async def admin_proof_save(body: dict) -> MessageResponse:
    store.save_proof(body)
    return MessageResponse()


# --- Settings (hero, CTA, steps, footer, section copy) ----------------------
#
# These endpoints are for *site content* only. Operational config lives in the
# same settings store under `config:*` keys, so an unrestricted write here would
# let a content/marketing role escalate into payment/security settings. The
# allowlist mirrors main._PUBLIC_SETTING_KEYS and is enforced on both read and
# write.

CONTENT_SETTING_SECTIONS = (
    "hero",
    "cta",
    "steps",
    "footer",
    "markets_section",
    "dashboard_section",
)


def _content_settings(all_settings: dict) -> dict:
    return {k: all_settings[k] for k in CONTENT_SETTING_SECTIONS if k in all_settings}


@router.get("/settings", dependencies=[Depends(require_capability(permissions.CONTENT_READ))])
async def admin_settings_get() -> dict:
    return _content_settings(get_all_settings())


@router.put("/settings", response_model=MessageResponse, dependencies=[Depends(require_capability(permissions.CONTENT_WRITE))])
async def admin_settings_put(body: dict) -> MessageResponse:
    unknown = sorted(str(k) for k in body if k not in CONTENT_SETTING_SECTIONS)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or protected settings section: {', '.join(unknown)}",
        )
    for key, value in body.items():
        set_setting(key, value)
    return MessageResponse()


@router.put("/settings/{section}", response_model=MessageResponse, dependencies=[Depends(require_capability(permissions.CONTENT_WRITE))])
async def admin_settings_section(section: str, body: dict) -> MessageResponse:
    if section not in CONTENT_SETTING_SECTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown settings section: {section}")
    set_setting(section, body)
    return MessageResponse()


# --- Config (payments, security, staff roles, market resolution) -------------
# Operational controls, kept separate from the site *content* settings above so
# they never flow into the public /api/home bundle (see main._public_settings).

@router.get("/config", dependencies=[Depends(require_capability(permissions.CONFIG_READ))])
async def admin_config_get() -> dict:
    return siteconfig.all_config()


@router.put("/config/{section}", response_model=MessageResponse)
async def admin_config_put(
    section: str, body: dict, request: Request,
    principal: dict = Depends(require_capability_principal(permissions.CONFIG_WRITE)),
) -> MessageResponse:
    # The security fence (login lockout, role allowlist) is master-only even if
    # a staff row carries the `owner` role: a compromised staff session must not
    # be able to weaken its own guard. The master password route is likewise
    # guarded by `require_master`.
    if section in ("security", "staff_roles") and principal.get("kind") != "master":
        raise _deny(principal, "master:only", request)
    actor = principal["actor"]
    try:
        siteconfig.set_config(section, body)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown settings section: {section}")
    except siteconfig.ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Security limits, payment caps and resolution rules are live operational
    # controls, so record which section changed (not the values: they can be
    # large and may contain operator-chosen figures).
    _record_admin(
        Audit.ADMIN_CONFIG_CHANGED, actor, request,
        target_type="config", target_id=section,
        metadata={"keys": sorted(str(k) for k in body.keys())},
    )
    return MessageResponse()


# --- Audit log (read only) ---------------------------------------------------
# The audit log is append-only: there is deliberately no create/update/delete
# endpoint. This is the read side an operator uses during a dispute or an abuse
# investigation. Only the admin gate may read it.

@router.get("/audit", dependencies=[Depends(require_capability(permissions.AUDIT_READ))])
async def admin_audit_list(limit: int = 100, action: str | None = None) -> dict:
    # Cap the page so one request can't pull the whole log into memory.
    limit = max(1, min(limit, 500))
    rows = audit.list_recent(limit=limit, action=action)
    return {"count": audit.count(), "rows": rows}


# --- Users ------------------------------------------------------------------

class AdminUserResetPassword(BaseModel):
    identifier: str  # email address OR Malawian phone number
    new_password: str


@router.get("/users", response_model=list[AdminUserView], dependencies=[Depends(require_capability(permissions.USERS_READ))])
async def admin_users_list() -> list[AdminUserView]:
    # Read the whole payment ledger once, then group it by wallet. Calling
    # `list_payments(wallet_id)` per user would be N+1 queries against the
    # database and make the admin list crawl as the user base grows.
    payments_by_wallet: dict[str, list[dict]] = {}
    for payment in store.list_payments():
        payments_by_wallet.setdefault(payment.get("wallet_id"), []).append(payment)

    views: list[AdminUserView] = []
    for u in store.list_users():
        wallet_id = u["wallet_id"]
        w = engine.wallet_view(wallet_id)
        if w is None:
            # Wallet not loaded into the engine yet. The raw record calls the
            # cashable pool `deposited` (wallet_view renames it `withdrawable`).
            w = store.get_wallet(wallet_id)
        payments = payments_by_wallet.get(wallet_id, [])
        deposits_total = sum(
            float(p.get("amount") or 0.0)
            for p in payments
            if p.get("kind") == "deposit" and p.get("status") == "completed"
        )
        withdrawals_total = sum(
            float(p.get("amount") or 0.0)
            for p in payments
            if p.get("kind") == "withdraw" and p.get("status") == "completed"
        )
        views.append(
            AdminUserView(
                id=u["id"],
                email=u["email"],
                phone=u.get("phone") or None,
                name=u.get("name") or u["id"],
                wallet_id=wallet_id,
                created=float(u.get("created") or 0.0),
                wallet_equity=(w or {}).get("equity"),
                wallet_balance=(w or {}).get("balance"),
                wallet_withdrawable=(w or {}).get("withdrawable", (w or {}).get("deposited")),
                wallet_currency=(w or {}).get("currency") or "MWK",
                positions=len((w or {}).get("positions") or []),
                trades=len((w or {}).get("history") or []),
                deposits_total=round(deposits_total, 2),
                withdrawals_total=round(withdrawals_total, 2),
                pending_payments=sum(1 for p in payments if p.get("status") == "pending"),
            )
        )
    views.sort(key=lambda v: -(v.wallet_equity or 0.0))
    return views


@router.post(
    "/users/reset-password",
    response_model=MessageResponse,
)
async def admin_user_reset_password(
    body: AdminUserResetPassword,
    request: Request,
    actor: str = Depends(require_capability(permissions.USERS_WRITE)),
) -> MessageResponse:
    try:
        user = lookup_user_by_identifier(body.identifier)
    except ValueError:
        raise HTTPException(status_code=404, detail="User not found")
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    user["password"] = hash_password(body.new_password)
    store.upsert_user(user)
    revoke_user_sessions(user["id"])
    # Identifier is recorded so an operator can see *which account* was
    # targeted; the new password never is.
    _record_admin(
        Audit.USER_PASSWORD_RESET, actor, request,
        target_type="user", target_id=user["id"],
        metadata={"identifier": body.identifier},
    )
    return MessageResponse(detail="Password reset — the user must log in again")


@router.delete("/users/{user_id}", response_model=MessageResponse)
async def admin_user_delete(
    user_id: str, request: Request,
    actor: str = Depends(require_capability(permissions.USERS_WRITE)),
) -> MessageResponse:
    deleted = store.delete_user(user_id)
    revoke_user_sessions(user_id)
    _record_admin(
        Audit.USER_DELETED, actor, request,
        target_type="user", target_id=user_id,
        metadata={"deleted": deleted},
    )
    return MessageResponse(ok=deleted, detail=("deleted" if deleted else "not found"))


# --- Staff directory --------------------------------------------------------
#
# Operators of the platform (separate from trader accounts). Every mutation
# emits a `staff` event (see app/staff.py) which main.py broadcasts, so the
# change appears on every open admin panel and the public team page live.
#
# Object-level rules on top of the `staff:*` capabilities:
#   * only a master-password session may grant the `owner` role or touch an
#     `owner` account, otherwise an `admin` operator could reset the owner's
#     password / create a new owner and escalate permanently;
#   * disabling or deleting an account revokes its live sessions immediately;
#   * admin responses are always projected through ``staff.admin_view`` so the
#     password hash and invite-token digest never leave the backend.

def _staff_conflict(exc: ValueError) -> HTTPException:
    # Duplicate identifiers are a conflict (409); everything else is bad input.
    if "already exists" in str(exc):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _forbid_owner_change(principal: dict, member: dict, request: Request) -> None:
    """Non-master operators may not modify an account with the `owner` role."""
    if (
        str(member.get("role") or "").strip().lower() == "owner"
        and principal.get("kind") != "master"
    ):
        raise _deny(principal, "staff:owner_account", request)


def _forbid_owner_grant(principal: dict, role: str | None, request: Request) -> None:
    """Only the break-glass master session may hand out the `owner` role."""
    if str(role or "").strip().lower() == "owner" and principal.get("kind") != "master":
        raise _deny(principal, "staff:grant_owner", request)


@router.get(
    "/staff",
    response_model=list[StaffMember],
    dependencies=[Depends(require_capability(permissions.STAFF_READ))],
)
async def admin_staff_list() -> list[StaffMember]:
    return [StaffMember(**staff.admin_view(s)) for s in staff.list_staff()]


@router.post("/staff", response_model=StaffMember)
async def admin_staff_create(
    body: StaffCreate,
    request: Request,
    principal: dict = Depends(require_capability_principal(permissions.STAFF_WRITE)),
) -> StaffMember:
    _forbid_owner_grant(principal, body.role, request)
    try:
        member = staff.create_staff(body.name, body.email, body.phone, body.role)
    except ValueError as exc:
        raise _staff_conflict(exc)
    _record_admin(
        Audit.STAFF_CREATED, principal["actor"], request,
        target_type="staff", target_id=str(member.get("id") or ""),
        metadata={"role": member.get("role")},
    )
    return StaffMember(**staff.admin_view(member))


def _parsed_upload_rows(body: StaffUpload) -> list[dict]:
    """Best-effort parse of an upload for *authorisation* checks only.

    ``staff.upload`` remains the authoritative parser/validator; this mirrors
    its accepted shapes (JSON text, CSV text, explicit rows) so the route can
    inspect role/email/phone before anything is written. A row we fail to
    recognise simply cannot trigger a grant, and the real parser will reject or
    skip it.
    """
    rows: list[dict] = [r for r in (body.rows or []) if isinstance(r, dict)]
    raw = (body.text or "").strip()
    if body.rows is not None:
        # ``staff.upload`` gives explicit rows precedence and ignores text.
        return rows
    if not raw:
        return rows
    if raw.startswith(("[", "{")):
        try:
            loaded = json.loads(raw)
        except ValueError:
            return rows
        if isinstance(loaded, dict):
            loaded = loaded.get("staff") or loaded.get("rows") or [loaded]
        if isinstance(loaded, list):
            rows.extend(r for r in loaded if isinstance(r, dict))
        return rows
    try:
        table = list(csv.reader(io.StringIO(raw)))
    except csv.Error:
        return rows
    if not table:
        return rows
    header = [cell.strip().lower() for cell in table[0]]
    for line in table[1:]:
        rows.append({header[i]: cell for i, cell in enumerate(line) if i < len(header)})
    return rows


@router.post(
    "/staff/upload",
    response_model=StaffUploadResult,
)
async def admin_staff_upload(
    body: StaffUpload, request: Request,
    principal: dict = Depends(require_capability_principal(permissions.STAFF_WRITE)),
) -> StaffUploadResult:
    if not body.text and not body.rows:
        raise HTTPException(status_code=400, detail="Provide CSV/JSON text or rows")

    # A bulk upload must not become a privilege-escalation / sabotage back door:
    # inspect every requested role and every target account before writing.
    parsed = _parsed_upload_rows(body)
    for row in parsed:
        _forbid_owner_grant(principal, row.get("role"), request)
    if principal.get("kind") != "master":
        for row in parsed:
            email = str(row.get("email") or "").strip().lower()
            phone = str(row.get("phone") or "").strip()
            existing = staff.find_by_email(email) if email else None
            if existing is None and phone:
                existing = staff.find_by_phone(phone)
            if existing is not None:
                _forbid_owner_change(principal, existing, request)

    result = staff.upload(text=body.text, rows=body.rows)
    _record_admin(
        Audit.STAFF_BULK_UPLOADED, principal["actor"], request,
        target_type="staff",
        metadata={"summary": getattr(result, "detail", None)},
    )
    return result


@router.put("/staff/{staff_id}", response_model=StaffMember)
async def admin_staff_update(
    staff_id: str, body: StaffUpdate, request: Request,
    principal: dict = Depends(require_capability_principal(permissions.STAFF_WRITE)),
) -> StaffMember:
    patch = body.model_dump(exclude_unset=True)
    existing = store.get_staff(staff_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    _forbid_owner_change(principal, existing, request)
    if "role" in patch:
        _forbid_owner_grant(principal, patch.get("role"), request)
    try:
        member = staff.update_staff(staff_id, patch)
    except ValueError as exc:
        raise _staff_conflict(exc)
    if member is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    # Deactivation is an immediate lockout, not a flag checked only at login.
    if patch.get("active") is False:
        staffauth.revoke_staff_sessions(staff_id)
    _record_admin(
        Audit.STAFF_UPDATED, principal["actor"], request,
        target_type="staff", target_id=staff_id,
        metadata={"fields": sorted(str(k) for k in patch.keys())},
    )
    return StaffMember(**staff.admin_view(member))


@router.delete("/staff/{staff_id}", response_model=MessageResponse)
async def admin_staff_delete(
    staff_id: str, request: Request,
    principal: dict = Depends(require_capability_principal(permissions.STAFF_WRITE)),
) -> MessageResponse:
    existing = store.get_staff(staff_id)
    if existing is not None:
        _forbid_owner_change(principal, existing, request)
    deleted = staff.delete_staff(staff_id)
    # A deleted row must not leave a live session behind (the session would fail
    # the next request anyway, but revoking makes it immediate and explicit).
    staffauth.revoke_staff_sessions(staff_id)
    _record_admin(
        Audit.STAFF_DELETED, principal["actor"], request,
        target_type="staff", target_id=staff_id,
        metadata={"deleted": deleted},
    )
    return MessageResponse(ok=deleted, detail=("deleted" if deleted else "not found"))


@router.post(
    "/staff/{staff_id}/invite",
    response_model=StaffInviteResult,
)
def admin_staff_invite(
    staff_id: str, request: Request,
    actor: str = Depends(require_capability(permissions.STAFF_WRITE)),
) -> StaffInviteResult:
    try:
        result = staff.invite_staff(staff_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Staff member not found")
    _record_admin(
        Audit.STAFF_INVITED, actor, request,
        target_type="staff", target_id=staff_id,
    )
    return result


# --- Staff credential lifecycle ---------------------------------------------
#
# These are separate from the directory "invite" above (which is a welcome
# notice). Here we mint the single-use set/reset-password link. Only a `staff:
# write` operator may trigger one for somebody else; the recipient proves
# ownership by opening the emailed token, and self-service password change uses
# the authenticated `/staff/password` route instead.

def _active_staff_or_404(staff_id: str) -> dict:
    member = store.get_staff(staff_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    if not member.get("active", True):
        raise HTTPException(status_code=400, detail="Account is disabled")
    return member


@router.post(
    "/staff/{staff_id}/credentials/invite",
    response_model=StaffInviteResult,
)
def admin_staff_credentials_invite(
    staff_id: str, request: Request,
    principal: dict = Depends(require_capability_principal(permissions.STAFF_WRITE)),
) -> StaffInviteResult:
    member = _active_staff_or_404(staff_id)
    _forbid_owner_change(principal, member, request)
    result = staffauth.send_invite(member, reset=False)
    _record_admin(
        Audit.STAFF_CREDENTIALS_INVITED, principal["actor"], request,
        target_type="staff", target_id=staff_id,
    )
    return result


@router.post(
    "/staff/{staff_id}/credentials/reset",
    response_model=StaffInviteResult,
)
def admin_staff_credentials_reset(
    staff_id: str, request: Request,
    principal: dict = Depends(require_capability_principal(permissions.STAFF_WRITE)),
) -> StaffInviteResult:
    member = _active_staff_or_404(staff_id)
    _forbid_owner_change(principal, member, request)
    result = staffauth.send_invite(member, reset=True)
    _record_admin(
        Audit.STAFF_PASSWORD_RESET_SENT, principal["actor"], request,
        target_type="staff", target_id=staff_id,
    )
    return result


# --- Public credential endpoints (no admin session) -------------------------

STAFF_FORGOT_MAX_SENDS = 5


def _send_password_reset_email(member_id: str, ip: str) -> None:
    """Deliver a self-service reset link after the response has been sent.

    Re-reading the row (rather than trusting the request's snapshot) means a
    concurrent delete/disable wins: we never resurrect or email an account that
    was removed while the task was queued. Running the transport off the event
    loop also stops an unauthenticated caller from tying up a worker with a slow
    mail API, and makes the response time independent of whether the address
    exists (no timing oracle for staff enumeration).
    """
    current = store.get_staff(member_id)
    if current is None or not current.get("active", True):
        return
    staffauth.send_invite(current, reset=True)
    audit.record(
        Audit.STAFF_PASSWORD_RESET_SENT,
        actor_type="anonymous",
        ip=ip,
        target_type="staff",
        target_id=member_id,
        metadata={"self_service": True},
    )


def _consume_attempt(
    bucket: str, now: float, window: int, maximum: int
) -> bool:
    """Record one attempt; True when the caller is still under the cap.

    Used for the unauthenticated credential endpoints. Buckets are keyed by IP
    and (for forgot-password) by hashed email, so one host cannot spray a single
    inbox and a botnet cannot hammer one address.
    """
    stamps = [t for t in authstate.throttle_get(bucket) if now - t < window]
    if len(stamps) >= maximum:
        return False
    stamps.append(now)
    authstate.throttle_set(bucket, stamps, window)
    return True


@router.post(
    "/staff/accept-invite",
    response_model=MessageResponse,
)
def admin_staff_accept_invite(
    body: StaffAcceptInvite, request: Request
) -> MessageResponse:
    """Consume a single-use credential link and set the new password."""
    now = time.time()
    window = _login_window()
    ip = _client_ip(request)
    if not _consume_attempt(f"throttle:staff_accept:{ip}", now, window, max(10, _login_max_failures())):
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Try again later.",
        )
    try:
        member = staffauth.accept_invite(body.token, body.password)
    except ValueError as exc:
        # Same generic failure for unknown/expired/used tokens (no oracle).
        raise HTTPException(status_code=400, detail=str(exc))
    audit.record(
        Audit.STAFF_PASSWORD_SET,
        actor_type="staff",
        actor_id=str(member.get("id") or ""),
        ip=ip,
        metadata={"role": member.get("role")},
    )
    return MessageResponse(detail="Password set — you can now sign in.")


@router.post(
    "/staff/forgot",
    response_model=MessageResponse,
)
def admin_staff_forgot(
    body: StaffForgotPassword, request: Request, background: BackgroundTasks
) -> MessageResponse:
    """Email a reset link if the address belongs to an active account.

    The response is identical whether or not the account exists so this endpoint
    cannot be used to enumerate staff. Sends are capped per IP and per email to
    stop it becoming an email-bomb amplifier.
    """
    generic = MessageResponse(
        detail="If that email belongs to a staff account, a reset link has been sent."
    )
    now = time.time()
    window = _login_window()
    ip = _client_ip(request)
    email = (body.email or "").strip().lower()
    if not email:
        return generic
    account_digest = hashlib.sha256(email.encode()).hexdigest()
    if not _consume_attempt(f"throttle:staff_forgot_ip:{ip}", now, window, STAFF_FORGOT_MAX_SENDS):
        return generic
    if not _consume_attempt(
        f"throttle:staff_forgot_acct:{account_digest}", now, window, STAFF_FORGOT_MAX_SENDS
    ):
        return generic

    member = staff.find_by_email(email)
    if member is not None and member.get("active", True):
        background.add_task(
            _send_password_reset_email, str(member.get("id") or ""), ip
        )
    return generic


# --- Broadcast: one announcement to every user with an email --------------------
#
# Runs as a background job with a status endpoint rather than inline: sending is
# one blocking HTTPS round-trip per recipient, so a few thousand users takes
# minutes — far longer than any HTTP client (or proxy) will wait, and doing it
# inline would also stall the event loop for every other request (CWE-400).
#
# Threat model: this is the single most abusable endpoint in the app, because it
# is gated by one shared password and it spends money (Resend quota) and touches
# every user's inbox. Hence: one job at a time, a hard recipient cap, dedupe of
# the recipient list, admin text escaped before it reaches the mail template, and
# finished jobs pruned so the status store cannot grow without bound.

BROADCAST_MAX_RECIPIENTS = 5_000
# Pacing between recipients. Resend allows bursts but a tight loop against
# several thousand addresses is the signature of spam, and can trip provider
# rate limiting that would then also delay transactional OTP mail.
BROADCAST_PAUSE_SECONDS = 0.05
BROADCAST_MAX_JOBS = 50

_broadcast_jobs: dict[str, dict] = {}


class BroadcastRequest(BaseModel):
    subject: str
    body: str


class BroadcastAccepted(BaseModel):
    job_id: str
    total: int


class BroadcastStatus(BaseModel):
    job_id: str
    status: str  # running | done | error
    total: int
    sent: int
    failed: int
    subject: str
    error: str | None = None


def _prune_broadcast_jobs() -> None:
    """Drop finished jobs beyond the retention window, newest kept."""
    if len(_broadcast_jobs) <= BROADCAST_MAX_JOBS:
        return
    finished = sorted(
        (j for j in _broadcast_jobs.items() if j[1]["status"] != "running"),
        key=lambda kv: kv[1]["seq"],
    )
    for job_id, _ in finished[: len(_broadcast_jobs) - BROADCAST_MAX_JOBS]:
        _broadcast_jobs.pop(job_id, None)


async def _run_broadcast(
    job_id: str, recipients: list[str], subject: str, text: str
) -> None:
    """Send one message per recipient. Never raises into the event loop."""
    job = _broadcast_jobs[job_id]
    try:
        for address in recipients:
            # One recipient per message: no shared To/CC/Bcc, which would
            # disclose the user list to every recipient and to any relay.
            ok = await asyncio.to_thread(
                mailer.send_broadcast_email, address, subject, text
            )
            if ok:
                job["sent"] += 1
            else:
                job["failed"] += 1
            if BROADCAST_PAUSE_SECONDS > 0:
                await asyncio.sleep(BROADCAST_PAUSE_SECONDS)
        job["status"] = "done"
    except asyncio.CancelledError:  # pragma: no cover — shutdown path
        job["status"] = "error"
        job["error"] = "Broadcast cancelled"
        raise
    except Exception:  # pragma: no cover — defensive
        logger.exception("Broadcast %s failed", job_id)
        job["status"] = "error"
        # Never surface the exception text to the admin API: it can carry
        # provider URLs, headers or recipient addresses.
        job["error"] = "Broadcast failed"


@router.post("/broadcast", response_model=BroadcastAccepted)
async def admin_broadcast_start(
    body: BroadcastRequest, request: Request,
    actor: str = Depends(require_capability(permissions.BROADCAST_WRITE)),
) -> BroadcastAccepted:
    """Queue one announcement to every user with an email address."""
    subject = " ".join(str(body.subject or "").split())
    text = str(body.body or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="Subject is required")
    if len(subject) > 200:
        raise HTTPException(status_code=400, detail="Subject must be 200 characters or fewer")
    if not text:
        raise HTTPException(status_code=400, detail="Message body is required")
    if len(text) > 20_000:
        raise HTTPException(status_code=400, detail="Message must be 20000 characters or fewer")

    # One job at a time. Without this, a compromised admin session can loop the
    # endpoint and mail the entire user base repeatedly.
    if any(j["status"] == "running" for j in _broadcast_jobs.values()):
        raise HTTPException(status_code=409, detail="A broadcast is already running")

    # Build the recipient list up front so a bad address fails fast rather than
    # halfway through, and so the reported total is the real blast radius.
    job_id = secrets.token_urlsafe(12)
    recipients: list[str] = []
    seen: set[str] = set()
    for user in store.list_users():
        address = str(user.get("email") or "").strip().lower()
        if not address or address in seen:
            continue
        seen.add(address)
        recipients.append(address)
        if len(recipients) >= BROADCAST_MAX_RECIPIENTS:
            logger.warning(
                "Broadcast %s capped at %d recipients", job_id, BROADCAST_MAX_RECIPIENTS
            )
            break
    if not recipients:
        raise HTTPException(
            status_code=400, detail="No users with an email address to broadcast to"
        )

    _broadcast_jobs[job_id] = {
        "job_id": job_id,
        "seq": time.time(),
        "status": "running",
        "total": len(recipients),
        "sent": 0,
        "failed": 0,
        "subject": subject,
        "error": None,
        # Strong reference to the in-flight task. asyncio only keeps weak
        # references to tasks, so without this a broadcast can be garbage
        # collected mid-send and the remaining recipients silently never
        # receive the message. Holding it also lets us join/shutdown cleanly.
        "task": None,
    }
    _prune_broadcast_jobs()
    task = asyncio.create_task(_run_broadcast(job_id, recipients, subject, text))
    _broadcast_jobs[job_id]["task"] = task
    _record_admin(
        Audit.BROADCAST_STARTED, actor, request,
        target_type="broadcast", target_id=job_id,
        metadata={"recipients": len(recipients)},
    )
    return BroadcastAccepted(job_id=job_id, total=len(recipients))


@router.get("/broadcast/{job_id}", response_model=BroadcastStatus, dependencies=[Depends(require_capability(permissions.BROADCAST_WRITE))])
async def admin_broadcast_status(job_id: str) -> BroadcastStatus:
    """Poll progress of a queued broadcast."""
    job = _broadcast_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown broadcast job")
    return BroadcastStatus(
        job_id=job["job_id"],
        status=job["status"],
        total=job["total"],
        sent=job["sent"],
        failed=job["failed"],
        subject=job["subject"],
        error=job["error"],
    )
