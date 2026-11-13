"""User accounts for Ketsa — register / login / session.

Adds real user accounts on top of the simulated-wallet trading flow. Each
registered user owns a wallet (created on registration) whose balance and
positions live in the storage backend, so funds survive restarts.

Auth is intentionally lightweight and mirrors the admin gate in `admin.py`:
  * Passwords are hashed with PBKDF2-HMAC-SHA256 before storage.
  * Sessions are random bearer tokens whose digests live in the storage backend
    (authstate.py), so they survive restarts and are shared across workers.
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

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from . import authstate, mailer, netutil, social, store
from . import audit
from .engine import engine
from .models import User, Wallet

# Security-relevant failures are logged with detail and returned to the client
# as a generic message, so provider internals never reach the browser.
logger = logging.getLogger("ketsa.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Sessions last 30 days, sliding. The digest -> (expiry, user id) map lives in
# the storage backend (authstate.py), so a restart or redeploy keeps everyone
# logged in and every worker shares one view. The sliding refresh is throttled
# to one write per SESSION_SLIDE_INTERVAL so authenticated requests don't each
# pay for a database write.
SESSION_TTL = 30 * 24 * 3600
SESSION_SLIDE_INTERVAL = 3600

# Auth0 social login: single-use, short-lived tickets that identify the user to
# the frontend /auth/callback page. The ticket appears in a URL, so it must be
# unguessable, single-use and short-lived (60s) — no session material ever
# travels in a URL, and the ticket stores a user id, never a token.
SSO_TICKET_TTL = 60
# Redeemed tickets are popped, but a ticket whose callback is never completed
# (closed tab, back button, dropped mobile connection) would otherwise sit here
# forever: the TTL is only ever checked at redemption, never used to evict. On
# a long-running process that is an unbounded leak reachable by anyone who can
# call /social/login and simply never finish (CWE-401 / CWE-770). So entries
# are swept on issue, and hard-capped so a burst inside one TTL cannot blow up.
MAX_PENDING_TICKETS = 5_000


def _prune_tickets(now: float) -> None:
    """Evict expired tickets, then hard-cap the store if it is still too big."""
    authstate.sweep(now)
    pending = authstate.ticket_count()
    if pending > MAX_PENDING_TICKETS:
        for ticket in authstate.oldest_tickets(pending - MAX_PENDING_TICKETS):
            authstate.delete_ticket(ticket)

# Login throttling — per-identifier (email or phone) failed-attempt window
# (env-tunable so tests can force short windows). Guards the (public,
# per-IP limited) login endpoint against password guessing without locking
# out honest guests on a shared IP. Stamps live in the shared store so a
# redeploy doesn't reset the fence and every worker counts the same failures.
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 900

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

_SALT_LEN = 16
_PBKDF2_ITER = 100_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Malawian mobile numbers, canonical form: 9 digits starting with 8 or 9
# (TNM: 098/099, Airtel: 088/099). Stored/compared without leading 0 or
# country code — matching payments.normalize_number(), which accepts this form
# so a registered phone can be reused directly for deposits/payouts later.
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
#   "reset:<user_id>" -> {} (user already exists)
#   "login:<user_id>" -> {} (user already exists)
# All thresholds are env-tunable so tests can force short windows.
_OTP_TTL_SECONDS = 10 * 60
_OTP_MAX_ATTEMPTS = 5
_OTP_RESEND_SECONDS = 60


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
    # fresh, and the store can never grow unbounded.
    authstate.sweep(now)
    previous = authstate.get_otp(key)
    if previous and now - previous["issued"] < _otp_resend_cooldown():
        raise _OtpCooldown()
    code = f"{secrets.randbelow(1_000_000):06d}"
    authstate.put_otp(
        key,
        hashlib.sha256(code.encode("ascii")).hexdigest(),
        payload if payload is not None else (previous or {}).get("payload"),
        issued=now,
        expires=now + _otp_ttl(),
    )
    return code


def _consume_otp(key: str, code: str) -> dict | None:
    """Validate and burn a one-time passcode.

    Returns the consumed entry on success (entry removed — single use, even
    across processes; callers read ``entry.get("payload")``), or None for any
    failure: unknown key, expired code, too many attempts (code dead, entry
    kept so a resend can recover the payload), or a wrong code (entry kept,
    attempts bumped). The code digest comparison happens inside the store's
    atomic consume.
    """
    now = time.time()
    max_attempts = _otp_max_attempts()
    validate = hashlib.sha256((code or "").strip().encode("ascii")).hexdigest()
    entry = authstate.consume_otp(key, validate, max_attempts=max_attempts, now=now)
    if entry is not None:
        return entry
    # Wrong code / expired / dead: count the failed guess so the cap means a
    # cap. The entry is kept so a resend can recover its payload.
    authstate.bump_otp_attempts(key, max_attempts=max_attempts, now=now)
    return None


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


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 hash, `salt_hex$hash_hex` (shared with admin)."""
    salt = os.urandom(_SALT_LEN)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITER)
    return f"{salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of ``password`` against a stored PBKDF2 hash.

    Public wrapper around the same verification used by user login so the
    staff-admin path hashes identically. Malformed/legacy hashes fail closed.
    """
    return _verify_password(password, stored)



class RegisterRequest(BaseModel):
    name: str = Field(max_length=100)
    identifier: str = Field(max_length=320)  # email address OR Malawian phone number
    # Upper bound matters: PBKDF2 cost scales with input length, so an
    # unbounded password is a cheap CPU-exhaustion vector on a public endpoint
    # (CWE-400). 256 chars is far beyond any real password.
    password: str = Field(max_length=256)
    # Optional referral code of the inviting user. Accepted at registration only;
    # a user cannot change who referred them later.
    referral_code: str | None = Field(default=None, max_length=32)


class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(max_length=320)  # email address OR Malawian phone number


class ResetPasswordRequest(BaseModel):
    email: str = Field(max_length=320)
    otp: str = Field(max_length=16)
    new_password: str = Field(max_length=256)


class LoginRequest(BaseModel):
    identifier: str = Field(max_length=320)  # email address OR Malawian phone number
    password: str = Field(max_length=256)


class LoginCodeRequest(BaseModel):
    """Ask for a sign-in code to be emailed. Email addresses only."""

    identifier: str = Field(max_length=320)


class VerifyLoginCodeRequest(BaseModel):
    email: str = Field(max_length=320)
    otp: str = Field(max_length=16)


class ChangePasswordRequest(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(max_length=256)


class SocialSessionRequest(BaseModel):
    ticket: str = Field(max_length=256)


class AuthResponse(BaseModel):
    token: str
    user: User
    wallet: Wallet


def _create_account(
    *,
    identifier: str,
    email: str,
    phone: str | None,
    name: str,
    password_hash: str,
    referred_by: str | None = None,
) -> dict:
    """Create the account record + wallet and send the welcome notification.

    ``identifier`` is the record id (email or canonical phone); ``email`` and
    ``phone`` are the displayed contact fields. For email signups the phone is
    stored as JSON ``null`` — never ``""``: an empty string is a *value*, so it
    would occupy the unique ``ketsa_users_phone_idx`` slot and make every
    subsequent email-only signup collide with the first one (Postgres treats
    NULLs as distinct, but not ``''``). Phone signups keep ``email=""`` because
    ``User.email`` is a required string and email has no unique index.
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
        "referred_by": referred_by,
        "referral_earnings": 0.0,
        "referral_count": 0,
    }
    ensure_referral_code(user)
    store.upsert_user(user)

    if referred_by:
        referrer = store.get_user(referred_by)
        if referrer is not None:
            referrer["referral_count"] = int(referrer.get("referral_count") or 0) + 1
            store.upsert_user(referrer)
            engine.notify(
                referrer.get("wallet_id", ""),
                "system",
                "New referral",
                f"{name} joined with your referral link. You'll earn 20% of their losing trade stake when markets they bet on resolve against them.",
            )

    engine.notify(
        wallet["id"],
        "system",
        "Welcome to Ketsa",
        "Your account is ready. Deposit via mobile money (PayChangu) to fund "
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
    now = time.time()
    token = secrets.token_urlsafe(32)
    authstate.put_session(
        _hash_token(token), user_id, issued=now, expires=now + SESSION_TTL
    )
    return token


def _issue_sso_ticket(user_id: str) -> str:
    """Single-use ticket that lets the frontend claim a fresh session."""
    now = time.time()
    _prune_tickets(now)
    ticket = secrets.token_urlsafe(32)
    authstate.put_ticket(ticket, user_id, issued=now, expires=now + SSO_TICKET_TTL)
    return ticket


def _revoke_session(token: str) -> None:
    authstate.delete_session(_hash_token(token))


def revoke_user_sessions(user_id: str) -> None:
    """Drop every live session for a user (password change / admin reset)."""
    authstate.delete_sessions_for_user(user_id)


def _generate_referral_code() -> str:
    # Short, human-friendly, uppercase code. 8 chars from a 32-char alphabet.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def ensure_referral_code(user: dict) -> str:
    """Return the user's referral code, minting and persisting one if missing.

    Existing accounts created before referrals were introduced get a code on
    first access so every user can share an invite link.
    """
    code = str(user.get("referral_code") or "").strip().upper()
    if code:
        user["referral_code"] = code
        return code
    for _ in range(20):
        candidate = _generate_referral_code()
        if store.get_user_by_referral_code(candidate) is None:
            user["referral_code"] = candidate
            store.upsert_user(user)
            return candidate
    # Extremely unlikely collision storm; fall back to a longer random code.
    candidate = secrets.token_hex(6).upper()
    user["referral_code"] = candidate
    store.upsert_user(user)
    return candidate


def _user_public(user: dict) -> User:
    return User(
        id=user["id"],
        email=user.get("email", ""),
        phone=user.get("phone") or None,
        name=user.get("name", "Trader"),
        wallet_id=user["wallet_id"],
        referral_code=ensure_referral_code(user),
        referred_by=user.get("referred_by") or None,
        referral_earnings=float(user.get("referral_earnings") or 0.0),
        referral_count=int(user.get("referral_count") or 0),
        created=float(user.get("created") or 0.0),
    )


def _wallet_for_user(user: dict) -> Wallet:
    w = engine.connect_wallet(user["wallet_id"], name=user["name"])
    return Wallet(**w)


def resolve_token(token: str) -> dict:
    """Resolve a raw bearer token to the authenticated user record."""
    digest = _hash_token(token)
    now = time.time()
    entry = authstate.get_session(digest)
    if entry is None:
        raise HTTPException(status_code=401, detail="Session expired, please log in again")
    expiry, user_id = entry
    if expiry < now:
        authstate.delete_session(digest)
        raise HTTPException(status_code=401, detail="Session expired, please log in again")
    # Sliding window, but write at most once per SESSION_SLIDE_INTERVAL so
    # authenticated requests don't each trigger a database write.
    if expiry - now < SESSION_TTL - SESSION_SLIDE_INTERVAL:
        authstate.touch_session(digest, now + SESSION_TTL)
    user = store.get_user(user_id)
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
def register(body: RegisterRequest) -> AuthResponse:
    """Create an account + wallet immediately (no email-verification step).

    Both email and phone signups answer 200 with a full session. Note this
    means an email address is *not* proven to belong to the registrant; the
    duplicate check below is the only claim on an address.
    """
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

    referred_by: str | None = None
    if body.referral_code:
        ref_code = body.referral_code.strip().upper()
        if ref_code:
            referrer = store.get_user_by_referral_code(ref_code)
            if referrer is not None and referrer.get("id") != identifier:
                referred_by = referrer.get("id")
            # Unknown/self codes are ignored rather than blocking registration.

    if kind == "email":
        email, phone = identifier, None
        if store.get_user_by_email(email):
            raise HTTPException(status_code=409, detail="An account with this email already exists")
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
        referred_by=referred_by,
    )
    token = _issue_session(user["id"])
    return AuthResponse(token=token, user=_user_public(user), wallet=_wallet_for_user(user))


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest) -> dict:
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
def reset_password(body: ResetPasswordRequest, request: Request) -> dict:
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
    # A recovery-code reset is a security-relevant event (account takeover
    # signal if unexpected); record it against the account, never the password.
    audit.record(
        audit.Actions.USER_PASSWORD_CHANGED,
        actor_type="user",
        actor_id=str(user["id"]),
        ip=netutil.client_ip(request),
        target_type="user",
        target_id=str(user["id"]),
        metadata={"via": "reset_code"},
    )
    return {"ok": True}


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest) -> AuthResponse:
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
    authstate.sweep(now)

    bucket = f"throttle:login:{identifier}"
    fails = [t for t in authstate.throttle_get(bucket) if now - t < window]
    if len(fails) >= max_failures:
        retry_in = max(1, int(window - (now - min(fails))))
        raise HTTPException(
            status_code=429,
            detail=f"Too many attempts. Try again in {retry_in}s.",
        )

    user = store.get_user_by_email(identifier) if kind == "email" else store.get_user_by_phone(identifier)
    if user is None or not _verify_password(body.password, user.get("password", "")):
        stamps = [t for t in authstate.throttle_get(bucket) if now - t < window]
        stamps.append(now)
        authstate.throttle_set(bucket, stamps, window)
        raise HTTPException(status_code=401, detail="Invalid email/phone or password")

    authstate.throttle_clear(bucket)
    token = _issue_session(user["id"])
    return AuthResponse(token=token, user=_user_public(user), wallet=_wallet_for_user(user))


# --- Passwordless sign-in by emailed code -------------------------------------
# Deliberately additive: the password login above is untouched, so a phone-only
# account, a user who prefers a password, and any existing client keep working.


@router.post("/login/code")
def request_login_code(body: LoginCodeRequest, request: Request) -> dict:
    """Email a one-time sign-in code so a user can log in without a password.

    Always answers ``200 {"ok": true}`` — for unknown accounts, phone
    identifiers, malformed input, invalid addresses and cooldown-suppressed
    resends alike — so this endpoint cannot be used to enumerate which email
    addresses have accounts (CWE-203 / user enumeration).

    The 429 below is keyed on the *client IP*, not the account, so it leaks
    nothing about the address being mailed.
    """
    ip = netutil.client_ip(request)
    now = time.time()
    window = _code_request_window()
    authstate.sweep(now)
    bucket = f"throttle:code:{ip}"
    hits = [t for t in authstate.throttle_get(bucket) if now - t < window]
    if len(hits) >= _code_request_max():
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in code requests. Try again later.",
        )
    hits.append(now)
    authstate.throttle_set(bucket, hits, window)

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
def verify_login_code(body: VerifyLoginCodeRequest) -> AuthResponse:
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
    authstate.throttle_clear(f"throttle:login:{email}")
    token = _issue_session(user["id"])
    return AuthResponse(token=token, user=_user_public(user), wallet=_wallet_for_user(user))


@router.post("/logout")
def logout(authorization: str | None = Header(default=None)) -> dict[str, bool]:
    if authorization and authorization.startswith("Bearer "):
        _revoke_session(authorization.removeprefix("Bearer ").strip())
    return {"ok": True}


@router.post("/password", response_model=AuthResponse)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: dict = Depends(require_user),
) -> AuthResponse:
    """Change the authenticated account's password (all other sessions revoked)."""
    if not _verify_password(body.current, user.get("password", "")):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(body.new) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    user["password"] = hash_password(body.new)
    store.upsert_user(user)
    revoke_user_sessions(user["id"])
    audit.record(
        audit.Actions.USER_PASSWORD_CHANGED,
        actor_type="user",
        actor_id=str(user["id"]),
        ip=netutil.client_ip(request),
        target_type="user",
        target_id=str(user["id"]),
        metadata={"via": "authenticated_change"},
    )
    token = _issue_session(user["id"])  # keep the current session on a fresh token
    return AuthResponse(token=token, user=_user_public(user), wallet=_wallet_for_user(user))


@router.get("/me", response_model=AuthResponse)
def me(user: dict = Depends(require_user)) -> AuthResponse:
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
            # NULL, not "": see _create_account — an empty string would claim
            # the unique phone slot shared by every phone-less account.
            "phone": None,
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
def social_login_start() -> dict:
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

    # _realize_social_user reads/writes users and _issue_sso_ticket writes the
    # shared store: keep both off the event loop so Google's latency (already
    # threaded above) is the only blocking this handler does.
    user = await asyncio.to_thread(_realize_social_user, claims)
    ticket = await asyncio.to_thread(_issue_sso_ticket, user["id"])
    return RedirectResponse(
        url=f"{social.frontend_url()}/auth/callback?ticket={ticket}",
        status_code=302,
    )


@router.post("/social/session", response_model=AuthResponse)
def social_session(body: SocialSessionRequest) -> AuthResponse:
    """Exchange the single-use ticket for a fresh Ketsa session."""
    _prune_tickets(time.time())
    entry = authstate.take_ticket(body.ticket)
    if entry is None:
        raise HTTPException(status_code=400, detail="Invalid or expired login — please try again")
    if entry["expires"] < time.time() or not entry.get("user_id"):
        raise HTTPException(status_code=400, detail="Login expired — please try again")
    user = store.get_user(str(entry["user_id"]))
    if user is None:
        raise HTTPException(status_code=400, detail="Login expired — please try again")
    token = _issue_session(user["id"])
    return AuthResponse(token=token, user=_user_public(user), wallet=_wallet_for_user(user))