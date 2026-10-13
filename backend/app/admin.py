"""Protected admin API for managing the Ketsa site content.

Access is gated by a single shared admin password (`KETSA_ADMIN_PASSWORD`).
On login the client receives a server-issued token which must be supplied on
every subsequent request via the `Authorization: Bearer <token>` header.

Tokens are random and their digests live in the shared auth store
(authstate.py), so a restart or redeploy does not log the admin out and every
worker validates the same token. The admin gate is still a simple, low-overhead
safeguard for a marketing site, not a multi-user RBAC system.

Because one password guards the whole site (it can delete accounts, reset
any user's password, and resolve markets — which settles real money), the
login endpoint is brute-force throttled per client IP exactly like the user
account login in `auth.py`. Without that, the shared password was reachable
at the global request rate limit (~120/min/IP), which is an online-guessing
budget rather than a control.
"""

import asyncio
import hashlib
import logging
import os
import secrets
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from . import authstate, mailer, store
from .auth import hash_password, lookup_user_by_identifier, revoke_user_sessions
from .engine import engine
from .models import AdminUserView
from .storage import get_all_settings, get_setting, reset_db, set_setting

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
LOGIN_MAX_FAILURES = 10
LOGIN_LOCKOUT_SECONDS = 900


def _login_window() -> int:
    try:
        return int(os.getenv("KETSA_ADMIN_LOCKOUT_SECONDS", str(LOGIN_LOCKOUT_SECONDS)))
    except ValueError:
        return LOGIN_LOCKOUT_SECONDS


def _login_max_failures() -> int:
    try:
        return int(os.getenv("KETSA_ADMIN_MAX_FAILURES", str(LOGIN_MAX_FAILURES)))
    except ValueError:
        return LOGIN_MAX_FAILURES


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


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


def require_admin(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ").strip()
    digest = _hash_token(token)
    now = time.time()
    expiry = authstate.get_admin_session(digest)
    if expiry is None or expiry < now:
        # Purge expired digest for hygiene.
        authstate.delete_admin_session(digest)
        raise HTTPException(status_code=401, detail="Session expired, please log in again")
    authstate.touch_admin_session(digest, now + TOKEN_TTL)  # sliding window


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str


class ChangePasswordRequest(BaseModel):
    current: str
    new: str


class MessageResponse(BaseModel):
    ok: bool = True
    detail: str | None = None


# --- Auth -------------------------------------------------------------------

@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request) -> LoginResponse:
    # Per-IP lockout. The admin password is the single key to the whole site
    # (user management, password resets, market resolution/settlement), so
    # unlimited guessing is not acceptable. A success clears the counter.
    now = time.time()
    window = _login_window()
    max_failures = _login_max_failures()
    authstate.sweep(now)

    ip = _client_ip(request)
    bucket = f"throttle:admin:{ip}"
    fails = [t for t in authstate.throttle_get(bucket) if now - t < window]
    if len(fails) >= max_failures:
        retry_in = max(1, int(window - (now - min(fails))))
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {retry_in}s.",
        )

    # Constant-time-ish comparison to reduce trivial timing signal.
    if not _check_password(body.password):
        stamps = [t for t in authstate.throttle_get(bucket) if now - t < window]
        stamps.append(now)
        authstate.throttle_set(bucket, stamps, window)
        raise HTTPException(status_code=401, detail="Invalid password")

    authstate.throttle_clear(bucket)
    token = secrets.token_urlsafe(32)
    authstate.put_admin_session(_hash_token(token), time.time() + TOKEN_TTL)
    return LoginResponse(token=token)


@router.post("/logout", response_model=MessageResponse, dependencies=[Depends(require_admin)])
def logout(authorization: str | None = Header(default=None)) -> MessageResponse:
    token = authorization.removeprefix("Bearer ").strip()
    authstate.delete_admin_session(_hash_token(token))
    return MessageResponse()


@router.get("/me", dependencies=[Depends(require_admin)])
async def me() -> dict:
    return {"authenticated": True}


@router.post("/password", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def change_password(body: ChangePasswordRequest) -> MessageResponse:
    if not _check_password(body.current):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(body.new) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    _set_stored_password(body.new)
    return MessageResponse()


@router.post("/reset", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def reset_content() -> MessageResponse:
    reset_db()
    engine.reset()
    return MessageResponse(detail="Content reset to defaults")


# --- Markets ----------------------------------------------------------------

@router.post("/markets", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_markets_create(m: dict) -> MessageResponse:
    try:
        store.upsert_market(m)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not save market")
    engine.reseed_market(m["id"])
    return MessageResponse()


@router.put("/markets", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_markets_update(m: dict) -> MessageResponse:
    try:
        store.upsert_market(m)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not save market")
    engine.reseed_market(m["id"])
    return MessageResponse()


@router.delete("/markets/{market_id}", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_markets_delete(market_id: str) -> MessageResponse:
    deleted = store.delete_market(market_id)
    engine.remove_market(market_id)
    return MessageResponse(ok=True, detail=("deleted" if deleted else "not found"))


# --- Watch ------------------------------------------------------------------

@router.put("/watch", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_watch_replace(items: list[dict]) -> MessageResponse:
    store.replace_watch(items)
    return MessageResponse()


# --- Ticker -----------------------------------------------------------------

@router.put("/ticker", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_ticker_replace(items: list[dict]) -> MessageResponse:
    store.replace_ticker(items)
    return MessageResponse()


# --- Dashboard / stats / proof ---------------------------------------------

@router.put("/dashboard", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_dashboard_save(body: dict) -> MessageResponse:
    store.save_dashboard(body)
    return MessageResponse()


@router.put("/stats", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_stats_save(body: dict) -> MessageResponse:
    store.save_stats(body)
    return MessageResponse()


@router.put("/proof", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_proof_save(body: dict) -> MessageResponse:
    store.save_proof(body)
    return MessageResponse()


# --- Settings (hero, CTA, steps, footer, section copy) ----------------------

@router.get("/settings", dependencies=[Depends(require_admin)])
async def admin_settings_get() -> dict:
    return get_all_settings()


@router.put("/settings", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_settings_put(body: dict) -> MessageResponse:
    for key, value in body.items():
        set_setting(key, value)
    return MessageResponse()


@router.put("/settings/{section}", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_settings_section(section: str, body: dict) -> MessageResponse:
    set_setting(section, body)
    return MessageResponse()


# --- Users ------------------------------------------------------------------

class AdminUserResetPassword(BaseModel):
    identifier: str  # email address OR Malawian phone number
    new_password: str


@router.get("/users", response_model=list[AdminUserView], dependencies=[Depends(require_admin)])
async def admin_users_list() -> list[AdminUserView]:
    views: list[AdminUserView] = []
    for u in store.list_users():
        w = engine.wallet_view(u["wallet_id"])
        if w is None:
            w = store.get_wallet(u["wallet_id"])
        views.append(
            AdminUserView(
                id=u["id"],
                email=u["email"],
                phone=u.get("phone") or None,
                name=u.get("name") or u["id"],
                wallet_id=u["wallet_id"],
                created=float(u.get("created") or 0.0),
                wallet_equity=(w or {}).get("equity"),
                wallet_balance=(w or {}).get("balance"),
                positions=len((w or {}).get("positions") or []),
                trades=len((w or {}).get("history") or []),
            )
        )
    views.sort(key=lambda v: -(v.wallet_equity or 0.0))
    return views


@router.post(
    "/users/reset-password",
    response_model=MessageResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_user_reset_password(body: AdminUserResetPassword) -> MessageResponse:
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
    return MessageResponse(detail="Password reset — the user must log in again")


@router.delete("/users/{user_id}", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_user_delete(user_id: str) -> MessageResponse:
    deleted = store.delete_user(user_id)
    revoke_user_sessions(user_id)
    return MessageResponse(ok=deleted, detail=("deleted" if deleted else "not found"))


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


@router.post("/broadcast", response_model=BroadcastAccepted, dependencies=[Depends(require_admin)])
async def admin_broadcast_start(body: BroadcastRequest) -> BroadcastAccepted:
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
    return BroadcastAccepted(job_id=job_id, total=len(recipients))


@router.get("/broadcast/{job_id}", response_model=BroadcastStatus, dependencies=[Depends(require_admin)])
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
