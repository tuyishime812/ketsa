"""Passwordless sign-in by emailed one-time code.

Covers the security properties that matter for a code-delivered login:
  * the code is bound to one account, single-use, and expires;
  * requesting a code never reveals whether an address is registered
    (no user enumeration, CWE-203);
  * the endpoint cannot be turned into an open mail relay (per-IP throttle);
  * a phone-only account cannot be signed into this way (no inbox to deliver to).
"""

import time
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app import auth as auth_mod
from app import authstate
from tests.conftest import register_user


@pytest.fixture(autouse=True)
def _clean_auth_state():
    """The OTP/session/throttle stores are shared state (authstate.py).

    In the real server they intentionally live for the process lifetime (and
    across restarts in production), so every test in this module has to start
    from empty or it inherits another test's codes and per-IP request counts
    (TestClient reports the same "testclient" IP for every request). Mirrors
    tests/test_social.py.
    """
    authstate.reset()
    yield
    authstate.reset()


@pytest.fixture()
def code_env(monkeypatch):
    """Short cooldown so the resend tests don't sleep for a minute."""
    monkeypatch.setenv("KETSA_OTP_RESEND_SECONDS", "1")
    monkeypatch.setenv("KETSA_CODE_REQUEST_MAX", "5")
    monkeypatch.setenv("KETSA_CODE_REQUEST_WINDOW", "900")
    return monkeypatch


def _request_code(client: TestClient, identifier: str) -> tuple[int, list]:
    """Ask for a sign-in code, capturing what the mailer was asked to send."""
    sent: list[tuple[str, str, str]] = []
    with mock.patch(
        "app.mailer.send_otp_email",
        side_effect=lambda to, code, purpose, ttl, name="": (
            sent.append((to, code, purpose)) or True
        ),
    ):
        res = client.post("/api/auth/login/code", json={"identifier": identifier})
    return res.status_code, sent


def _login_codes(sent: list) -> list[str]:
    return [code for _to, code, purpose in sent if purpose == "login"]


def test_code_login_returns_a_session(client: TestClient, code_env) -> None:
    register_user(client, "alice@ketsa.io")

    status, sent = _request_code(client, "alice@ketsa.io")
    assert status == 200
    assert len(_login_codes(sent)) == 1

    code = _login_codes(sent)[0]
    res = client.post(
        "/api/auth/login/code/verify", json={"email": "alice@ketsa.io", "otp": code}
    )
    assert res.status_code == 200, res.text
    assert res.json()["token"]
    assert res.json()["user"]["email"] == "alice@ketsa.io"


def test_unknown_address_is_indistinguishable(client: TestClient, code_env) -> None:
    """Requesting a code must not disclose whether the account exists."""
    register_user(client, "alice@ketsa.io")

    known_status, known_sent = _request_code(client, "alice@ketsa.io")
    unknown_status, unknown_sent = _request_code(client, "nobody@ketsa.io")

    assert known_status == unknown_status == 200
    # Same shape of reply; only the presence of a real email differs.
    assert len(known_sent) == 1
    assert unknown_sent == []


def test_malformed_and_phone_identifiers_are_also_uniform(
    client: TestClient, code_env
) -> None:
    for identifier in ("not-an-email", "0991234567", ""):
        status, sent = _request_code(client, identifier)
        assert status == 200, identifier
        assert sent == [], identifier


def test_wrong_code_is_rejected(client: TestClient, code_env) -> None:
    register_user(client, "alice@ketsa.io")
    _request_code(client, "alice@ketsa.io")

    res = client.post(
        "/api/auth/login/code/verify",
        json={"email": "alice@ketsa.io", "otp": "000000"},
    )
    assert res.status_code == 401


def test_code_is_single_use(client: TestClient, code_env) -> None:
    """A leaked code must not be replayable (CWE-294 auth bypass by reuse)."""
    register_user(client, "alice@ketsa.io")
    _status, sent = _request_code(client, "alice@ketsa.io")
    code = _login_codes(sent)[0]

    first = client.post(
        "/api/auth/login/code/verify", json={"email": "alice@ketsa.io", "otp": code}
    )
    assert first.status_code == 200
    replay = client.post(
        "/api/auth/login/code/verify", json={"email": "alice@ketsa.io", "otp": code}
    )
    assert replay.status_code == 401


def test_code_expires(client: TestClient, code_env) -> None:
    register_user(client, "alice@ketsa.io")
    _status, sent = _request_code(client, "alice@ketsa.io")
    code = _login_codes(sent)[0]

    # Rewind the stored code's expiry rather than sleeping.
    authstate.expire_all_otps(time.time() - 1)

    res = client.post(
        "/api/auth/login/code/verify", json={"email": "alice@ketsa.io", "otp": code}
    )
    assert res.status_code == 401


def test_code_cannot_be_redeemed_for_another_account(
    client: TestClient, code_env
) -> None:
    """A code is bound to the account that requested it."""
    register_user(client, "alice@ketsa.io")
    register_user(client, "bob@ketsa.io", name="Bob Trader")

    _status, sent = _request_code(client, "alice@ketsa.io")
    code = _login_codes(sent)[0]

    res = client.post(
        "/api/auth/login/code/verify", json={"email": "bob@ketsa.io", "otp": code}
    )
    assert res.status_code == 401


def test_resend_is_cooldown_gated(client: TestClient, code_env) -> None:
    """A second request inside the cooldown must not mail a second code."""
    register_user(client, "alice@ketsa.io")

    _status, first = _request_code(client, "alice@ketsa.io")
    status, second = _request_code(client, "alice@ketsa.io")

    assert status == 200  # still uniform: no oracle for "was a code sent?"
    assert len(_login_codes(first)) == 1
    assert second == []


def test_per_ip_throttle_blocks_mail_relay_abuse(
    client: TestClient, monkeypatch
) -> None:
    """Rotating victim addresses must be throttled per IP (spam relay, CWE-441)."""
    monkeypatch.setenv("KETSA_OTP_RESEND_SECONDS", "0")
    monkeypatch.setenv("KETSA_CODE_REQUEST_MAX", "3")
    register_user(client, "alice@ketsa.io")

    statuses = [
        client.post(
            "/api/auth/login/code", json={"identifier": f"victim{i}@ketsa.io"}
        ).status_code
        for i in range(6)
    ]
    assert statuses.count(200) == 3
    assert statuses.count(429) == 3


def test_login_code_survives_reboot_of_password_throttle(
    client: TestClient, code_env
) -> None:
    """A password failure streak must not block a valid code sign-in."""
    register_user(client, "alice@ketsa.io")
    for _ in range(2):
        client.post(
            "/api/auth/login",
            json={"identifier": "alice@ketsa.io", "password": "wrongpassword"},
        )

    _status, sent = _request_code(client, "alice@ketsa.io")
    code = _login_codes(sent)[0]
    res = client.post(
        "/api/auth/login/code/verify", json={"email": "alice@ketsa.io", "otp": code}
    )
    assert res.status_code == 200, res.text