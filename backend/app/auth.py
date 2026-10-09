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

import asyncio
import hashlib
import logging
import os
import re
import secrets
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from . import mailer, social, store
from .engine import engine
from .models import User, Wallet

# Security-relevant failures are logged with detail and returned to the client
# as a generic message, so provider internals never reach the browser.
logger = logging.getLogger("ketsa.auth")

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
# Redeemed tickets are popped, but a ticket whose callback is never completed
# (closed tab, back button, dropped mobile connection) would otherwise sit here
# forever: the TTL is only ever checked at redemption, never used to evict. On
# a long-running process that is an unbounded leak reachable by anyone who can
# call /social/login and simply never finish (CWE-401 / CWE-770). So entries
# are swept on issue, and hard-capped so a burst inside one TTL cannot blow up.
MAX_PENDING_TICKETS = 5_000


def _prune_tickets(now: float) -> None:
    """Evict expired tickets, then hard-cap the dict if it is still too big."""
    for t in [t for t, (exp, _) in _tickets.items() if exp < now]:
        _tickets.pop(t, None)
    if len(_tickets) > MAX_PENDING_TICKETS:
        for t in sorted(_tickets, key=lambda k: _tickets[k][0])[: len(_tickets) - MAX_PENDING_TICKETS]:
            _tickets.pop(t, None)

# Login throttling — per-identifier (email or phone) failed-attempt window
# (env-tunable so tests can force short windows). Guards the (public,
# per-IP limited) login endpoint against password guessing without locking
# out honest guests on a shared IP.
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 900
_login_attempts: dict[str, list[float]] = {}

# Passwordless sign-in by emailed code.
#
# Two independent brakes, because they stop different attacks:
#   * the per-address OTP resend cooldown (inside _issue_otp) stops one mailbox
#     being flooded;
#   * the per-IP request window below stops an attacker rotating through a list
#     of victim addresses at the public per-IP rate limit, which would turn the
#     app into an open mail relay and burn the Resend daily quota (spam-relay
#     abuse / resource exhaustion, CWE-441 + CWE-770).
CODE_REQUEST_MAX = 5
CODE_REQUEST_WINDOW_SECONDS = 900
_code_requests: dict[str, list[float]] = {}


def _code_request_max() -> int:
    try:
        return int(os.getenv("KETSA_CODE_REQUEST_MAX", str(CODE_REQUEST_MAX)))
    except ValueError:
        return CODE_REQUEST_MAX


def _code_request_window() -> int:
    try:
        return int(os.getenv("KETSA_CODE_REQUEST_WINDOW", str(CODE_REQUEST_WINDOW_SECONDS)))
    except ValueError:
        return CODE_REQUEST_WINDOW_SECONDS


def _prune_code_requests(now: float, window: int) -> None:
    """Drop expired request stamps so the per-IP tracker can't grow unbounded."""
    for ip, stamps in list(_code_requests.items()):
        kept = [t for t in stamps if now - t < window]
        if kept:
            _code_requests[ip] = kept
        else:
            _code_requests.pop(ip, None)

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


# --- One-time passcode (OTP) engine ------------------------------------------
# Codes are 6 random digits whose SHA-256 digest is stored (never plaintext),
# single-use, TTL'd, capped at a few attempts, with a resend cooldown. Every
# code is keyed by a scope string that also carries its payload:
#   "signup:<email>" -> {name, password_hash} waiting for verification
#   "reset:<user_id>" -> {} (user already exists)
# All thresholds are env-tunable so tests can force short windows.
_OTP_TTL_SECONDS = 10 * 60
_OTP_MAX_ATTEMPTS = 5
_OTP_RESEND_SECONDS = 60
_otps: dict[str, dict] = {}


class _OtpCooldown(Exception):
    """Raised when a new code for the same scope was issued too recently."""


def _otp_ttl() -> int:
    try:
        return int(os.getenv("KETSA_OTP_TTL_SECONDS", str(_OTP_TTL_SECONDS)))
    except ValueError:
        return _OTP_TTL_SECONDS


def _otp_max_attempts() -> int:
    try:
        return int(os.getenv("KETSA_OTP_MAX_ATTEMPTS", str(_OTP_MAX_ATTEMPTS)))
    except ValueError:
        return _OTP_MAX_ATTEMPTS


def _otp_resend_cooldown() -> int:
    try:
        return int(os.getenv("KETSA_OTP_RESEND_SECONDS", str(_OTP_RESEND_SECONDS)))
    except ValueError:
        return _OTP_RESEND_SECONDS


def _issue_otp(key: str, payload: dict | None = None) -> str:
    """Issue a fresh 6-digit code for ``key``, carrying ``payload``.

    An existing code for the same key inherits its payload unless a new one is
    given, so resends never lose the pending registration data. Raises
    ``_OtpCooldown`` when a code for this key was issued moments ago.
    """
    now = time.time()
    # Opportunistic sweep: drop anything that expired so a resend can start
    # fresh, and the map can never grow unbounded.
    for stale in [k for k, v in _otps.items() if v["expires"] < now]:
        _otps.pop(stale, None)
    previous = _otps.get(key)
    if previous and now - previous["issued"] < _otp_resend_cooldown():
        raise _OtpCooldown()
    code = f"{secrets.randbelow(1_000_000):06d}"
    _otps[key] = {
        "hash": hashlib.sha256(code.encode("ascii")).hexdigest(),
        "issued": now,
        "expires": now + _otp_ttl(),
        "attempts": 0,
        "payload": payload if payload is not None else (previous or {}).get("payload"),
    }
    return code


def _consume_otp(key: str, code: str) -> dict | None:
    """Validate and burn a one-time passcode.

    Returns the consumed entry on success (entry removed — single use, even
    in memory; callers read ``entry.get("payload")``), or None for any
    failure: unknown key, expired code, too many attempts (code dead, entry
    kept so a resend can recover the payload), or a wrong code (entry kept,
    attempts bumped). Comparison is constant-time.
    """
    entry = _otps.get(key)
    if entry is None:
        return None
    now = time.time()
    if now > entry["expires"] or entry["attempts"] > _otp_max_attempts():
        return None
    entry["attempts"] += 1
    if entry["attempts"] > _otp_max_attempts():
        return None
    validate = hashlib.sha256((code or "").strip().encode("ascii")).hexdigest()
    if not secrets.compare_digest(entry["hash"], validate):
        return None
    return _otps.pop(key, None)


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


class VerifyEmailRequest(BaseModel):
    email: str
    otp: str


class ResendOtpRequest(BaseModel):
    email: str


class ForgotPasswordRequest(BaseModel):
    identifier: str  # email address OR Malawian phone number


class ResetPasswordRequest(BaseModel):
    email: str
    otp: str
    new_password: str


class LoginRequest(BaseModel):
    identifier: str  # email address OR Malawian phone number
    password: str


class LoginCodeRequest(BaseModel):
    """Ask for a sign-in code to be emailed. Email addresses only."""

    identifier: str


class VerifyLoginCodeRequest(BaseModel):
    email: str
    otp: str


class ChangePasswordRequest(BaseModel):
    current: str
    new: str


class SocialSessionRequest(BaseModel):
    ticket: str


class AuthResponse(BaseModel):
    token: str
    user: User
    wallet: Wallet


class PendingVerifyResponse(BaseModel):
    """202 returned by /register for email signups awaiting OTP verification."""
    ok: bool = True
    pending: bool = True
    email: str


def _create_account(*, identifier: str, email: str, phone: str, name: str, password_hash: str) -> dict:
    """Create the account record + wallet and send the welcome notification.

    ``identifier`` is the record id (email or canonical phone); ``email`` and
    ``phone`` are the displayed contact fields (one of them empty).
    """
    wallet = engine.connect_wallet(name=name)
    user = {
        "id": identifier,
        "email": email,
        "phone": phone,
        "name": name,
        "password": password_hash,
        "wallet_id": wallet["id"],
        "created": time.time(),
    }
    store.upsert_user(user)
    engine.notify(
        wallet["id"],
        "system",
        "Welcome to Ketsa",
        "Your account is ready. Deposit via mobile money (wandePay) to fund "
        "your wallet, then trade any open market.",
    )
    return user


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
    now = time.time()
    _prune_tickets(now)
    ticket = secrets.token_urlsafe(32)
    _tickets[ticket] = (now + SSO_TICKET_TTL, token)
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

@router.post("/register", response_model=AuthResponse | PendingVerifyResponse)
async def register(
    body: RegisterRequest, response: Response
) -> AuthResponse | PendingVerifyResponse:
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
        # Proof-of-inbox first: no account, no wallet until the emailed code
        # comes back. Pending signups expire with the OTP.
        try:
            code = _issue_otp(
                f"signup:{email}",
                payload={"name": name, "password_hash": _hash_password(body.password)},
            )
        except _OtpCooldown:
            raise HTTPException(
                status_code=429,
                detail="A verification code was recently sent to this email. Try again shortly.",
            )
        sent = mailer.send_otp_email(email, code, "signup", _otp_ttl() // 60, name=name)
        if not sent:
            # The code never left the building. Discard it so the user can retry
            # at once instead of being locked out by the resend cooldown for a
            # code they never received, and tell the caller the truth rather
            # than routing them to a verify step that can never be completed —
            # that dead end is indistinguishable from a broken button.
            # This path is taken identically for every address, so it leaks
            # nothing beyond the existence disclosure the 409 above already makes.
            _otps.pop(f"signup:{email}", None)
            raise HTTPException(
                status_code=502,
                detail="We couldn't send the verification email. Please try again in a moment.",
            )
        response.status_code = 202  # pending — account appears only after OTP
        return PendingVerifyResponse(email=email)
    else:
        email, phone = "", identifier
        if store.get_user_by_phone(phone):
            raise HTTPException(status_code=409, detail="An account with this phone number already exists")
        user = _create_account(
            identifier=identifier,
            email=email,
            phone=phone,
            name=name,
            password_hash=_hash_password(body.password),
        )
        token = _issue_session(user["id"])
        return AuthResponse(token=token, user=_user_public(user), wallet=_wallet_for_user(user))


@router.post("/register/verify", response_model=AuthResponse)
async def verify_email(body: VerifyEmailRequest) -> AuthResponse:
    """Complete an email signup with the emailed one-time passcode."""
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if store.get_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    payload = _consume_otp(f"signup:{email}", body.otp.strip())
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired verification code")
    payload = payload.get("payload") or {}
    name = str(payload.get("name") or email.split("@")[0])
    password_hash = str(payload.get("password_hash") or "")
    user = _create_account(
        identifier=email,
        email=email,
        phone="",
        name=name,
        password_hash=password_hash,
    )
    token = _issue_session(user["id"])
    return AuthResponse(token=token, user=_user_public(user), wallet=_wallet_for_user(user))


@router.post("/register/resend", response_model=PendingVerifyResponse)
async def resend_register_otp(body: ResendOtpRequest, response: Response) -> PendingVerifyResponse:
    """Re-email the signup code for a pending registration (cooldown-gated)."""
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if _otps.get(f"signup:{email}") is None:
        raise HTTPException(status_code=400, detail="No pending registration for this email")
    try:
        code = _issue_otp(f"signup:{email}")
    except _OtpCooldown:
        raise HTTPException(
            status_code=429,
            detail="A verification code was recently sent to this email. Try again shortly.",
        )
    entry = _otps.get(f"signup:{email}", {})
    payload = entry.get("payload") or {}
    sent = mailer.send_otp_email(
        email, code, "signup", _otp_ttl() // 60, name=str(payload.get("name") or "")
    )
    if not sent:
        # Report the failure rather than pretending the code is on its way.
        # State is left as-is on purpose: the pending signup (and its payload)
        # must survive, and clearing the cooldown here would let a caller loop
        # this endpoint against the provider without limit. The honest message
        # costs the user one cooldown window; losing their signup would cost
        # them the whole form.
        raise HTTPException(
            status_code=502,
            detail="We couldn't send the verification email. Please try again in a moment.",
        )
    response.status_code = 202
    return PendingVerifyResponse(email=email)


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest) -> dict:
    """Email a reset code when the identifier belongs to an account.

    Always answers 200 ``{"ok": true}`` — for unknown accounts, phone
    identifiers (email-only self-service), invalid input and rate-limited
    resends alike — so the endpoint cannot be used to enumerate users.
    """
    try:
        kind, identifier = normalize_identifier(body.identifier)
    except ValueError:
        return {"ok": True}
    user = None
    if kind == "email":
        user = store.get_user_by_email(identifier)
    if user is None:
        return {"ok": True}
    try:
        code = _issue_otp(f"reset:{user['id']}")
    except _OtpCooldown:
        return {"ok": True}  # silently swallowed on purpose (no oracle)
    # Deliberately ignore the delivery result. This send only happens when the
    # identifier matched an account, so surfacing a failure here would answer
    # "does this account exist?" with a different status code — a textbook
    # enumeration oracle (CWE-203). The uniform 200 is the security property;
    # delivery problems are reported server-side instead (see mailer.py).
    mailer.send_otp_email(identifier, code, "reset", _otp_ttl() // 60)
    return {"ok": True}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest) -> dict:
    """Validate the emailed reset code and set a new password.

    All existing sessions are revoked. Unknown emails and invalid/expired
    codes produce the same 401, so the endpoint reveals nothing about which
    addresses have accounts.
    """
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    user = store.get_user_by_email(email)
    key = f"reset:{user['id']}" if user is not None else None
    # Identical failure for unknown account vs bad/expired/used code.
    if key is None or _consume_otp(key, body.otp.strip()) is None:
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    user["password"] = hash_password(body.new_password)
    store.upsert_user(user)
    revoke_user_sessions(user["id"])
    return {"ok": True}


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


# --- Passwordless sign-in by emailed code -------------------------------------
# Deliberately additive: the password login above is untouched, so a phone-only
# account, a user who prefers a password, and any existing client keep working.


@router.post("/login/code")
async def request_login_code(body: LoginCodeRequest, request: Request) -> dict:
    """Email a one-time sign-in code so a user can log in without a password.

    Always answers ``200 {"ok": true}`` — for unknown accounts, phone
    identifiers, malformed input, invalid addresses and cooldown-suppressed
    resends alike — so this endpoint cannot be used to enumerate which email
    addresses have accounts (CWE-203 / user enumeration).

    The 429 below is keyed on the *client IP*, not the account, so it leaks
    nothing about the address being mailed.
    """
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = _code_request_window()
    _prune_code_requests(now, window)
    hits = _code_requests.setdefault(ip, [])
    if len(hits) >= _code_request_max():
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in code requests. Try again later.",
        )
    hits.append(now)

    try:
        kind, identifier = normalize_identifier(body.identifier)
    except ValueError:
        return {"ok": True}
    # Phone accounts are password-only: this path is email-delivery and a phone
    # account has no email to deliver to.
    if kind != "email":
        return {"ok": True}
    user = store.get_user_by_email(identifier)
    if user is None:
        return {"ok": True}
    try:
        code = _issue_otp(f"login:{user['id']}")
    except _OtpCooldown:
        return {"ok": True}  # silently swallowed on purpose (no oracle)
    # Delivery result deliberately discarded — same reasoning as forgot-password
    # above: this send only runs when the account exists, so a distinct failure
    # status would turn the endpoint into a user-enumeration oracle (CWE-203).
    mailer.send_otp_email(
        identifier, code, "login", _otp_ttl() // 60, name=str(user.get("name") or "")
    )
    return {"ok": True}


@router.post("/login/code/verify", response_model=AuthResponse)
async def verify_login_code(body: VerifyLoginCodeRequest) -> AuthResponse:
    """Exchange a valid emailed sign-in code for a normal session.

    The code is bound to the user id that requested it and burns on use, so it
    cannot be replayed. Unknown email and bad/expired/used code produce the
    same 401, matching /reset-password and revealing nothing about accounts.
    """
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    user = store.get_user_by_email(email)
    key = f"login:{user['id']}" if user is not None else None
    if key is None or _consume_otp(key, body.otp.strip()) is None:
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    # A successful code is proof enough; clear any password-failure streak so a
    # user who fumbled the form isn't left throttled after signing in.
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
        nonce, code_verifier = social.take_state(state or "")
    except social.SocialError as e:
        # State failures are safe to show: they carry no provider detail.
        raise HTTPException(status_code=400, detail=str(e))
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    try:
        # Auth0 exchange + JWKS fetch + verification are blocking network
        # calls — run them off the event loop so one slow Google response
        # can't stall every request on this process (F-08).
        tokens = await asyncio.to_thread(social.exchange_code, code, code_verifier)
    except social.SocialError as e:
        # Auth0's error text can name internal hosts and describe the tenant's
        # configuration, so it is logged rather than returned to the browser.
        logger.warning("auth0 code exchange failed: %s", e)
        raise HTTPException(
            status_code=502, detail="Could not complete sign-in with Google. Please try again."
        )
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=502, detail="Could not complete sign-in with Google. Please try again.")
    try:
        claims = await asyncio.to_thread(social.verify_id_token, id_token, nonce)
    except social.SocialError as e:
        # Same here: a rejected token can be a real attack (wrong connection,
        # forged signature), and the reason belongs in the log, not the URL bar.
        logger.warning("auth0 id token rejected: %s", e)
        raise HTTPException(status_code=400, detail="Google sign-in could not be verified. Please try again.")

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
    _prune_tickets(time.time())
    entry = _tickets.pop(body.ticket, None)
    if entry is None:
        raise HTTPException(status_code=400, detail="Invalid or expired login — please try again")
    exp, token = entry
    if exp < time.time():
        raise HTTPException(status_code=400, detail="Login expired — please try again")
    user = resolve_token(token)
    return AuthResponse(token=token, user=_user_public(user), wallet=_wallet_for_user(user))