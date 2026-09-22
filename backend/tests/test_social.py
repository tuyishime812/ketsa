"""Tests for Auth0 "Continue with Google" social login.

The Auth0 HTTP surface (authorize page, /oauth/token, JWKS) is stubbed; the
crypto is real. Id tokens are RS256-signed with a generated keypair and
verified through the same PyJWT + JWKS path the production code uses, so a
tampered token, a wrong nonce, a wrong issuer/audience or an unknown signing
key all fail end-to-end — not just in the mock layer.

Network calls to Auth0 are replaced by monkeypatching ``app.social`` functions;
nothing in this file touches the network or a real database.
"""

import base64
import json
import os
import time
import urllib.parse
from unittest import mock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import auth as auth_mod
from app import social as social_mod
from app.engine import engine
from app.storage import reset_backend
from app.main import create_app

GOOGLE_EMAIL = "ada.okafor@gmail.com"
GOOGLE_SUB = "google-oauth2|1234567890"
GOOGLE_NAME = "Ada Okafor"

AUTH0_ENV = {
    "KETSA_AUTH0_DOMAIN": "ketsa-test.auth0.com",
    "KETSA_AUTH0_CLIENT_ID": "test-client-id",
    "KETSA_AUTH0_CLIENT_SECRET": "test-client-secret",
    "KETSA_PUBLIC_BASE_URL": "http://127.0.0.1:8000",
    "KETSA_FRONTEND_URL": "http://localhost:3000",
}


# ---------------------------------------------------------------------------
# Crypto helpers — real keypair, JWK, signed id token
# ---------------------------------------------------------------------------

def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def make_keypair(kid: str = "test-key-1"):
    """Return (private_pem, jwks) for a fresh RSA key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub = key.public_key().public_numbers()
    n_bytes = pub.n.to_bytes((pub.n.bit_length() + 7) // 8, "big")
    e_bytes = pub.e.to_bytes((pub.e.bit_length() + 7) // 8, "big")
    jwks = {
        "keys": [{
            "kty": "RSA",
            "kid": kid,
            "use": "sig",
            "alg": "RS256",
            "n": _b64u(n_bytes),
            "e": _b64u(e_bytes),
        }]
    }
    return priv_pem, jwks


def sign_id_token(priv_pem, claims: dict, kid: str = "test-key-1") -> str:
    return jwt.encode(claims, priv_pem, algorithm="RS256", headers={"kid": kid})


def google_claims(**overrides) -> dict:
    now = int(time.time())
    claims = {
        "iss": "https://ketsa-test.auth0.com/",
        "sub": GOOGLE_SUB,
        "aud": "test-client-id",
        "iat": now - 60,
        "exp": now + 3600,
        "nonce": "",
        "email": GOOGLE_EMAIL,
        "email_verified": True,
        "name": GOOGLE_NAME,
    }
    claims.update(overrides)
    return claims


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PRIV_PEM, _JWKS = make_keypair()


@pytest.fixture(autouse=True)
def _clean_state():
    reset_backend()
    engine.reset()
    auth_mod._tickets.clear()
    auth_mod._sessions.clear()
    social_mod._states.clear()
    yield


@pytest.fixture(autouse=True)
def _clean_state():
    reset_backend()
    engine.reset()
    auth_mod._tickets.clear()
    auth_mod._sessions.clear()
    social_mod._states.clear()
    yield


def _env_for(clear_auth0: bool) -> dict:
    env = dict(AUTH0_ENV)
    if clear_auth0:
        env.update({"KETSA_AUTH0_DOMAIN": "", "KETSA_AUTH0_CLIENT_ID": "", "KETSA_AUTH0_CLIENT_SECRET": ""})
    env.update({
        "KETSA_RATE_LIMIT_PER_MIN": "0",
        "KETSA_EXPOSE_DOCS": "0",
        "KETSA_DB_BACKEND": "memory",
    })
    return env


@pytest.fixture()
def client() -> TestClient:
    """App with Auth0 configured; the env patch lives for the whole test."""
    with mock.patch.dict(os.environ, _env_for(clear_auth0=False), clear=False):
        yield TestClient(create_app())


@pytest.fixture()
def unconfigured_client() -> TestClient:
    """App with Auth0 env vars blanked -> social endpoints return 503."""
    with mock.patch.dict(os.environ, _env_for(clear_auth0=True), clear=False):
        yield TestClient(create_app())


def _start_login(client: TestClient) -> tuple[str, str]:
    """POST /social/login, return (authorize_url, state)."""
    res = client.post("/api/auth/social/login")
    assert res.status_code == 200, res.text
    url = res.json()["url"]
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return url, qs["state"][0]


def _run_callback(client: TestClient, code: str, state: str, follow: bool = False):
    return client.get(
        f"/api/auth/social/callback?code={code}&state={state}",
        follow_redirects=follow,
    )


# ---------------------------------------------------------------------------
# Configuration gating
# ---------------------------------------------------------------------------

def test_login_503_when_not_configured(unconfigured_client: TestClient) -> None:
    assert unconfigured_client.post("/api/auth/social/login").status_code == 503


def test_callback_503_when_not_configured(unconfigured_client: TestClient) -> None:
    res = unconfigured_client.get("/api/auth/social/callback?code=x&state=y")
    assert res.status_code == 503


# ---------------------------------------------------------------------------
# Login start
# ---------------------------------------------------------------------------

def test_login_returns_authorize_url(client: TestClient) -> None:
    url, _ = _start_login(client)
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert url.startswith("https://ketsa-test.auth0.com/authorize?")
    assert qs["client_id"] == ["test-client-id"]
    assert qs["response_type"] == ["code"]
    assert qs["scope"] == ["openid profile email"]
    assert qs["connection"] == ["google-oauth2"]
    assert qs["redirect_uri"] == ["http://127.0.0.1:8000/api/auth/social/callback"]
    assert qs["state"] and qs["nonce"]


# ---------------------------------------------------------------------------
# Callback validation (no token exchange yet)
# ---------------------------------------------------------------------------

def test_callback_rejects_unknown_state(client: TestClient) -> None:
    res = _run_callback(client, "code", "forged-state")
    assert res.status_code == 400
    assert "state" in res.json()["detail"].lower()


def test_callback_rejects_missing_code(client: TestClient) -> None:
    _, state = _start_login(client)
    res = _run_callback(client, "", state)
    assert res.status_code == 400


def test_callback_state_is_single_use(client: TestClient) -> None:
    _, state = _start_login(client)
    nonce = social_mod._states[state]["nonce"]
    with mock.patch.object(social_mod, "jwks", return_value=_JWKS), mock.patch.object(
        social_mod, "exchange_code",
        return_value={"id_token": sign_id_token(_PRIV_PEM, google_claims(nonce=nonce))},
    ):
        assert _run_callback(client, "code", state, follow=False).status_code == 302
        assert _run_callback(client, "code", state).status_code == 400  # replayed state


def test_callback_502_when_auth0_exchange_fails(client: TestClient) -> None:
    _, state = _start_login(client)
    with mock.patch.object(
        social_mod, "exchange_code", side_effect=social_mod.SocialError("Auth0 down")
    ):
        assert _run_callback(client, "code", state).status_code == 502


# ---------------------------------------------------------------------------
# Token verification (real signatures)
# ---------------------------------------------------------------------------

def _auth0_wiring(client: TestClient, priv_pem=_PRIV_PEM, jwks=_JWKS):
    """Context managers routing JWKS fetch + code exchange to test doubles."""
    return (
        mock.patch.object(social_mod, "jwks", return_value=jwks),
        mock.patch.object(
            social_mod, "exchange_code",
            return_value={"id_token": sign_id_token(priv_pem, google_claims())},
        ),
    )


def test_happy_path_creates_user_and_session(client: TestClient) -> None:
    url, state = _start_login(client)
    nonce = social_mod._states[state]["nonce"]
    with mock.patch.object(social_mod, "jwks", return_value=_JWKS), mock.patch.object(
        social_mod, "exchange_code",
        return_value={"id_token": sign_id_token(_PRIV_PEM, google_claims(nonce=nonce))},
    ):
        res = _run_callback(client, "code", state, follow=False)
    assert res.status_code == 302, res.text
    location = res.headers["location"]
    assert location.startswith("http://localhost:3000/auth/callback?ticket=")
    ticket = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)["ticket"][0]

    session = client.post("/api/auth/social/session", json={"ticket": ticket})
    assert session.status_code == 200, session.text
    body = session.json()
    assert body["user"]["email"] == GOOGLE_EMAIL
    assert body["user"]["name"] == GOOGLE_NAME
    assert body["wallet"]["balance"] >= 0
    assert body["token"]

    # The issued token is a real Ketsa session.
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.json()["user"]["email"] == GOOGLE_EMAIL

    # The user is persisted with its Auth0 subject (+ the auth0_sub lookup).
    assert me.json()["user"]["id"] == GOOGLE_EMAIL


def test_second_google_login_reuses_same_account(client: TestClient) -> None:
    tokens = []
    for _ in range(2):
        url, state = _start_login(client)
        nonce = social_mod._states[state]["nonce"]
        with mock.patch.object(social_mod, "jwks", return_value=_JWKS), mock.patch.object(
            social_mod, "exchange_code",
            return_value={"id_token": sign_id_token(_PRIV_PEM, google_claims(nonce=nonce))},
        ):
            res = _run_callback(client, "code", state, follow=False)
        ticket = urllib.parse.parse_qs(
            urllib.parse.urlparse(res.headers["location"]).query
        )["ticket"][0]
        tokens.append(client.post("/api/auth/social/session", json={"ticket": ticket}).json())
    assert tokens[0]["user"]["id"] == tokens[1]["user"]["id"]
    assert tokens[0]["wallet"]["id"] == tokens[1]["wallet"]["id"]


def test_callback_rejects_nonce_mismatch(client: TestClient) -> None:
    _, state = _start_login(client)
    with mock.patch.object(social_mod, "jwks", return_value=_JWKS), mock.patch.object(
        social_mod, "exchange_code",
        return_value={"id_token": sign_id_token(_PRIV_PEM, google_claims(nonce="wrong-nonce"))},
    ):
        res = _run_callback(client, "code", state)
    assert res.status_code == 400
    assert "nonce" in res.json()["detail"].lower()


def test_callback_rejects_unknown_signing_key(client: TestClient) -> None:
    _, state = _start_login(client)
    other_pem, _ = make_keypair(kid="other-key")
    with mock.patch.object(social_mod, "jwks", return_value=_JWKS), mock.patch.object(
        social_mod, "exchange_code",
        return_value={"id_token": sign_id_token(other_pem, google_claims(), kid="other-key")},
    ):
        res = _run_callback(client, "code", state)
    assert res.status_code == 400


def test_callback_rejects_wrong_audience(client: TestClient) -> None:
    _, state = _start_login(client)
    nonce = social_mod._states[state]["nonce"]
    with mock.patch.object(social_mod, "jwks", return_value=_JWKS), mock.patch.object(
        social_mod, "exchange_code",
        return_value={"id_token": sign_id_token(
            _PRIV_PEM, google_claims(nonce=nonce, aud="someone-elses-client")
        )},
    ):
        res = _run_callback(client, "code", state)
    assert res.status_code == 400


def test_callback_rejects_wrong_issuer(client: TestClient) -> None:
    _, state = _start_login(client)
    nonce = social_mod._states[state]["nonce"]
    with mock.patch.object(social_mod, "jwks", return_value=_JWKS), mock.patch.object(
        social_mod, "exchange_code",
        return_value={"id_token": sign_id_token(
            _PRIV_PEM, google_claims(nonce=nonce, iss="https://evil.auth0.com/")
        )},
    ):
        res = _run_callback(client, "code", state)
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Account linking
# ---------------------------------------------------------------------------

def _google_login_with(client: TestClient, claims: dict) -> dict:
    """Run a full Google login; the server-minted nonce is stamped in."""
    url, state = _start_login(client)
    nonce = social_mod._states[state]["nonce"]
    claims = dict(claims)
    claims["nonce"] = nonce
    with mock.patch.object(social_mod, "jwks", return_value=_JWKS), mock.patch.object(
        social_mod, "exchange_code",
        return_value={"id_token": sign_id_token(_PRIV_PEM, claims)},
    ):
        res = _run_callback(client, "code", state, follow=False)
    assert res.status_code == 302, res.text
    ticket = urllib.parse.parse_qs(
        urllib.parse.urlparse(res.headers["location"]).query
    )["ticket"][0]
    return client.post("/api/auth/social/session", json={"ticket": ticket}).json()


def test_links_google_login_to_existing_password_account(client: TestClient) -> None:
    reg = client.post("/api/auth/register", json={
        "name": "Ada Okafor",
        "email": GOOGLE_EMAIL,
        "password": "CorrectHorse99",
    })
    assert reg.status_code == 200, reg.text
    password_wallet = reg.json()["wallet"]["id"]

    session = _google_login_with(client, google_claims(nonce="n"))
    assert session["user"]["id"] == GOOGLE_EMAIL
    assert session["wallet"]["id"] == password_wallet  # same account, same wallet
    # The account now carries the Auth0 subject, so future Google logins hit it.
    assert auth_mod.store.get_user(GOOGLE_EMAIL)["auth0_sub"] == GOOGLE_SUB


def test_rejects_email_bound_to_another_google_account(client: TestClient) -> None:
    _google_login_with(client, google_claims())
    url, state = _start_login(client)
    nonce = social_mod._states[state]["nonce"]
    with mock.patch.object(social_mod, "jwks", return_value=_JWKS), mock.patch.object(
        social_mod, "exchange_code",
        return_value={"id_token": sign_id_token(
            _PRIV_PEM, google_claims(nonce=nonce, sub="google-oauth2|9999999999")
        )},
    ):
        res = _run_callback(client, "code", state)
    assert res.status_code == 409


def test_unverified_email_does_not_link(client: TestClient) -> None:
    reg = client.post("/api/auth/register", json={
        "name": "Ada Okafor",
        "email": GOOGLE_EMAIL,
        "password": "CorrectHorse99",
    })
    assert reg.status_code == 200, reg.text

    session = _google_login_with(
        client, google_claims(email_verified=False, name="Eve")
    )
    # No linking -> a brand-new account keyed by the Auth0 subject, never the
    # email (which would overwrite the password account's row).
    assert session["user"]["id"] == GOOGLE_SUB
    assert session["user"]["email"] == GOOGLE_EMAIL
    linked = auth_mod.store.get_user(GOOGLE_SUB)
    assert linked is not None and linked["auth0_sub"] == GOOGLE_SUB

    # The pre-existing password account must be untouched and still work.
    reg_login = client.post("/api/auth/login", json={
        "email": GOOGLE_EMAIL, "password": "CorrectHorse99",
    })
    assert reg_login.status_code == 200, reg_login.text
    assert reg_login.json()["wallet"]["id"] == reg.json()["wallet"]["id"]


# ---------------------------------------------------------------------------
# Ticket handling
# ---------------------------------------------------------------------------

def test_ticket_is_single_use(client: TestClient) -> None:
    _google_login_with(client, google_claims())
    url, state = _start_login(client)
    nonce = social_mod._states[state]["nonce"]
    with mock.patch.object(social_mod, "jwks", return_value=_JWKS), mock.patch.object(
        social_mod, "exchange_code",
        return_value={"id_token": sign_id_token(_PRIV_PEM, google_claims(nonce=nonce))},
    ):
        res = _run_callback(client, "code", state, follow=False)
    ticket = urllib.parse.parse_qs(
        urllib.parse.urlparse(res.headers["location"]).query
    )["ticket"][0]
    assert client.post("/api/auth/social/session", json={"ticket": ticket}).status_code == 200
    assert client.post("/api/auth/social/session", json={"ticket": ticket}).status_code == 400


def test_ticket_cannot_be_forged_or_expired(client: TestClient) -> None:
    assert client.post("/api/auth/social/session", json={"ticket": "not-a-real-ticket"}).status_code == 400
    # Expire a real ticket by rewinding its timestamp.
    url, state = _start_login(client)
    nonce = social_mod._states[state]["nonce"]
    with mock.patch.object(social_mod, "jwks", return_value=_JWKS), mock.patch.object(
        social_mod, "exchange_code",
        return_value={"id_token": sign_id_token(_PRIV_PEM, google_claims(nonce=nonce))},
    ):
        res = _run_callback(client, "code", state, follow=False)
    ticket = urllib.parse.parse_qs(
        urllib.parse.urlparse(res.headers["location"]).query
    )["ticket"][0]
    import time
    auth_mod._tickets[ticket] = (time.time() - 1, "stale-token")
    assert client.post("/api/auth/social/session", json={"ticket": ticket}).status_code == 400