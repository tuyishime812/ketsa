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
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from . import social, store
from .engine import engine
from .models import User, Wallet

router = APIRouter(prefix="/api/auth", tags=["auth"])

# token digest -> (expiry, user id). Sessions last 30 days, sliding.
_sessions: dict[str, tuple[float, str]] = {}
SESSION_TTL = 30 * 24 * 3600

# Auth0 social login: single-use, short-lived tickets that carry a freshly
# issued session token from the backend callback to the frontend /auth/callback
# page. The ticket appears in a URL, so it must be unguessable, single-use and
# short-lived (60s) — the real session token never travels in a URL.
_tickets: dict[str, tuple[float, str]] = {}
SSO_TICKET_TTL = 60

# Login throttling — per-identifier (email or phone) failed-attempt window
# (env-tunable so tests can force short windows). Guards the (public,
# per-IP limited) login endpoint against password guessing without locking
# out honest guests on a shared IP.
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 900
_login_attempts: dict[str, list[float]] = {}

_SALT_LEN = 16
_PBKDF2_ITER = 100_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Malawian mobile numbers, canonical form: 9 digits starting with 8 or 9
# (TNM: 098/099, Airtel: 088/099). Stored/compared without leading 0 or
# country code — matching wandePay's normalize_number() so a registered phone
# can be reused directly for deposits/payouts later.
_PHONE_RE = re.compile(r"^[89]\d{8}$")


def normalize_phone(raw: str) -> str:
    """Normalize a Malawian phone to canonical 9-digit form ('991234567').

    Accepts '0991234567', '+265991234567', '265991234567', '00265...',
    spaced/dashed variants. Raises ValueError for anything else.
    """
    digits = re.sub(r"[\s\-().]", "", (raw or "").strip())
    if digits.startswith("+"):
        digits = digits[1:]
    if not digits.isdigit() or not digits:
        raise ValueError("not a valid phone number")
    if digits.startswith("00265"):
        digits = digits[5:]
    elif digits.startswith("265") and len(digits) == 12:
        digits = digits[3:]
    digits = digits.lstrip("0")
    if not _PHONE_RE.match(digits):
        raise ValueError("not a valid Malawian phone number")
    return digits


def normalize_identifier(identifier: str) -> tuple[str, str]:
    """Classify and canonicalize a user-supplied identifier.

    Returns ``("email", lowercased_email)`` or ``("phone", canonical_9_digits)``.
    Raises ``ValueError`` for anything that is neither.
    """
    raw = (identifier or "").strip()
    if _EMAIL_RE.match(raw):
        return "email", raw.lower()
    return "phone", normalize_phone(raw)


def lookup_user_by_identifier(identifier: str) -> dict | None:
    """Resolve an email or phone identifier to a user record (or None)."""
    kind, normalized = normalize_identifier(identifier)
    if kind == "email":
        return store.get_user_by_email(normalized)
    return store.get_user_by_phone(normalized)


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
    identifier: str  # email address OR Malawian phone number
    password: str


class LoginRequest(BaseModel):
    identifier: str  # email address OR Malawian phone number
    password: str


class ChangePasswordRequest(BaseModel):
    current: str
    new: str


class SocialSessionRequest(BaseModel):
    ticket: str


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


def _issue_sso_ticket(token: str) -> str:
    """Single-use ticket that hands a session token to the frontend callback."""
    ticket = secrets.token_urlsafe(32)
    _tickets[ticket] = (time.time() + SSO_TICKET_TTL, token)
    return ticket


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
        phone=user.get("phone") or None,
        name=user["name"],
        wallet_id=user["wallet_id"],
        created=user["created"],
    )


def _wallet_for_user(user: dict) -> Wallet:
    w = engine.connect_wallet(user["wallet_id"], name=user["name"])
    return Wallet(**w)


def resolve_token(token: str) -> dict:
    """Resolve a raw bearer token to the authenticated user record."""
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


def require_user(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: resolve the bearer token to the authenticated user."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return resolve_token(authorization.removeprefix("Bearer ").strip())


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
    try:
        kind, identifier = normalize_identifier(body.identifier)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Enter a valid email address or Malawian phone number (e.g. 0991 234 567)",
        )

    if not name or len(name) < 2:
        raise HTTPException(status_code=400, detail="Name must be at least 2 characters")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    if kind == "email":
        email, phone = identifier, ""
        if store.get_user_by_email(email):
            raise HTTPException(status_code=409, detail="An account with this email already exists")
    else:
        email, phone = "", identifier
        if store.get_user_by_phone(phone):
            raise HTTPException(status_code=409, detail="An account with this phone number already exists")

    wallet = engine.connect_wallet(name=name)
    user = {
        "id": identifier,
        "email": email,
        "phone": phone,
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
    try:
        kind, identifier = normalize_identifier(body.identifier)
    except ValueError:
        # Uniform 401: don't let format errors distinguish account state.
        raise HTTPException(
            status_code=401,
            detail="Invalid email/phone or password",
        )
    now = time.time()
    window = _throttle_window()
    max_failures = _throttle_max()
    _prune_attempts(now, window)

    fails = [t for t in _login_attempts.get(identifier, []) if now - t < window]
    if len(fails) >= max_failures:
        retry_in = max(1, int(window - (now - min(fails))))
        raise HTTPException(
            status_code=429,
            detail=f"Too many attempts. Try again in {retry_in}s.",
        )

    user = store.get_user_by_email(identifier) if kind == "email" else store.get_user_by_phone(identifier)
    if user is None or not _verify_password(body.password, user.get("password", "")):
        _login_attempts.setdefault(identifier, []).append(now)
        _prune_attempts(now, window)
        raise HTTPException(status_code=401, detail="Invalid email/phone or password")

    _login_attempts.pop(identifier, None)
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


# --- Auth0 social login (Google) ---------------------------------------------

def _realize_social_user(claims: dict) -> dict:
    """Find or create the Ketsa user matching an Auth0 id-token payload.

    Account linking rules (in order):
      1. Auth0 subject (``sub``) matches an existing user -> reuse it.
      2. Verified email matches a user that has NO Auth0 subject yet -> link
         the login (Google proved ownership of that inbox). A user that
         already carries a *different* Auth0 subject is rejected — never
         silently re-link an email to a second provider account.
      3. Otherwise create a fresh account (with a wallet).
    """
    sub = str(claims.get("sub") or "").strip()
    if not sub:
        raise HTTPException(status_code=400, detail="Auth0 id token has no subject")
    email = str(claims.get("email") or "").strip().lower()
    name = str(claims.get("name") or "").strip() or (email or sub).split("@")[0]
    verified = claims.get("email_verified") is True

    user = store.get_user_by_auth0_sub(sub)
    if user is None and email and verified:
        existing = store.get_user_by_email(email)
        if existing is not None:
            other = existing.get("auth0_sub")
            if other and other != sub:
                raise HTTPException(
                    status_code=409,
                    detail="This email is already linked to another Google account",
                )
            user = existing

    if user is None:
        # New account. Prefer the email as the record id, but NEVER let the
        # id collide with an existing record: an unverified email claim (or any
        # leftover collision) falls back to the Auth0 subject, otherwise a
        # Google upsert could overwrite a password account's row (wiping its
        # password hash and orphaning its wallet).
        uid = email if (email and verified) else sub
        if store.get_user(uid) is not None:
            uid = sub
        wallet = engine.connect_wallet(name=name)
        user = {
            "id": uid,
            "email": email,
            "phone": "",
            "name": name,
            "password": None,  # Google-created accounts log in via Auth0 only
            "wallet_id": wallet["id"],
            "auth0_sub": sub,
            "created": time.time(),
        }
        store.upsert_user(user)
        engine.notify(
            wallet["id"],
            "system",
            "Welcome to Ketsa",
            f"Your account is live with wallet {wallet['id'][:8]}.",
        )
    else:
        if not user.get("auth0_sub"):
            user["auth0_sub"] = sub
            store.upsert_user(user)
        # Make sure the wallet is live in the engine after a restart.
        engine.connect_wallet(user["wallet_id"], name=user.get("name") or name)
    return user


@router.post("/social/login", response_model=dict)
async def social_login_start() -> dict:
    """Start an Auth0 Google login; returns the /authorize URL to follow."""
    if not social.configured():
        raise HTTPException(status_code=503, detail="Google login is not configured on this server")
    return {"url": social.begin_login()}


@router.get("/social/callback")
async def social_login_callback(
    code: str | None = None, state: str | None = None
) -> RedirectResponse:
    """Auth0 redirect target: validate state, exchange the code, verify the
    id token, then hand the browser a single-use ticket for the frontend.

    The Ketsa session token itself never appears in this redirect — only the
    60-second, single-use ticket does.
    """
    if not social.configured():
        raise HTTPException(status_code=503, detail="Google login is not configured on this server")
    try:
        nonce = social.take_state(state or "")
    except social.SocialError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    try:
        tokens = social.exchange_code(code)
    except social.SocialError as e:
        raise HTTPException(status_code=502, detail=str(e))
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=502, detail="Auth0 did not return an id token")
    try:
        claims = social.verify_id_token(id_token, nonce)
    except social.SocialError as e:
        raise HTTPException(status_code=400, detail=str(e))

    user = _realize_social_user(claims)
    token = _issue_session(user["id"])
    ticket = _issue_sso_ticket(token)
    return RedirectResponse(
        url=f"{social.frontend_url()}/auth/callback?ticket={ticket}",
        status_code=302,
    )


@router.post("/social/session", response_model=AuthResponse)
async def social_session(body: SocialSessionRequest) -> AuthResponse:
    """Exchange the single-use ticket for the Ketsa session (token + user + wallet)."""
    entry = _tickets.pop(body.ticket, None)
    if entry is None:
        raise HTTPException(status_code=400, detail="Invalid or expired login — please try again")
    exp, token = entry
    if exp < time.time():
        raise HTTPException(status_code=400, detail="Login expired — please try again")
    user = resolve_token(token)
    return AuthResponse(token=token, user=_user_public(user), wallet=_wallet_for_user(user))