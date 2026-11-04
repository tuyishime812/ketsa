"""Tests for the admin API (auth, CRUD, settings) and editable content."""

import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app.storage import reset_backend


def _import_app():
    from app.main import create_app
    return create_app()


@pytest.fixture()
def admin_client() -> TestClient:
    """Admin client with a fresh in-memory store and a known admin password.

    The env patch (which includes the admin password) stays active for the whole
    test so login requests can read it at request time.
    """
    reset_backend()
    with mock.patch.dict(
        os.environ,
        {
            "KETSA_RATE_LIMIT_PER_MIN": "0",
            "KETSA_ADMIN_PASSWORD": "pw123",
        },
        clear=False,
    ):
        client = TestClient(_import_app())
        yield client


def make_public() -> TestClient:
    return TestClient(_import_app())


def _auth(client: TestClient, password: str = "pw123") -> dict[str, str]:
    r = client.post("/api/admin/login", json={"password": password})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_login_requires_valid_password_client(admin_client: TestClient) -> None:
    assert admin_client.post("/api/admin/login", json={"password": "nope"}).status_code == 401
    assert admin_client.post("/api/admin/login", json={"password": "pw123"}).status_code == 200


def test_admin_requires_token(admin_client: TestClient) -> None:
    # No token -> 401 on a protected endpoint.
    assert admin_client.get("/api/admin/settings").status_code == 401
    assert admin_client.get(
        "/api/admin/settings", headers={"Authorization": "Bearer bogus"}
    ).status_code == 401


def test_market_crud(admin_client: TestClient) -> None:
    headers = _auth(admin_client)
    market = {
        "id": "test-market",
        "cat": "tech",
        "tag": "Tech",
        "q": "Will a test market resolve?",
        "yes": 42,
        "no": 58,
        "meta": ["$1M vol", "2K traders"],
        "trend": "up",
        "pts": [10, 12, 14, 16],
    }
    assert admin_client.put("/api/admin/markets", json=market, headers=headers).status_code == 200
    public = make_public()
    detail = public.get("/api/markets/test-market")
    assert detail.status_code == 200
    assert detail.json()["q"] == market["q"]
    market["yes"] = 60
    market["no"] = 40
    assert admin_client.put("/api/admin/markets", json=market, headers=headers).status_code == 200
    assert public.get("/api/markets/test-market").json()["yes"] == 60
    assert admin_client.delete("/api/admin/markets/test-market", headers=headers).status_code == 200
    assert public.get("/api/markets/test-market").status_code == 404


def _market_payload(market_id: str = "validation-market") -> dict:
    return {
        "id": market_id,
        "cat": "tech",
        "tag": "Tech",
        "q": "Will this market pass validation?",
        "yes": 50,
        "no": 50,
        "meta": ["$1M vol", "2K traders"],
        "trend": "up",
        "pts": [10, 12, 14, 16],
    }


def test_market_id_cannot_overwrite_content(admin_client: TestClient) -> None:
    """Market ids share the kv table with settings/watch/ticker."""
    headers = _auth(admin_client)
    market = _market_payload("settings")

    r = admin_client.put("/api/admin/markets", json=market, headers=headers)
    assert r.status_code == 400
    # The content row is still readable rather than replaced by a market.
    assert admin_client.get("/api/admin/settings", headers=headers).status_code == 200


def test_market_payload_is_validated(admin_client: TestClient) -> None:
    headers = _auth(admin_client)

    assert admin_client.put(
        "/api/admin/markets",
        json={**_market_payload(), "id": "Not A Slug"},
        headers=headers,
    ).status_code == 422
    assert admin_client.put(
        "/api/admin/markets",
        json={**_market_payload(), "yes": 60, "no": 60},
        headers=headers,
    ).status_code == 422
    assert admin_client.put(
        "/api/admin/markets",
        json={**_market_payload(), "q": "   "},
        headers=headers,
    ).status_code == 422


def test_market_update_preserves_resolution_fields(admin_client: TestClient) -> None:
    headers = _auth(admin_client)
    market = _market_payload("settled-market")

    assert admin_client.post(
        "/api/admin/markets", json=market, headers=headers
    ).status_code == 200
    assert admin_client.post(
        "/api/admin/markets/settled-market/resolve",
        json={"outcome": "yes"},
        headers=headers,
    ).status_code == 200

    before = admin_client.get("/api/markets/settled-market").json()
    assert before["resolved_outcome"] == "yes"

    # Reopening a settled market through the content endpoint must fail.
    reopen = {**market, "status": "open"}
    assert admin_client.put(
        "/api/admin/markets", json=reopen, headers=headers
    ).status_code == 400

    # The editor does not submit resolved_* fields; a full-row replace would
    # wipe the settlement record. The update path must merge instead.
    edit = {**market, "status": "resolved", "q": "Edited after settlement?"}
    assert admin_client.put(
        "/api/admin/markets", json=edit, headers=headers
    ).status_code == 200

    after = admin_client.get("/api/markets/settled-market").json()
    assert after["resolved_outcome"] == "yes"
    assert after["resolved_price"] == before["resolved_price"]
    assert after["resolved_ts"] == before["resolved_ts"]


def test_market_write_cannot_forge_settlement(admin_client: TestClient) -> None:
    """markets:write must not be able to declare a payout result."""
    headers = _auth(admin_client)
    market = _market_payload("forge-market")
    forged = {
        **market,
        "resolved_outcome": "yes",
        "resolved_price": 100,
        "resolved_ts": 1.0,
    }

    assert admin_client.put(
        "/api/admin/markets", json=forged, headers=headers
    ).status_code == 400
    assert admin_client.post(
        "/api/admin/markets", json=forged, headers=headers
    ).status_code == 400

    # Even the status flip must go through the resolve action.
    premature = {**market, "status": "resolved"}
    assert admin_client.post(
        "/api/admin/markets", json=premature, headers=headers
    ).status_code == 400


def test_market_create_rejects_duplicate_id(admin_client: TestClient) -> None:
    headers = _auth(admin_client)
    market = _market_payload("duplicate-market")

    assert admin_client.post(
        "/api/admin/markets", json=market, headers=headers
    ).status_code == 200
    assert admin_client.post(
        "/api/admin/markets", json=market, headers=headers
    ).status_code == 409


def test_market_create_stamps_listing_time(admin_client: TestClient) -> None:
    headers = _auth(admin_client)
    market = _market_payload("created-market")

    assert admin_client.post(
        "/api/admin/markets", json=market, headers=headers
    ).status_code == 200

    detail = make_public().get("/api/markets/created-market")
    assert detail.status_code == 200
    assert detail.json()["created"]


def test_settings_edit_reflected_public(admin_client: TestClient) -> None:
    headers = _auth(admin_client)
    new_hero = {
        "hero": {
            "headline_1": "Trade on ",
            "headline_accent": "whatever matters.",
            "description": "An admin-edited description.",
            "badge": "$1M traded today",
        }
    }
    assert admin_client.put("/api/admin/settings", json=new_hero, headers=headers).status_code == 200
    home = make_public().get("/api/home").json()
    assert home["settings"]["hero"]["badge"] == "$1M traded today"
    assert home["settings"]["hero"]["description"] == "An admin-edited description."


def test_ticker_and_watch_replace(admin_client: TestClient) -> None:
    headers = _auth(admin_client)
    ticker = [{"t": "A", "v": "50¢", "d": "up"}, {"t": "B", "v": "30¢", "d": "down"}]
    assert admin_client.put("/api/admin/ticker", json=ticker, headers=headers).status_code == 200
    public = make_public()
    assert [i["t"] for i in public.get("/api/ticker").json()] == ["A", "B"]

    watch = [{"name": "W1", "cat": "tech", "price": 55, "pts": [10, 20, 30]}]
    assert admin_client.put("/api/admin/watch", json=watch, headers=headers).status_code == 200
    assert len(public.get("/api/watch").json()) == 1
    assert public.get("/api/watch").json()[0]["name"] == "W1"


def test_dashboard_and_stats_save(admin_client: TestClient) -> None:
    headers = _auth(admin_client)
    dash = {
        "ranges": {
            "1D": {"pts": [100, 110], "balance": 110, "change": 10.0},
            "1W": {"pts": [90, 100], "balance": 100, "change": 5.5},
        },
        "positions": [{"name": "P", "avg": 30, "cur": 40, "pts": [10, 20]}],
    }
    assert admin_client.put("/api/admin/dashboard", json=dash, headers=headers).status_code == 200
    public = make_public()
    assert public.get("/api/dashboard").json()["ranges"]["1D"]["balance"] == 110
    assert public.get("/api/dashboard").json()["positions"][0]["name"] == "P"
    stats = {"pnl": 5000, "open_positions": 7, "win_rate": 71}
    assert admin_client.put("/api/admin/stats", json=stats, headers=headers).status_code == 200
    assert public.get("/api/stats").json() == stats


def test_proof_save(admin_client: TestClient) -> None:
    headers = _auth(admin_client)
    proof = {"traders_k": 500, "live_markets": 1500, "total_volume_m": 120.5}
    assert admin_client.put("/api/admin/proof", json=proof, headers=headers).status_code == 200
    assert make_public().get("/api/proof").json() == proof


def test_logout_revokes_token(admin_client: TestClient) -> None:
    headers = _auth(admin_client)
    assert admin_client.get("/api/admin/me", headers=headers).status_code == 200
    assert admin_client.post("/api/admin/logout", headers=headers).status_code == 200
    assert admin_client.get("/api/admin/me", headers=headers).status_code == 401


def test_change_password(admin_client: TestClient) -> None:
    headers = _auth(admin_client)
    # Wrong current password rejected.
    resp = admin_client.post(
        "/api/admin/password",
        json={"current": "wrong", "new": "newpassword123"},
        headers=headers,
    )
    assert resp.status_code == 401
    # Too-short new password rejected.
    resp = admin_client.post(
        "/api/admin/password",
        json={"current": "pw123", "new": "short"},
        headers=headers,
    )
    assert resp.status_code == 400
    # Valid change.
    resp = admin_client.post(
        "/api/admin/password",
        json={"current": "pw123", "new": "newpassword123"},
        headers=headers,
    )
    assert resp.status_code == 200
    # Old password no longer works; new one does (persisted in the store).
    assert admin_client.post("/api/admin/login", json={"password": "pw123"}).status_code == 401
    assert admin_client.post("/api/admin/login", json={"password": "newpassword123"}).status_code == 200


def test_reset_restores_seed(admin_client: TestClient) -> None:
    headers = _auth(admin_client)
    # Mutate: create a custom market, change a setting, change hero.
    market = {
        "id": "custom-market",
        "cat": "tech",
        "tag": "Tech",
        "q": "Custom?",
        "yes": 30,
        "no": 70,
        "meta": ["a", "b"],
        "trend": "up",
        "pts": [10, 12],
    }
    assert admin_client.put("/api/admin/markets", json=market, headers=headers).status_code == 200
    assert admin_client.put(
        "/api/admin/settings/hero",
        json={"headline_1": "X", "headline_accent": "Y", "description": "Z", "badge": "B"},
        headers=headers,
    ).status_code == 200

    public_before = make_public()
    assert public_before.get("/api/markets/custom-market").status_code == 200
    assert public_before.get("/api/home").json()["settings"]["hero"]["badge"] == "B"

    # Reset to seed.
    assert admin_client.post("/api/admin/reset", headers=headers).status_code == 200

    public_after = make_public()
    assert public_after.get("/api/markets/custom-market").status_code == 404
    home_after = public_after.get("/api/home").json()
    assert home_after["settings"]["hero"]["badge"] == "$97.4M traded this week"
    # Seed data restored (all original markets present).
    assert len(home_after["markets"]["all"]) == 9
