"""Tests for the user auth API (register / login / session)."""

import os
import time
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app import auth as auth_mod
from app import authstate
from app.engine import engine
from conftest import register_user


def _register(client: TestClient, email: str = "alice@ketsa.io") -> dict:
    return register_user(client, identifier=email, name="Alice Trader")


def test_register_creates_account_and_wallet(client: TestClient) -> None:
    body = _register(client)
    assert body["token"]
    assert body["user"]["email"] == "alice@ketsa.io"
    assert "wallet_id" in body["user"]
    assert body["wallet"]["id"] == body["user"]["wallet_id"]
    assert body["wallet"]["balance"] == 0.0  # no free money — deposits fund wallets


def test_register_validation(client: TestClient) -> None:
    assert client.post(
        "/api/auth/register",
        json={"name": "X", "identifier": "a@b.io", "password": "password123"},
    ).status_code == 400
    assert client.post(
        "/api/auth/register",
        json={"name": "Alice", "identifier": "not-an-email", "password": "password123"},
    ).status_code == 400
    assert client.post(
        "/api/auth/register",
        json={"name": "Alice", "identifier": "a@b.io", "password": "short"},
    ).status_code == 400


def test_register_duplicate_email(client: TestClient) -> None:
    _register(client)
    assert client.post(
        "/api/auth/register",
        json={"name": "Bob", "identifier": "alice@ketsa.io", "password": "password123"},
    ).status_code == 409


def test_login_success_and_failure(client: TestClient) -> None:
    _register(client)
    ok = client.post(
        "/api/auth/login",
        json={"identifier": "alice@ketsa.io", "password": "password123"},
    )
    assert ok.status_code == 200
    assert ok.json()["token"]
    assert ok.json()["user"]["email"] == "alice@ketsa.io"

    bad = client.post(
        "/api/auth/login",
        json={"identifier": "alice@ketsa.io", "password": "wrongpass"},
    )
    assert bad.status_code == 401

    missing = client.post(
        "/api/auth/login",
        json={"identifier": "nobody@ketsa.io", "password": "password123"},
    )
    assert missing.status_code == 401


def test_login_returns_same_wallet(client: TestClient) -> None:
    reg = _register(client)
    login = client.post(
        "/api/auth/login",
        json={"identifier": "alice@ketsa.io", "password": "password123"},
    ).json()
    assert login["wallet"]["id"] == reg["wallet"]["id"]


def test_me_requires_valid_token(client: TestClient) -> None:
    _register(client)
    assert client.get("/api/auth/me").status_code == 401
    assert client.get(
        "/api/auth/me", headers={"Authorization": "Bearer junk"}
    ).status_code == 401


def test_me_returns_profile(client: TestClient) -> None:
    body = _register(client)
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert res.status_code == 200
    assert res.json()["user"]["email"] == "alice@ketsa.io"
    assert res.json()["wallet"]["id"] == body["wallet"]["id"]


def test_logout_invalidates_session(client: TestClient) -> None:
    body = _register(client)
    headers = {"Authorization": f"Bearer {body['token']}"}
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401


# ---------------------------------------------------------------------------
# Notifications — welcome on register
# ---------------------------------------------------------------------------

def test_register_creates_welcome_notification(client: TestClient) -> None:
    reg = _register(client)
    wid = reg["wallet"]["id"]
    headers = {"Authorization": f"Bearer {reg['token']}"}
    notes = client.get(f"/api/wallet/{wid}/notifications", headers=headers).json()
    assert len(notes) >= 1
    assert notes[0]["type"] == "system"
    assert "Welcome" in notes[0]["title"]


# ---------------------------------------------------------------------------
# Login throttling (env-forced low thresholds so the test is fast)
# ---------------------------------------------------------------------------

def test_login_throttling(client: TestClient) -> None:
    _register(client, email="throttle@ketsa.io")
    with mock.patch.dict(os.environ, {"KETSA_AUTH_MAX_FAILURES": "2", "KETSA_AUTH_LOCKOUT_SECONDS": "120"}):
        for _ in range(2):
            client.post(
                "/api/auth/login",
                json={"identifier": "throttle@ketsa.io", "password": "bad"},
            )
        # Third attempt with bad password → 429
        resp = client.post(
            "/api/auth/login",
            json={"identifier": "throttle@ketsa.io", "password": "bad"},
        )
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------

def test_change_password(client: TestClient) -> None:
    reg = _register(client, email="pw@ketsa.io")
    token = reg["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Wrong current → 401
    resp = client.post(
        "/api/auth/password",
        json={"current": "wrongcurrent", "new": "newpassword1"},
        headers=headers,
    )
    assert resp.status_code == 401

    # Successful change
    resp = client.post(
        "/api/auth/password",
        json={"current": "password123", "new": "newpassword1"},
        headers=headers,
    )
    assert resp.status_code == 200
    new_token = resp.json()["token"]
    assert new_token

    # Old token revoked
    assert client.get("/api/auth/me", headers=headers).status_code == 401

    # New token works
    new_headers = {"Authorization": f"Bearer {new_token}"}
    assert client.get("/api/auth/me", headers=new_headers).status_code == 200

    # Old password can no longer log in
    assert client.post(
        "/api/auth/login",
        json={"identifier": "pw@ketsa.io", "password": "password123"},
    ).status_code == 401

    # New password logs in
    assert client.post(
        "/api/auth/login",
        json={"identifier": "pw@ketsa.io", "password": "newpassword1"},
    ).status_code == 200


# ---------------------------------------------------------------------------
# Optional bearer trade gating
# ---------------------------------------------------------------------------

def _create_guest_wallet(client: TestClient) -> str:
    resp = client.post("/api/wallet", json={"name": "Guest"})
    return resp.json()["id"]


def test_guest_trade_without_token(client: TestClient) -> None:
    wid = _create_guest_wallet(client)
    engine.credit_balance(wid, 1000.0)  # no free mint — fund for the test
    resp = client.post(
        "/api/trade",
        json={"wallet_id": wid, "market_id": "btc-120k", "outcome": "yes", "side": "buy", "amount": 25.0},
    )
    assert resp.status_code == 200


def test_account_trade_with_own_token(client: TestClient) -> None:
    reg = _register(client, email="gate@ketsa.io")
    engine.credit_balance(reg["wallet"]["id"], 1000.0)  # no free mint — fund for the test
    resp = client.post(
        "/api/trade",
        json={
            "wallet_id": reg["wallet"]["id"],
            "market_id": "btc-120k",
            "outcome": "yes",
            "side": "buy",
            "amount": 25.0,
        },
        headers={"Authorization": f"Bearer {reg['token']}"},
    )
    assert resp.status_code == 200


def test_account_trade_wrong_wallet_403(client: TestClient) -> None:
    alice = _register(client, email="a@ketsa.io")
    bob = _register(client, email="b@ketsa.io")
    resp = client.post(
        "/api/trade",
        json={
            "wallet_id": alice["wallet"]["id"],
            "market_id": "btc-120k",
            "outcome": "yes",
            "side": "buy",
            "amount": 25.0,
        },
        headers={"Authorization": f"Bearer {bob['token']}"},
    )
    assert resp.status_code == 403


def test_trade_invalid_token_401(client: TestClient) -> None:
    wid = _create_guest_wallet(client)
    resp = client.post(
        "/api/trade",
        json={"wallet_id": wid, "market_id": "btc-120k", "outcome": "yes", "side": "buy", "amount": 25.0},
        headers={"Authorization": "Bearer obviously-fake"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Phone-number accounts (alternative email/phone identifier)
# ---------------------------------------------------------------------------

def _register_phone(
    client: TestClient,
    phone: str = "0991 234 567",
    name: str = "Chimwemwe Banda",
) -> dict:
    res = client.post(
        "/api/auth/register",
        json={"name": name, "identifier": phone, "password": "password123"},
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_register_with_phone_normalizes_identifier(client: TestClient) -> None:
    body = _register_phone(client)
    # Leading 0, spaces stripped → canonical 9-digit form (wandePay-compatible).
    assert body["user"]["id"] == "991234567"
    assert body["user"]["phone"] == "991234567"
    assert body["user"]["email"] == ""
    assert body["wallet"]["id"] == body["user"]["wallet_id"]


def test_register_phone_country_code_forms(client: TestClient) -> None:
    # Different human formats of the same number all resolve to one account.
    _register_phone(client, phone="+265 99 123 4567")
    resp = client.post(
        "/api/auth/register",
        json={"name": "Dup", "identifier": "265991234567", "password": "password123"},
    )
    assert resp.status_code == 409


def test_login_with_phone_any_format(client: TestClient) -> None:
    _register_phone(client, phone="0888 123 456")
    ok = client.post(
        "/api/auth/login",
        json={"identifier": "+265888123456", "password": "password123"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["user"]["phone"] == "888123456"
    assert ok.json()["user"]["id"] == "888123456"

    # Bad password on a phone account → uniform 401, no account oracle.
    bad = client.post(
        "/api/auth/login",
        json={"identifier": "088123456", "password": "wrongpass"},
    )
    assert bad.status_code == 401


def test_register_phone_rejects_foreign_and_junk(client: TestClient) -> None:
    for junk in ("+441234567890", "12345", "099", "abcdefghij", ""):
        assert client.post(
            "/api/auth/register",
            json={"name": "X", "identifier": junk, "password": "password123"},
        ).status_code == 400, junk


def test_email_and_phone_are_distinct_accounts(client: TestClient) -> None:
    email_reg = _register(client, email="bob@ketsa.io")
    phone_reg = _register_phone(client, phone="991234567")
    assert email_reg["user"]["id"] == "bob@ketsa.io"
    assert phone_reg["user"]["id"] == "991234567"
    assert email_reg["wallet"]["id"] != phone_reg["wallet"]["id"]
    # Mailbox-style identifiers never resolve to the phone account.
    assert client.post(
        "/api/auth/login",
        json={"identifier": "bob@ketsa.io", "password": "password123"},
    ).json()["wallet"]["id"] == email_reg["wallet"]["id"]


def test_me_returns_phone_for_phone_account(client: TestClient) -> None:
    body = _register_phone(client)
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert res.status_code == 200
    assert res.json()["user"]["phone"] == "991234567"


def test_phone_login_throttling(client: TestClient) -> None:
    _register_phone(client, phone="995555555")
    with mock.patch.dict(os.environ, {"KETSA_AUTH_MAX_FAILURES": "2", "KETSA_AUTH_LOCKOUT_SECONDS": "120"}):
        for _ in range(2):
            client.post(
                "/api/auth/login",
                json={"identifier": "0995555555", "password": "bad"},
            )
        resp = client.post(
            "/api/auth/login",
            json={"identifier": "0995555555", "password": "bad"},
        )
        assert resp.status_code == 429
        # Lockout is keyed on the canonical identifier — alternate formatting
        # of the same number cannot bypass it.
        resp2 = client.post(
            "/api/auth/login",
            json={"identifier": "+265995555555", "password": "bad"},
        )
        assert resp2.status_code == 429


# ---------------------------------------------------------------------------
# Email OTP verification (register) + password reset (forgot-password)
# ---------------------------------------------------------------------------

def _start_email_signup(
    client: TestClient,
    email: str = "otp@ketsa.io",
    name: str = "Otp User",
    password: str = "password123",
) -> tuple[list[tuple[str, str, str]], str]:
    """POST /register for an email; returns (mail log, pending body email)."""
    sent: list[tuple[str, str, str]] = []

    def fake(to: str, code: str, purpose: str, ttl: int, name: str = "") -> bool:
        sent.append((to, code, purpose))
        return True

    with mock.patch("app.mailer.send_otp_email", side_effect=fake):
        res = client.post(
            "/api/auth/register",
            json={"name": name, "identifier": email, "password": password},
        )
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["pending"] is True and body["email"] == email
    assert len(sent) == 1 and sent[0][2] == "signup"
    return sent, body["email"]


def _verify(client: TestClient, email: str, otp: str):
    return client.post(
        "/api/auth/register/verify", json={"email": email, "otp": otp}
    )


def test_email_signup_waits_for_otp(client: TestClient) -> None:
    sent, email = _start_email_signup(client, email="hover@ketsa.io")
    code = sent[0][1]

    # No account yet — nothing in the store, cannot log in, no wallet minted.
    assert auth_mod.store.get_user_by_email(email) is None
    assert client.post(
        "/api/auth/login", json={"identifier": email, "password": "password123"}
    ).status_code == 401

    # Wrong code rejected.
    assert _verify(client, email, "000000").status_code == 401

    # Correct code completes the signup with a wallet (zero-funded — no mint).
    res = _verify(client, email, code)
    assert res.status_code == 200, res.text
    assert res.json()["user"]["id"] == email
    assert res.json()["user"]["email"] == email
    assert res.json()["wallet"]["balance"] == 0.0

    # The code is single-use — and the account now exists, so the verify
    # route answers 409 (account exists) before it would even look at the code.
    assert _verify(client, email, code).status_code == 409
    # A second signup for the now-taken email is rejected.
    assert client.post(
        "/api/auth/register",
        json={"name": "Dup", "identifier": email, "password": "password123"},
    ).status_code == 409


def test_email_signup_otp_attempts_then_resend(client: TestClient) -> None:
    with mock.patch.dict(
        os.environ, {"KETSA_OTP_MAX_ATTEMPTS": "1", "KETSA_OTP_RESEND_SECONDS": "0"}
    ):
        sent, email = _start_email_signup(client, email="tries@ketsa.io")
        code = sent[0][1]

        # One wrong attempt burns the code.
        assert _verify(client, email, "000000").status_code == 401
        assert _verify(client, email, code).status_code == 401  # correct but burned

        # Resend issues a fresh code that works.
        sent2: list[tuple[str, str, str]] = []

        def fake(to, code, purpose, ttl, name="") -> bool:
            sent2.append((to, code, purpose))
            return True

        with mock.patch("app.mailer.send_otp_email", side_effect=fake):
            res = client.post("/api/auth/register/resend", json={"email": email})
            assert res.status_code == 202, res.text
        new_code = sent2[0][1]
        assert new_code != code
        assert _verify(client, email, new_code).status_code == 200


def test_email_signup_resend_cooldown(client: TestClient) -> None:
    _, email = _start_email_signup(client, email="resend@ketsa.io")
    # Immediate resend hits the default 60s cooldown.
    res = client.post("/api/auth/register/resend", json={"email": email})
    assert res.status_code == 429
    # Nobody can verify an email that was never asked to sign up.
    assert _verify(client, "ghost@nowhere.io", "123456").status_code == 401


def test_register_phone_skips_otp(client: TestClient) -> None:
    # Phone signups are immediate (no email to verify) — unchanged behavior.
    res = client.post(
        "/api/auth/register",
        json={"name": "Phona Gwede", "identifier": "0997 654 321", "password": "password123"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["user"]["id"] == "997654321"


def test_forgot_password_no_account_oracle(client: TestClient) -> None:
    sent: list[tuple[str, str, str]] = []

    def fake(to, code, purpose, ttl, name="") -> bool:
        sent.append((to, code, purpose))
        return True

    with mock.patch("app.mailer.send_otp_email", side_effect=fake):
        # Unknown email, phone identifier, junk — all 200 ok, nothing sent.
        for identifier in ("nobody@nowhere.io", "0991234567", "!!"):
            res = client.post(
                "/api/auth/forgot-password", json={"identifier": identifier}
            )
            assert res.status_code == 200, identifier
            assert res.json() == {"ok": True}
        assert sent == []


def test_forgot_password_reset_flow(client: TestClient) -> None:
    reg = _register(client, email="resetable@ketsa.io")

    sent: list[tuple[str, str, str]] = []

    def fake(to, code, purpose, ttl, name="") -> bool:
        sent.append((to, code, purpose))
        return True

    with mock.patch("app.mailer.send_otp_email", side_effect=fake):
        # Case-insensitive identifier resolution.
        res = client.post(
            "/api/auth/forgot-password", json={"identifier": "RESETABLE@ketsa.io"}
        )
        assert res.status_code == 200
    assert len(sent) == 1 and sent[0][2] == "reset"
    code = sent[0][1]

    # Wrong code → 401.
    assert client.post(
        "/api/auth/reset-password",
        json={"email": "resetable@ketsa.io", "otp": "000000", "new_password": "brandnew123"},
    ).status_code == 401

    # Short new password → 400 and the code is NOT consumed.
    assert client.post(
        "/api/auth/reset-password",
        json={"email": "resetable@ketsa.io", "otp": code, "new_password": "short"},
    ).status_code == 400

    # Reset succeeds.
    res = client.post(
        "/api/auth/reset-password",
        json={"email": "resetable@ketsa.io", "otp": code, "new_password": "brandnew123"},
    )
    assert res.status_code == 200 and res.json() == {"ok": True}

    # Single-use: replaying the code fails.
    assert client.post(
        "/api/auth/reset-password",
        json={"email": "resetable@ketsa.io", "otp": code, "new_password": "brandnew123"},
    ).status_code == 401

    # Old sessions revoked, old password dead, new password works.
    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {reg['token']}"}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"identifier": "resetable@ketsa.io", "password": "password123"}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"identifier": "resetable@ketsa.io", "password": "brandnew123"}
    ).status_code == 200


def test_reset_password_unknown_email_uniform(client: TestClient) -> None:
    # Same 401 as a wrong code — the endpoint can't enumerate accounts.
    res = client.post(
        "/api/auth/reset-password",
        json={"email": "ghost@nowhere.io", "otp": "654321", "new_password": "password123"},
    )
    assert res.status_code == 401


def test_otp_expired_by_ttl(client: TestClient) -> None:
    with mock.patch.dict(os.environ, {"KETSA_OTP_TTL_SECONDS": "3", "KETSA_OTP_RESEND_SECONDS": "0"}):
        sent, email = _start_email_signup(client, email="tick@ketsa.io")
        code = sent[0][1]
        # Age the entry past its TTL without sleeping.
        key = f"signup:{email}"
        authstate.expire_otp(key, time.time() - 1)
        assert _verify(client, email, code).status_code == 401
        # Resend is still possible and issues a working code.
        sent2: list[tuple[str, str, str]] = []

        def fake(to, code, purpose, ttl, name="") -> bool:
            sent2.append((to, code, purpose))
            return True

        with mock.patch("app.mailer.send_otp_email", side_effect=fake):
            assert client.post(
                "/api/auth/register/resend", json={"email": email}
            ).status_code == 202
        assert _verify(client, email, sent2[0][1]).status_code == 200