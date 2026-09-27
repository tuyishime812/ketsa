"""Protected admin API for managing the Ketsa site content.

Access is gated by a single shared admin password (`KETSA_ADMIN_PASSWORD`).
On login the client receives a server-issued token which must be supplied on
every subsequent request via the `Authorization: Bearer <token>` header.

Tokens are random and held in memory, so restarting the server invalidates
them (a fresh login is required). This is intentional: the admin gate is a
simple, low-overhead safeguard for a marketing site, not a multi-user RBAC
system.

Because one password guards the whole site (it can delete accounts, reset
any user's password, and resolve markets — which settles real money), the
login endpoint is brute-force throttled per client IP exactly like the user
account login in `auth.py`. Without that, the shared password was reachable
at the global request rate limit (~120/min/IP), which is an online-guessing
budget rather than a control.
"""

import hashlib
import os
import secrets
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from . import store
from .auth import hash_password, lookup_user_by_identifier, revoke_user_sessions
from .engine import engine
from .models import AdminUserView
from .storage import get_all_settings, get_setting, reset_db, set_setting

router = APIRouter(prefix="/api/admin", tags=["admin"])

# token -> expiry (unix seconds). Tokens last 12h.
_tokens: dict[str, float] = {}
TOKEN_TTL = 12 * 3600

# Password hashing (PBKDF2-HMAC-SHA256) for the optional stored admin password.
_SALT_LEN = 16
_PBKDF2_ITER = 100_000

# Brute-force throttle for POST /login, keyed by client IP.
LOGIN_MAX_FAILURES = 10
LOGIN_LOCKOUT_SECONDS = 900
_login_attempts: dict[str, list[float]] = {}


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


def _prune_login_attempts(now: float, window: int) -> None:
    """Drop expired attempt logs so the tracker can't grow unboundedly."""
    for ip, stamps in list(_login_attempts.items()):
        kept = [t for t in stamps if now - t < window]
        if kept:
            _login_attempts[ip] = kept
        else:
            _login_attempts.pop(ip, None)


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
    expiry = _tokens.get(digest)
    if expiry is None or expiry < now:
        # Purge expired digest for hygiene.
        _tokens.pop(digest, None)
        raise HTTPException(status_code=401, detail="Session expired, please log in again")
    _tokens[digest] = now + TOKEN_TTL  # sliding window


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
async def login(body: LoginRequest, request: Request) -> LoginResponse:
    # Per-IP lockout. The admin password is the single key to the whole site
    # (user management, password resets, market resolution/settlement), so
    # unlimited guessing is not acceptable. A success clears the counter.
    now = time.time()
    window = _login_window()
    max_failures = _login_max_failures()
    _prune_login_attempts(now, window)

    ip = _client_ip(request)
    fails = [t for t in _login_attempts.get(ip, []) if now - t < window]
    if len(fails) >= max_failures:
        retry_in = max(1, int(window - (now - min(fails))))
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {retry_in}s.",
        )

    # Constant-time-ish comparison to reduce trivial timing signal.
    if not _check_password(body.password):
        fails.append(now)
        _login_attempts[ip] = fails
        raise HTTPException(status_code=401, detail="Invalid password")

    _login_attempts.pop(ip, None)
    token = secrets.token_urlsafe(32)
    _tokens[_hash_token(token)] = time.time() + TOKEN_TTL
    return LoginResponse(token=token)


@router.post("/logout", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def logout(authorization: str | None = Header(default=None)) -> MessageResponse:
    token = authorization.removeprefix("Bearer ").strip()
    _tokens.pop(_hash_token(token), None)
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
