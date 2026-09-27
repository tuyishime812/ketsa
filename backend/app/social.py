"""Auth0 social login (Google) — server-to-server integration.

The browser never talks to Auth0 directly: the Ketsa backend owns the whole
flow so no third-party JavaScript or SDK ships in the frontend bundle.

Flow (Authorization Code):
    1. POST /api/auth/social/login      -> backend builds the Auth0 /authorize
                                           URL (state + nonce) and returns it.
    2. The browser follows it; the user authenticates on Auth0's hosted page
       (Google as the only enabled connection).
    3. Auth0 302s back to /api/auth/social/callback?code=...&state=...
       - state is validated against the server-side store (login-CSRF guard).
       - the code is exchanged for tokens at /oauth/token using the client
         secret (confidential-client flow — PKCE not required).
       - the id token is verified: RS256 signature against the Auth0 JWKS,
         issuer, audience (client id), expiry and the nonce.
    4. The backend issues a Ketsa session token, wraps it in a short-lived
       single-use ticket and redirects the browser to the frontend.
    5. POST /api/auth/social/session {ticket} -> Ketsa session (same bearer
       token contract as email/password login).

No webhook, no browser-exposed tokens, no Auth0 JS SDK. Everything below is
pure stdlib + PyJWT (cryptography for RS256).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import jwt  # PyJWT (RS256 verification)

# --- constants ---------------------------------------------------------------

STATE_TTL_SECONDS = 600          # how long an /authorize state+nonce is valid
JWKS_CACHE_TTL = 3600            # re-fetch Auth0 signing keys at most hourly
DEFAULT_CONNECTION = "google-oauth2"  # Auth0 connection to force at /authorize
SCOPE = "openid profile email"

# Hard cap on in-flight login attempts. Entries expire, but a burst inside a
# single TTL window would otherwise be unbounded — the same cap the password
# login-attempt tracker uses (CWE-770).
MAX_PENDING_STATES = 5_000

# --- configuration -----------------------------------------------------------

_DEFAULTS = {
    "KETSA_PUBLIC_BASE_URL": "http://127.0.0.1:8000",  # backend origin (Auth0 callback target)
    "KETSA_FRONTEND_URL": "http://localhost:3000",     # where the ticket redirect lands
}


def _env(key: str) -> str:
    return os.getenv(key, "").strip()


def domain() -> str:
    return _env("KETSA_AUTH0_DOMAIN").rstrip("/")


def connection() -> str:
    """The Auth0 connection this site authenticates against.

    Tunable so adding a second provider (Apple, Facebook, an enterprise
    connection) is one env change rather than a code change — and, more
    importantly, so the *callback* guard below can never disagree with what
    /authorize asked for: both read this.
    """
    return _env("KETSA_AUTH0_CONNECTION") or DEFAULT_CONNECTION


def expected_sub_prefix() -> str:
    """The subject prefix that proves which connection minted a token.

    Auth0 encodes the issuing connection in the subject as "<connection>|<id>",
    e.g. "google-oauth2|1234567890". `begin_login` asks for `connection()`, but
    /authorize does not *bind* state to it: a caller can reuse a server-minted
    state against a different connection in the same tenant. So the callback
    must check the prefix itself, or a token from any other connection (an
    Auth0 database, a SAML/OIDC enterprise connection, or anything added for
    testing) would pass every other check and be linked to an existing account
    by email.
    """
    return f"{connection()}|"


def client_id() -> str:
    return _env("KETSA_AUTH0_CLIENT_ID")


def client_secret() -> str:
    return _env("KETSA_AUTH0_CLIENT_SECRET")


def public_base() -> str:
    return os.getenv("KETSA_PUBLIC_BASE_URL", _DEFAULTS["KETSA_PUBLIC_BASE_URL"]).rstrip("/")


def frontend_url() -> str:
    return os.getenv("KETSA_FRONTEND_URL", _DEFAULTS["KETSA_FRONTEND_URL"]).rstrip("/")


def redirect_uri() -> str:
    """The exact callback URL that must be allowlisted in the Auth0 app."""
    return f"{public_base()}/api/auth/social/callback"


def configured() -> bool:
    return bool(domain() and client_id() and client_secret())


# --- OAuth state / nonce store ------------------------------------------------

_states: dict[str, dict[str, Any]] = {}


def _prune_states(now: float) -> None:
    """Drop expired attempts, then hard-cap the dict if it is still too big.

    Expiry alone bounds the *steady-state* size (rate x TTL) but not a burst
    inside one window, so the cap is what actually guarantees an upper bound.
    """
    for s in [s for s, v in _states.items() if v["exp"] < now]:
        _states.pop(s, None)
    if len(_states) > MAX_PENDING_STATES:
        # Drop the soonest-to-expire entries first.
        for s in sorted(_states, key=lambda k: _states[k]["exp"])[: len(_states) - MAX_PENDING_STATES]:
            _states.pop(s, None)


def _pkce_pair() -> tuple[str, str]:
    """A PKCE (S256) code verifier and its challenge.

    The client secret already makes this a confidential flow, so PKCE is not
    strictly required — but it means a stolen/intercepted authorization code
    is useless on its own, and it is what Auth0 recommends for every client.
    """
    verifier = secrets.token_urlsafe(64)  # 43-128 chars, per RFC 7636
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def begin_login() -> str:
    """Mint state+nonce+PKCE verifier and return the Auth0 /authorize URL."""
    now = time.time()
    _prune_states(now)
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier, challenge = _pkce_pair()
    _states[state] = {
        "exp": now + STATE_TTL_SECONDS,
        "nonce": nonce,
        "verifier": verifier,
    }
    qs = urllib.parse.urlencode({
        "client_id": client_id(),
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "nonce": nonce,
        "connection": connection(),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return f"https://{domain()}/authorize?{qs}"


def take_state(state: str) -> tuple[str, str]:
    """Consume and validate a state value.

    Returns ``(nonce, code_verifier)`` — both bound to the state, both
    single-use (the entry is popped before it is validated, so a replayed
    state finds nothing).
    """
    if not state:
        raise SocialError("Missing state parameter")
    entry = _states.pop(state, None)
    if entry is None:
        raise SocialError("Unknown or expired login state — please try again")
    if entry["exp"] < time.time():
        raise SocialError("Login state expired — please try again")
    return str(entry["nonce"]), str(entry["verifier"])


# --- low-level HTTP ------------------------------------------------------------

class SocialError(Exception):
    """Raised when Auth0 reports an error or is unreachable."""


def _http_post_form(url: str, data: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    """POST url-encoded form data; returns the parsed JSON response."""
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            detail = {}
        msg = detail.get("error_description") or detail.get("error") or f"HTTP {e.code}"
        raise SocialError(str(msg)) from e
    except urllib.error.URLError as e:
        raise SocialError(f"Auth0 unreachable: {e.reason}") from e
    except (ValueError, OSError) as e:
        raise SocialError(f"Auth0 response parse failed: {e}") from e


# --- token exchange + verification --------------------------------------------

def exchange_code(code: str, code_verifier: str) -> dict[str, Any]:
    """Swap the authorization code for tokens using the client secret + PKCE."""
    if not code:
        raise SocialError("Missing authorization code")
    payload = _http_post_form(
        f"https://{domain()}/oauth/token",
        {
            "grant_type": "authorization_code",
            "client_id": client_id(),
            "client_secret": client_secret(),
            "code": code,
            "redirect_uri": redirect_uri(),
            "code_verifier": code_verifier,
        },
    )
    if payload.get("error"):
        raise SocialError(str(payload.get("error_description") or payload["error"]))
    if not payload.get("id_token"):
        raise SocialError("Auth0 token response is missing the id token")
    return payload


_jwks_cache: dict[str, Any] | None = None
_jwks_fetched_at: float = 0.0


def _fetch_jwks() -> dict[str, Any]:
    """Fetch the Auth0 JSON Web Key Set (RS256 public keys)."""
    try:
        with urllib.request.urlopen(
            f"https://{domain()}/.well-known/jwks.json", timeout=15
        ) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
    except Exception as e:  # URLError | ValueError | OSError
        raise SocialError(f"Unable to fetch Auth0 signing keys: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("keys"), list) or not data["keys"]:
        raise SocialError("Auth0 signing keys are not a valid JWKS")
    return data


def jwks() -> dict[str, Any]:
    """Cached JWKS (a malicious/invalid response is not cached)."""
    global _jwks_cache, _jwks_fetched_at
    now = time.time()
    if _jwks_cache is None or now - _jwks_fetched_at > JWKS_CACHE_TTL:
        _jwks_cache = _fetch_jwks()
        _jwks_fetched_at = now
    return _jwks_cache


def verify_id_token(id_token: str, expected_nonce: str) -> dict[str, Any]:
    """Verify an Auth0 id token (signature, issuer, audience, exp, nonce, connection).

    Returns the verified claims. Any failure raises ``SocialError`` — a token
    is never trusted without a full verification pass.
    """
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as e:
        raise SocialError("Malformed id token") from e

    # Select the signing key the token's ``kid`` points at; a token that
    # references an unknown key is rejected outright.
    kid = header.get("kid")
    keys = jwks().get("keys") or []
    match = next((k for k in keys if k.get("kid") == kid), None)
    if match is None:
        raise SocialError("Unknown Auth0 signing key")

    try:
        payload = jwt.decode(
            id_token,
            key=jwt.PyJWK(match),
            algorithms=["RS256"],
            audience=client_id(),
            issuer=f"https://{domain()}/",
            leeway=10,
            options={"require": ["sub", "exp", "iat", "iss", "aud"]},
        )
    except jwt.PyJWTError as e:
        raise SocialError(f"Invalid id token: {e}") from e

    # PyJWT verifies standard claims but not app-level ones.
    if payload.get("nonce") != expected_nonce:
        raise SocialError("id token nonce mismatch")

    # The load-bearing check. A valid signature only proves "some connection in
    # this tenant minted this" — every connection shares the issuer, the
    # audience and the signing keys. Without this, a token from a second
    # connection (an Auth0 database, an enterprise SAML/OIDC connection, a
    # sandbox tenant member added for testing) would be accepted, and because
    # those connections let the *account holder* assert their own email, the
    # login would be silently linked to a victim's existing Ketsa account —
    # wallet, balance and all. `begin_login` asking for the connection is not a
    # substitute: /authorize does not bind `state` to the connection, so a
    # caller holding a valid state can authenticate against a different one and
    # still complete this callback.
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub.startswith(expected_sub_prefix()):
        raise SocialError("Sign-in was not completed with the expected provider")

    if not isinstance(payload.get("email"), str):
        # No usable email: only the sub can identify this user.
        payload["email"] = ""
    return payload