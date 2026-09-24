"""Tests for leaderboard, per-wallet notifications, and admin user management."""

from fastapi.testclient import TestClient

from conftest import register_user


def _admin_token(client: TestClient) -> str:
    resp = client.post("/api/admin/login", json={"password": "ketsa-admin"})
    assert resp.status_code == 200
    return resp.json()["token"]


def _register(client: TestClient, email: str = "alice@ketsa.io") -> dict:
    return register_user(client, identifier=email, name="Alice Trader")


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

def test_leaderboard_ranks_wallets(client: TestClient) -> None:
    _create_guest(client, "One")
    _create_guest(client, "Two")
    rows = client.get("/api/leaderboard").json()

    assert len(rows) >= 2
    assert rows[0]["rank"] == 1
    assert all(r["currency"] == "MWK" for r in rows)
    # Sorted by equity, descending.
    equities = [r["equity"] for r in rows]
    assert equities == sorted(equities, reverse=True)


def test_leaderboard_respects_limit(client: TestClient) -> None:
    for _ in range(4):
        _create_guest(client, "X")
    rows = client.get("/api/leaderboard?limit=2").json()
    assert len(rows) == 2


def _create_guest(client: TestClient, name: str) -> dict:
    resp = client.post("/api/wallet", json={"name": name})
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def test_fill_creates_notification(client: TestClient) -> None:
    wid = _create_guest(client, "Trader")["id"]
    assert client.post(
        "/api/trade",
        json={"wallet_id": wid, "market_id": "btc-120k", "outcome": "yes", "side": "buy", "amount": 25.0},
    ).status_code == 200

    notes = client.get(f"/api/wallet/{wid}/notifications").json()
    assert len(notes) == 1
    assert notes[0]["type"] == "fill"
    assert not notes[0]["read"]
    assert "Bought" in notes[0]["message"]
    assert "BTC" in notes[0]["message"]


def test_mark_notifications_read(client: TestClient) -> None:
    wid = _create_guest(client, "Reader")["id"]
    client.post(
        "/api/trade",
        json={"wallet_id": wid, "market_id": "btc-120k", "outcome": "yes", "side": "buy", "amount": 10.0},
    )
    note_id = client.get(f"/api/wallet/{wid}/notifications").json()[0]["id"]

    resp = client.post(
        f"/api/wallet/{wid}/notifications/read", json={"ids": [note_id]}
    )
    assert resp.status_code == 200
    assert resp.json()["marked"] == 1

    notes = client.get(f"/api/wallet/{wid}/notifications").json()
    assert all(n["read"] for n in notes)


def test_mark_all_notifications_read(client: TestClient) -> None:
    wid = _create_guest(client, "All")["id"]
    for _ in range(3):
        client.post(
            "/api/trade",
            json={"wallet_id": wid, "market_id": "btc-120k", "outcome": "no", "side": "buy", "amount": 8.0},
        )
    resp = client.post(f"/api/wallet/{wid}/notifications/read", json={"ids": []})
    assert resp.json()["marked"] == 3
    notes = client.get(f"/api/wallet/{wid}/notifications").json()
    assert all(n["read"] for n in notes)


def test_notifications_are_wallet_scoped(client: TestClient) -> None:
    w1 = _create_guest(client, "One")["id"]
    w2 = _create_guest(client, "Two")["id"]
    client.post(
        "/api/trade",
        json={"wallet_id": w1, "market_id": "btc-120k", "outcome": "yes", "side": "buy", "amount": 12.0},
    )
    assert len(client.get(f"/api/wallet/{w1}/notifications").json()) == 1
    assert client.get(f"/api/wallet/{w2}/notifications").json() == []


# ---------------------------------------------------------------------------
# Admin user management
# ---------------------------------------------------------------------------

def test_admin_users_list(client: TestClient) -> None:
    token = _admin_token(client)
    _register(client, email="adminview@ketsa.io")
    rows = client.get("/api/admin/users", headers=_auth(token)).json()

    row = next(r for r in rows if r["email"] == "adminview@ketsa.io")
    assert row["name"] == "Alice Trader"
    assert row["wallet_equity"] and row["wallet_equity"] > 0
    assert row["positions"] >= 0


def test_admin_users_requires_token(client: TestClient) -> None:
    assert client.get("/api/admin/users").status_code == 401


def test_admin_reset_password(client: TestClient) -> None:
    token = _admin_token(client)
    reg = _register(client, email="resetme@ketsa.io")

    # Unknown user → 404
    resp = client.post(
        "/api/admin/users/reset-password",
        json={"identifier": "nobody@ketsa.io", "new_password": "brandnewpass1"},
        headers=_auth(token),
    )
    assert resp.status_code == 404

    # Short password → 400
    resp = client.post(
        "/api/admin/users/reset-password",
        json={"identifier": "resetme@ketsa.io", "new_password": "short"},
        headers=_auth(token),
    )
    assert resp.status_code == 400

    # Successful reset
    resp = client.post(
        "/api/admin/users/reset-password",
        json={"identifier": "resetme@ketsa.io", "new_password": "brandnewpass1"},
        headers=_auth(token),
    )
    assert resp.status_code == 200

    # Old password revoked + previous session invalidated
    assert client.get("/api/auth/me", headers=_auth(reg["token"])).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"identifier": "resetme@ketsa.io", "password": "password123"},
    ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"identifier": "resetme@ketsa.io", "password": "brandnewpass1"},
    ).status_code == 200


def test_admin_delete_user(client: TestClient) -> None:
    token = _admin_token(client)
    reg = _register(client, email="deleteme@ketsa.io")

    resp = client.delete(f"/api/admin/users/{reg['user']['id']}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    rows = client.get("/api/admin/users", headers=_auth(token)).json()
    assert all(r["email"] != "deleteme@ketsa.io" for r in rows)
    # The deleted user's session is now unusable.
    assert client.get("/api/auth/me", headers=_auth(reg["token"])).status_code == 401


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}