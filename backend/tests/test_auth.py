"""Tests for the user auth API (register / login / session)."""

import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient


def _register(client: TestClient, email: str = "alice@ketsa.io") -> dict:
    res = client.post(
        "/api/auth/register",
        json={"name": "Alice Trader", "identifier": email, "password": "password123"},
    )
    assert res.status_code == 200
    return res.json()


def test_register_creates_account_and_wallet(client: TestClient) -> None:
    body = _register(client)
    assert body["token"]
    assert body["user"]["email"] == "alice@ketsa.io"
    assert "wallet_id" in body["user"]
    assert body["wallet"]["id"] == body["user"]["wallet_id"]
    assert body["wallet"]["balance"] > 0


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
    notes = client.get(f"/api/wallet/{wid}/notifications").json()
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
    resp = client.post(
        "/api/trade",
        json={"wallet_id": wid, "market_id": "btc-120k", "outcome": "yes", "side": "buy", "amount": 25.0},
    )
    assert resp.status_code == 200


def test_account_trade_with_own_token(client: TestClient) -> None:
    reg = _register(client, email="gate@ketsa.io")
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