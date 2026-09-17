"""Tests for market resolution: settlement, payout accounting, trading locks,
the admin resolve endpoint, and the live WebSocket resolution/notification
push."""

import pytest
from fastapi.testclient import TestClient

from app.engine import engine, WALLET_START_BALANCE


def _wallet(client: TestClient, name="Tester") -> dict:
    return client.post("/api/wallet", json={"name": name}).json()


def _buy(client: TestClient, wallet_id: str, market_id: str, outcome: str,
         amount: float) -> dict:
    return client.post(
        "/api/trade",
        json={
            "wallet_id": wallet_id,
            "market_id": market_id,
            "outcome": outcome,
            "side": "buy",
            "amount": amount,
        },
    ).json()


def _admin_token(client: TestClient) -> str:
    resp = client.post("/api/admin/login", json={"password": "ketsa-admin"})
    assert resp.status_code == 200
    return resp.json()["token"]


# --- Settlement ------------------------------------------------------------


def test_resolve_yes_pays_winners_and_clears_positions(client: TestClient) -> None:
    w = _wallet(client, "Winner")
    buy = _buy(client, w["id"], "nova-finals", "yes", 40.0)
    shares = buy["wallet"]["positions"][0]["shares"]

    result = engine.resolve_market("nova-finals", "yes")
    assert result["outcome"] == "yes"
    assert result["wallets_settled"] == 1
    assert result["total_payout"] == pytest.approx(shares, abs=0.01)

    wallet = client.get(f"/api/wallet/{w['id']}").json()
    assert wallet["balance"] == pytest.approx(WALLET_START_BALANCE - 40.0 + shares, abs=0.01)
    assert all(p["market_id"] != "nova-finals" for p in wallet["positions"])
    res_entries = [h for h in wallet["history"] if h.get("kind") == "resolution"]
    assert len(res_entries) == 1
    entry = res_entries[0]
    assert entry["side"] == "sell"
    assert entry["price"] == 100
    assert entry["qty"] == pytest.approx(shares, abs=0.01)
    assert entry["notional"] == pytest.approx(shares, abs=0.01)


def test_resolve_no_pays_no_holders_and_writes_loss_for_yes(client: TestClient) -> None:
    w = _wallet(client, "NoBettor")
    buy = _buy(client, w["id"], "fed-cuts", "no", 30.0)
    shares = buy["wallet"]["positions"][0]["shares"]
    w2 = _wallet(client, "YesLose")
    _buy(client, w2["id"], "fed-cuts", "yes", 25.0)

    result = engine.resolve_market("fed-cuts", "no")
    assert result["wallets_settled"] == 2

    wallet = client.get(f"/api/wallet/{w['id']}").json()
    assert wallet["balance"] == pytest.approx(WALLET_START_BALANCE - 30.0 + shares, abs=0.01)
    assert all(p["market_id"] != "fed-cuts" for p in wallet["positions"])
    entry = [h for h in wallet["history"] if h.get("kind") == "resolution"][0]
    assert entry["price"] == 100  # NO became worth 100¢

    # A YES holder loses: no payout, position zeroed, and a 0¢ resolution
    # entry is recorded so the ledger stays complete.
    wallet2 = client.get(f"/api/wallet/{w2['id']}").json()
    assert wallet2["balance"] == pytest.approx(WALLET_START_BALANCE - 25.0, abs=0.01)
    assert all(p["market_id"] != "fed-cuts" for p in wallet2["positions"])
    loss = [h for h in wallet2["history"] if h.get("kind") == "resolution"][0]
    assert loss["price"] == 0
    assert loss["notional"] == 0


def test_unrelated_wallet_is_untouched(client: TestClient) -> None:
    w = _wallet(client, "Bystander")
    _buy(client, w["id"], "ai-10t", "yes", 20.0)
    before = client.get(f"/api/wallet/{w['id']}").json()
    engine.resolve_market("nova-finals", "yes")
    after = client.get(f"/api/wallet/{w['id']}").json()
    assert after["balance"] == before["balance"]
    assert len(after["positions"]) == len(before["positions"])


def test_resolve_twice_and_unknown_market(client: TestClient) -> None:
    engine.resolve_market("nova-finals", "yes")
    with pytest.raises(ValueError):
        engine.resolve_market("nova-finals", "no")
    with pytest.raises(ValueError):
        engine.resolve_market("does-not-exist", "yes")
    with pytest.raises(ValueError):
        engine.resolve_market("nova-finals", "maybe")


# --- Trading locks ---------------------------------------------------------


def test_trade_rejected_after_resolution(client: TestClient) -> None:
    w = _wallet(client, "Late")
    engine.resolve_market("nova-finals", "yes")
    res = client.post(
        "/api/trade",
        json={
            "wallet_id": w["id"],
            "market_id": "nova-finals",
            "outcome": "yes",
            "side": "buy",
            "amount": 20.0,
        },
    )
    assert res.status_code == 400
    assert "resolved" in res.json()["detail"].lower()


def test_resolved_market_snapshot_and_book(client: TestClient) -> None:
    _wallet(client, "Trader")
    engine.resolve_market("btc-120k", "yes")
    m = client.get("/api/markets/btc-120k").json()
    assert m["status"] == "resolved"
    assert m["resolved_outcome"] == "yes"
    assert m["resolved_price"] == 100
    assert m["yes"] == 100
    assert m["no"] == 0
    book = client.get("/api/markets/btc-120k/book").json()
    assert book["bids"] == []
    assert book["asks"] == []
    assert book["yes"] == 100


def test_random_tick_skips_resolved_markets(client: TestClient) -> None:
    engine.resolve_market("eth-gas", "no")
    before = engine.snapshot_market("eth-gas")
    for _ in range(5):
        engine.random_tick()
    after = engine.snapshot_market("eth-gas")
    assert after["yes"] == before["yes"] == 0
    assert after["resolved_outcome"] == "no"


# --- Admin endpoint --------------------------------------------------------


def test_admin_resolve_endpoint(client: TestClient) -> None:
    _wallet(client, "Trader")
    token = _admin_token(client)
    res = client.post(
        "/api/admin/markets/nova-finals/resolve",
        json={"outcome": "no"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert "Resolved nova-finals" in res.json()["detail"]
    m = client.get("/api/markets/nova-finals").json()
    assert m["status"] == "resolved"
    assert m["resolved_outcome"] == "no"

    # Already resolved — reject.
    again = client.post(
        "/api/admin/markets/nova-finals/resolve",
        json={"outcome": "yes"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert again.status_code == 400


def test_admin_resolve_requires_auth(client: TestClient) -> None:
    res = client.post("/api/admin/markets/nova-finals/resolve", json={"outcome": "yes"})
    assert res.status_code == 401


# --- Live push -------------------------------------------------------------


class _FakeWS:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_text(self, message: str) -> None:
        import json as _json
        self.sent.append(_json.loads(message))


def _run(coro) -> None:
    import asyncio
    asyncio.run(coro)


def test_connection_manager_filters_notifications_by_subscription() -> None:
    from app.main import ConnectionManager
    import json as _json

    ws_a, ws_b, ws_c = _FakeWS(), _FakeWS(), _FakeWS()
    mgr = ConnectionManager()
    for ws in (ws_a, ws_b, ws_c):
        mgr._connections.add(ws)
        mgr._subs[ws] = None
    mgr.subscribe(ws_a, "wA")      # A subscribes to its own wallet
    mgr.subscribe(ws_b, "wB")      # B subscribes to its own wallet
    # ws_c: unsubscribed bystander.

    _run(mgr.broadcast(_json.dumps({"type": "notification", "notification": {"wallet_id": "wA"}})))
    _run(mgr.broadcast(_json.dumps({"type": "notification", "notification": {"wallet_id": "wB"}})))
    _run(mgr.broadcast(_json.dumps({"type": "resolution", "market_id": "m", "outcome": "yes"})))
    _run(mgr.broadcast(_json.dumps({"type": "leaderboard"})))

    # Everyone gets public events...
    for ws in (ws_a, ws_b, ws_c):
        types = [m["type"] for m in ws.sent]
        assert "resolution" in types and "leaderboard" in types
    # ...but notifications are strictly wallet-scoped.
    a_notices = [m for m in ws_a.sent if m["type"] == "notification"]
    b_notices = [m for m in ws_b.sent if m["type"] == "notification"]
    c_notices = [m for m in ws_c.sent if m["type"] == "notification"]
    assert a_notices == [{"type": "notification", "notification": {"wallet_id": "wA"}}]
    assert b_notices == [{"type": "notification", "notification": {"wallet_id": "wB"}}]
    assert c_notices == []


def test_subscribed_socket_receives_own_notification_on_resolve(
    client: TestClient,
) -> None:
    w = _wallet(client, "Winner")
    _buy(client, w["id"], "nova-finals", "yes", 40.0)
    token = _admin_token(client)

    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"type": "sub", "wallet_id": w["id"]})

        resp = client.post(
            "/api/admin/markets/nova-finals/resolve",
            json={"outcome": "yes"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        saw_resolution = False
        saw_notification = False
        for _ in range(10):
            payload = ws.receive_json()
            if payload.get("type") == "resolution" and payload["market_id"] == "nova-finals":
                saw_resolution = True
            if payload.get("type") == "notification":
                notif = payload["notification"]
                if notif["wallet_id"] == w["id"] and "Market resolved" in notif["title"]:
                    saw_notification = True
            if saw_resolution and saw_notification:
                break
        assert saw_resolution
        assert saw_notification


def test_leaderboard_event_fired_on_resolution(client: TestClient) -> None:
    _wallet(client, "Trader")
    token = _admin_token(client)
    with client.websocket_connect("/api/ws") as ws:
        client.post(
            "/api/admin/markets/nova-finals/resolve",
            json={"outcome": "yes"},
            headers={"Authorization": f"Bearer {token}"},
        )
        saw = False
        for _ in range(10):
            payload = ws.receive_json()
            if payload.get("type") == "leaderboard":
                saw = True
                break
        assert saw


def test_wallet_subscription_message_is_optional(client: TestClient) -> None:
    # Plain connects (no sub message) still receive the public feed.
    token = _admin_token(client)
    with client.websocket_connect("/api/ws") as ws:
        client.post(
            "/api/admin/markets/nova-finals/resolve",
            json={"outcome": "yes"},
            headers={"Authorization": f"Bearer {token}"},
        )
        saw_market = False
        for _ in range(6):
            payload = ws.receive_json()
            if payload.get("type") == "market" and payload["market"]["id"] == "nova-finals":
                saw_market = True
                break
        assert saw_market