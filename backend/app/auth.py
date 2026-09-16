"""User accounts for Ketsa — register / login / session.

Adds real user accounts on top of the simulated-wallet trading flow. Each
registered user owns a wallet (created on registration) whose balance and
positions live in the storage backend, so funds survive restarts.

Auth is intentionally lightweight and mirrors the admin gate in `admin.py`:
  * Passwords are hashed with PBKDF2-HMAC-SHA256 before storage.
  * Sessions are random bearer tokens held in memory (restart invalidates them).
  * All trading/portfolio routes continue to be addressed by wallet id, so the
    existing simulated-wallet experience and the account flow share one engine.
"""

import hashlib
import os
import re
import secrets
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from . import store
from .engine import engine
from .models import User, Wallet

router = APIRouter(prefix="/api/auth", tags=["auth"])

# token digest -> (expiry, user id). Sessions last 30 days, sliding.
_sessions: dict[str, tuple[float, str]] = {}
SESSION_TTL = 30 * 24 * 3600

# Login throttling — per-email failed-attempt window (env-tunable so tests can
# force short windows). Guards the (public, per-IP limited) login endpoint
# against password guessing without locking out honest guests on a shared IP.
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 900
_login_attempts: dict[str, list[float]] = {}

_SALT_LEN = 16
_PBKDF2_ITER = 100_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _throttle_window() -> int:
    try:
        return int(os.getenv("KETSA_AUTH_LOCKOUT_SECONDS", str(LOGIN_WINDOW_SECONDS)))
    except ValueError:
        return LOGIN_WINDOW_SECONDS


def _throttle_max() -> int:
    try:
        return int(os.getenv("KETSA_AUTH_MAX_FAILURES", str(LOGIN_MAX_FAILURES)))
    except ValueError:
        return LOGIN_MAX_FAILURES


def _prune_attempts(now: float, window: int) -> None:
    """Drop expired attempt logs so the tracker can't grow unboundedly."""
    if len(_login_attempts) > 2_000:
        for email in [e for e, ts in _login_attempts.items() if not ts]:
            _login_attempts.pop(email, None)
        for email, ts in list(_login_attempts.items()):
            ts[:] = [t for t in ts if now - t < window]
            if not ts:
                _login_attempts.pop(email, None)


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 hash, `salt_hex$hash_hex` (shared with admin)."""
    salt = os.urandom(_SALT_LEN)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITER)
    return f"{salt.hex()}${dk.hex()}"


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current: str
    new: str


class AuthResponse(BaseModel):
    token: str
    user: User
    wallet: Wallet


def _hash_password(password: str) -> str:
    return hash_password(password)


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITER)
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(dk.hex(), hash_hex)


def _hash_token(token: str) -> str:
    return hashlib.sha256(("ketsa:user:" + token).encode()).hexdigest()


def _issue_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[_hash_token(token)] = (time.time() + SESSION_TTL, user_id)
    return token


def _revoke_session(token: str) -> None:
    _sessions.pop(_hash_token(token), None)


def revoke_user_sessions(user_id: str) -> None:
    """Drop every live session for a user (password change / admin reset)."""
    for digest in [d for d, (_, uid) in _sessions.items() if uid == user_id]:
        _sessions.pop(digest, None)


def _user_public(user: dict) -> User:
    return User(
        id=user["id"],
        email=user["email"],
        name=user["name"],
        wallet_id=user["wallet_id"],
        created=user["created"],
    )


def _wallet_for_user(user: dict) -> Wallet:
    w = engine.connect_wallet(user["wallet_id"], name=user["name"])
    return Wallet(**w)


def require_user(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: resolve the bearer token to the authenticated user."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ").strip()
    digest = _hash_token(token)
    now = time.time()
    entry = _sessions.get(digest)
    if entry is None or entry[0] < now:
        _sessions.pop(digest, None)
        raise HTTPException(status_code=401, detail="Session expired, please log in again")
    _sessions[digest] = (now + SESSION_TTL, entry[1])  # sliding window
    user = store.get_user(entry[1])
    if user is None:
        raise HTTPException(status_code=401, detail="Account not found")
    return user


def resolve_optional_user(authorization: str | None) -> dict | None:
    """Resolve a bearer token to a user, or None for guest (unauthenticated)
    requests.

    An *absent* header means the caller is a guest using a simulated wallet.
    A *present but invalid* header still raises 401 so bad credentials can't
    silently downgrade an account request to guest access.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return require_user(authorization)


# --- Routes -----------------------------------------------------------------

@router.post("/register", response_model=AuthResponse)
async def register(body: RegisterRequest) -> AuthResponse:
    name = body.name.strip()
    email = body.email.strip().lower()

    if not name or len(name) < 2:
        raise HTTPException(status_code=400, detail="Name must be at least 2 characters")
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if store.get_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    wallet = engine.connect_wallet(name=name)
    user = {
        "id": email,
        "email": email,
        "name": name,
        "password": _hash_password(body.password),
        "wallet_id": wallet["id"],
        "created": time.time(),
    }
    store.upsert_user(user)
    engine.notify(
        wallet["id"],
        "system",
        "Welcome to Ketsa",
        f"Your account is live with {wallet['balance']:.0f} {wallet['currency']}. "
        "Trade a market to get started.",
    )

    token = _issue_session(user["id"])
    return AuthResponse(token=token, user=_user_public(user), wallet=Wallet(**wallet))


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest) -> AuthResponse:
    email = body.email.strip().lower()
    now = time.time()
    window = _throttle_window()
    max_failures = _throttle_max()
    _prune_attempts(now, window)

    fails = [t for t in _login_attempts.get(email, []) if now - t < window]
    if len(fails) >= max_failures:
        retry_in = max(1, int(window - (now - min(fails))))
        raise HTTPException(
            status_code=429,
            detail=f"Too many attempts. Try again in {retry_in}s.",
        )

    user = store.get_user_by_email(email)
    if user is None or not _verify_password(body.password, user.get("password", "")):
        _login_attempts.setdefault(email, []).append(now)
        _prune_attempts(now, window)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    _login_attempts.pop(email, None)
    token = _issue_session(user["id"])
    return AuthResponse(token=token, user=_user_public(user), wallet=_wallet_for_user(user))


@router.post("/logout")
async def logout(authorization: str | None = Header(default=None)) -> dict[str, bool]:
    if authorization and authorization.startswith("Bearer "):
        _revoke_session(authorization.removeprefix("Bearer ").strip())
    return {"ok": True}


@router.post("/password", response_model=AuthResponse)
async def change_password(
    body: ChangePasswordRequest, user: dict = Depends(require_user)
) -> AuthResponse:
    """Change the authenticated account's password (all other sessions revoked)."""
    if not _verify_password(body.current, user.get("password", "")):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(body.new) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    user["password"] = hash_password(body.new)
    store.upsert_user(user)
    revoke_user_sessions(user["id"])
    token = _issue_session(user["id"])  # keep the current session on a fresh token
    return AuthResponse(token=token, user=_user_public(user), wallet=_wallet_for_user(user))


@router.get("/me", response_model=AuthResponse)
async def me(user: dict = Depends(require_user)) -> AuthResponse:
    return AuthResponse(token="", user=_user_public(user), wallet=_wallet_for_user(user))