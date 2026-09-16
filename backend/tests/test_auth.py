"""Tests for the user auth API (register / login / session)."""

import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient


def _register(client: TestClient, email: str = "alice@ketsa.io") -> dict:
    res = client.post(
        "/api/auth/register",
        json={"name": "Alice Trader", "email": email, "password": "password123"},
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
        json={"name": "X", "email": "a@b.io", "password": "password123"},
    ).status_code == 400
    assert client.post(
        "/api/auth/register",
        json={"name": "Alice", "email": "not-an-email", "password": "password123"},
    ).status_code == 400
    assert client.post(
        "/api/auth/register",
        json={"name": "Alice", "email": "a@b.io", "password": "short"},
    ).status_code == 400


def test_register_duplicate_email(client: TestClient) -> None:
    _register(client)
    assert client.post(
        "/api/auth/register",
        json={"name": "Bob", "email": "alice@ketsa.io", "password": "password123"},
    ).status_code == 409


def test_login_success_and_failure(client: TestClient) -> None:
    _register(client)
    ok = client.post(
        "/api/auth/login",
        json={"email": "alice@ketsa.io", "password": "password123"},
    )
    assert ok.status_code == 200
    assert ok.json()["token"]
    assert ok.json()["user"]["email"] == "alice@ketsa.io"

    bad = client.post(
        "/api/auth/login",
        json={"email": "alice@ketsa.io", "password": "wrongpass"},
    )
    assert bad.status_code == 401

    missing = client.post(
        "/api/auth/login",
        json={"email": "nobody@ketsa.io", "password": "password123"},
    )
    assert missing.status_code == 401


def test_login_returns_same_wallet(client: TestClient) -> None:
    reg = _register(client)
    login = client.post(
        "/api/auth/login",
        json={"email": "alice@ketsa.io", "password": "password123"},
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
                json={"email": "throttle@ketsa.io", "password": "bad"},
            )
        # Third attempt with bad password → 429
        resp = client.post(
            "/api/auth/login",
            json={"email": "throttle@ketsa.io", "password": "bad"},
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
        json={"email": "pw@ketsa.io", "password": "password123"},
    ).status_code == 401

    # New password logs in
    assert client.post(
        "/api/auth/login",
        json={"email": "pw@ketsa.io", "password": "newpassword1"},
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