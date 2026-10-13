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
import hashlib
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

from conftest import register_user
from app import auth as auth_mod
from app import authstate
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
    authstate.reset()
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
    # The reason (a replayed/mismatched nonce) is a security signal and belongs in
    # the server log, not in the response body.
    detail = res.json()["detail"].lower()
    assert "nonce" not in detail
    assert "google sign-in could not be verified" in detail


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
    reg = register_user(client, identifier=GOOGLE_EMAIL, name="Ada Okafor", password="CorrectHorse99")
    password_wallet = reg["wallet"]["id"]

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
    reg = register_user(client, identifier=GOOGLE_EMAIL, name="Ada Okafor", password="CorrectHorse99")

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
        "identifier": GOOGLE_EMAIL, "password": "CorrectHorse99",
    })
    assert reg_login.status_code == 200, reg_login.text
    assert reg_login.json()["wallet"]["id"] == reg["wallet"]["id"]


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
    authstate.expire_ticket(ticket, time.time() - 1)
    assert client.post("/api/auth/social/session", json={"ticket": ticket}).status_code == 400


# ---------------------------------------------------------------------------
# Connection binding (A-02)
#
# `begin_login` asks Auth0 for the google-oauth2 connection, but /authorize does
# not bind `state` to it. A valid signature only proves "some connection in this
# tenant signed this" — issuer, audience and keys are shared. So a token from a
# SECOND connection in the same tenant used to pass every other check and then
# get linked, by email, to an existing account. These tests are the regression
# for that.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "rogue_sub",
    [
        "Username-Password-Authentication|abc123",  # Auth0's built-in database
        "my-enterprise-saml|xyz789",                # an enterprise connection
        "auth0|deadbeef",                           # no connection prefix at all
        "notgoogle-oauth2|abc",                     # prefix-lookalike
        "google-oauth2",                            # connection name, no separator
        "GOOGLE-OAUTH2|abc",                        # case-different lookalike
    ],
)
def test_sub_connection_prefix_is_enforced(client: TestClient, rogue_sub: str) -> None:
    """Only the Google connection may complete a Ketsa social login."""
    register_user(client, identifier=GOOGLE_EMAIL, name="Ada Okafor",
                  password="CorrectHorse99")
    _, state = _start_login(client)
    nonce = social_mod._states[state]["nonce"]
    with mock.patch.object(social_mod, "jwks", return_value=_JWKS), mock.patch.object(
        social_mod, "exchange_code",
        return_value={"id_token": sign_id_token(_PRIV_PEM, google_claims(nonce=nonce, sub=rogue_sub))},
    ):
        res = _run_callback(client, "code", state)
    assert res.status_code == 400
    assert "location" not in res.headers
    # The victim's account was never linked to the rogue subject. A password
    # account has no `auth0_sub` key at all, hence .get().
    assert auth_mod.store.get_user(GOOGLE_EMAIL).get("auth0_sub") is None


def test_same_connection_different_google_account_stays_allowed(client: TestClient) -> None:
    """The guard must not over-block: a new Google identity is a normal signup.

    Google accounts are separated by Auth0, not by us, so a *different*
    google-oauth2 subject must still be able to create its own account.
    """
    res = _google_login_with(client, google_claims(sub="google-oauth2|9999999999"))
    assert res["user"]["id"] == GOOGLE_EMAIL  # new account, own subject
    assert auth_mod.store.get_user(GOOGLE_EMAIL)["auth0_sub"] == "google-oauth2|9999999999"


def test_rogue_connection_cannot_hijack_an_existing_account(client: TestClient) -> None:
    """The full attack: a non-Google connection claiming the victim's email."""
    reg = register_user(client, identifier=GOOGLE_EMAIL, name="Ada Okafor",
                        password="CorrectHorse99")
    victim_wallet = reg["wallet"]["id"]

    # Fund it so a takeover would be visibly valuable.
    engine.credit_balance(victim_wallet, 5_000.0)
    # Baseline: register_user already issued the victim one session.
    sessions_before = authstate.session_count()

    for attempt in range(3):  # a determined attacker retries
        _, state = _start_login(client)
        nonce = social_mod._states[state]["nonce"]
        with mock.patch.object(social_mod, "jwks", return_value=_JWKS), mock.patch.object(
            social_mod, "exchange_code",
            return_value={"id_token": sign_id_token(
                _PRIV_PEM,
                google_claims(nonce=nonce, sub="Username-Password-Authentication|attacker",
                              email=GOOGLE_EMAIL, email_verified=True),
            )},
        ):
            res = _run_callback(client, "code", state)
        assert res.status_code == 400, f"attempt {attempt} should have been rejected"
        # Not one new session was minted, by anyone.
        assert authstate.session_count() == sessions_before

    victim = auth_mod.store.get_user(GOOGLE_EMAIL)
    assert victim.get("auth0_sub") is None
    assert victim["wallet_id"] == victim_wallet
    assert engine.wallet_view(victim_wallet)["balance"] == 5_000.0
    # The victim's password still works — the account was never re-pointed.
    assert client.post("/api/auth/login", json={
        "identifier": GOOGLE_EMAIL, "password": "CorrectHorse99"}).status_code == 200


def test_expected_sub_prefix_tracks_the_configured_connection() -> None:
    """The guard is derived from the same value /authorize asks for."""
    assert social_mod.expected_sub_prefix() == f"{social_mod.connection()}|"
    assert social_mod.expected_sub_prefix() == "google-oauth2|"
    # And it follows the env var, so adding a provider cannot desync the two.
    with mock.patch.dict(os.environ, {"KETSA_AUTH0_CONNECTION": "apple"}, clear=False):
        assert social_mod.connection() == "apple"
        assert social_mod.expected_sub_prefix() == "apple|"


# ---------------------------------------------------------------------------
# PKCE (A-05)
# ---------------------------------------------------------------------------

def test_authorize_url_carries_a_pkce_challenge(client: TestClient) -> None:
    url, state = _start_login(client)
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert qs["code_challenge_method"] == ["S256"]
    challenge = qs["code_challenge"][0]
    # S256, unpadded base64url of the SHA-256 of the stored verifier.
    verifier = social_mod._states[state]["verifier"]
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert challenge == expected.decode("ascii")
    assert 43 <= len(verifier) <= 128  # RFC 7636


def test_pkce_verifier_is_sent_to_the_token_endpoint(client: TestClient) -> None:
    """The callback must hand the bound verifier to /oauth/token."""
    _, state = _start_login(client)
    nonce = social_mod._states[state]["nonce"]
    expected_verifier = social_mod._states[state]["verifier"]
    with mock.patch.object(social_mod, "jwks", return_value=_JWKS), mock.patch.object(
        social_mod, "exchange_code", return_value={
            "id_token": sign_id_token(_PRIV_PEM, google_claims(nonce=nonce))}
    ) as exch:
        _run_callback(client, "code", state)
    assert exch.call_args.args[1] == expected_verifier


def test_take_state_returns_a_single_use_pair() -> None:
    """(nonce, verifier) is returned together and the state is consumed."""
    social_mod._states["s1"] = {
        "exp": time.time() + 600, "nonce": "n", "verifier": "v",
    }
    assert social_mod.take_state("s1") == ("n", "v")
    # Second attempt: the state is gone.
    with pytest.raises(social_mod.SocialError):
        social_mod.take_state("s1")


# ---------------------------------------------------------------------------
# Unbounded growth of the ticket / state stores (A-01, A-03)
# ---------------------------------------------------------------------------

def test_abandoned_tickets_are_evicted_not_kept_forever() -> None:
    """A ticket nobody ever redeems must not live forever (CWE-401/770)."""
    authstate.reset()
    now = time.time()
    # 10 abandoned tickets, all long expired, plus one live.
    for i in range(10):
        authstate.put_ticket(f"dead-{i}", "tok", issued=now - 100, expires=now - 1)
    authstate.put_ticket("live", "tok", issued=now - 100, expires=now + 60)
    auth_mod._prune_tickets(now)
    assert authstate.ticket_count() == 1
    authstate.reset()


def test_ticket_store_is_hard_capped() -> None:
    """A burst inside one TTL window cannot grow the store without bound."""
    authstate.reset()
    cap = auth_mod.MAX_PENDING_TICKETS
    now = time.time()
    for i in range(cap + 500):
        authstate.put_ticket(f"t{i}", "tok", issued=now, expires=now + 60)
    auth_mod._prune_tickets(now)
    assert authstate.ticket_count() == cap
    authstate.reset()


def test_issuing_a_ticket_sweeps_expired_ones(client: TestClient) -> None:
    """The sweep runs on the issue path, so it happens on real traffic."""
    authstate.reset()
    for i in range(50):
        authstate.put_ticket(f"stale-{i}", "tok", issued=time.time() - 200, expires=time.time() - 1)
    auth_mod._issue_sso_ticket("tok")
    # Only the fresh ticket remains (issued above issues exactly one).
    assert authstate.ticket_count() == 1


def test_pending_states_are_hard_capped() -> None:
    """Same guarantee for the /authorize state store (CWE-770)."""
    social_mod._states.clear()
    cap = social_mod.MAX_PENDING_STATES
    now = time.time()
    for i in range(cap + 500):
        social_mod._states[f"s{i}"] = {"exp": now + 600, "nonce": "n", "verifier": "v"}
    social_mod._prune_states(now)
    assert len(social_mod._states) == cap
    social_mod._states.clear()


def test_state_cap_evicts_the_soonest_to_expire() -> None:
    """Under pressure the oldest attempts go first, not arbitrary ones."""
    social_mod._states.clear()
    now = time.time()
    social_mod._states["oldest"] = {"exp": now + 10, "nonce": "n", "verifier": "v"}
    social_mod._states["newest"] = {"exp": now + 590, "nonce": "n", "verifier": "v"}
    social_mod.MAX_PENDING_STATES = 1
    try:
        social_mod._prune_states(now)
        assert "oldest" not in social_mod._states
        assert "newest" in social_mod._states
    finally:
        social_mod.MAX_PENDING_STATES = 5_000
        social_mod._states.clear()


# ---------------------------------------------------------------------------
# Provider internals must not reach the browser (A-04)
# ---------------------------------------------------------------------------

def test_auth0_error_detail_is_not_returned_to_the_client(client: TestClient) -> None:
    """Auth0's own error text is logged, not shown in the browser."""
    _, state = _start_login(client)
    secretish = "unauthorized_client: https://internal-ketsa.auth0.com/secret-tenant"
    with mock.patch.object(social_mod, "jwks", return_value=_JWKS), mock.patch.object(
        social_mod, "exchange_code", side_effect=social_mod.SocialError(secretish)
    ):
        res = _run_callback(client, "code", state)
    assert res.status_code == 502
    body = res.text
    assert "secret-tenant" not in body
    assert "internal-ketsa" not in body
    assert "unauthorized_client" not in body


def test_token_rejection_reason_is_not_returned_to_the_client(client: TestClient) -> None:
    """A rejected token's reason belongs in the log, not the response."""
    _, state = _start_login(client)
    nonce = social_mod._states[state]["nonce"]
    with mock.patch.object(social_mod, "jwks", return_value=_JWKS), mock.patch.object(
        social_mod, "exchange_code",
        return_value={"id_token": sign_id_token(
            _PRIV_PEM, google_claims(nonce=nonce, sub="rogue-conn|1"))},
    ):
        res = _run_callback(client, "code", state)
    assert res.status_code == 400
    assert "rogue-conn" not in res.text
    assert "expected provider" not in res.text