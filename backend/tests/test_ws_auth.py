"""Tests for the WebSocket wallet-subscription authorization (F-04/F-02 class).

The socket is a second door into a wallet's private notification feed —
deposits, withdrawals, mobile-money numbers, fills and settlement payouts.
Gating the HTTP notification endpoints is not enough if the socket accepts
any wallet id, so subscribing is authorized with the same ownership check.
"""

import json

from fastapi.testclient import TestClient

from app.engine import engine
from app.storage import reset_backend
from conftest import register_user


def _first(ws) -> dict:
    return json.loads(ws.receive_text())


def _drain(ws, want: str, limit: int = 10) -> list[dict]:
    """Collect frames of type `want` until one arrives (or `limit` is reached).

    Returns as soon as a match is found — the socket stays open afterwards, so
    looping for more would block on a frame that will never come.
    """
    out: list[dict] = []
    for _ in range(limit):
        payload = json.loads(ws.receive_text())
        if payload.get("type") == "sub_error":
            raise AssertionError(f"subscription was refused: {payload}")
        if payload.get("type") == want:
            out.append(payload[want])
            break
    return out


def test_subscribe_to_another_accounts_wallet_is_refused(client: TestClient) -> None:
    """The core regression: the socket must not be a bypass of the HTTP gate."""
    alice = register_user(client, identifier="alice@ketsa.io")
    bob = register_user(client, identifier="bob@ketsa.io")
    with client.websocket_connect("/api/ws") as ws:
        ws.send_text(
            json.dumps(
                {"type": "sub", "wallet_id": alice["wallet"]["id"], "token": bob["token"]}
            )
        )
        frame = _first(ws)
    assert frame["type"] == "sub_error"
    assert frame["status"] == 403


def test_subscribe_without_token_is_refused(client: TestClient) -> None:
    account = register_user(client, identifier="alice@ketsa.io")
    with client.websocket_connect("/api/ws") as ws:
        ws.send_text(json.dumps({"type": "sub", "wallet_id": account["wallet"]["id"]}))
        frame = _first(ws)
    assert frame["type"] == "sub_error"
    assert frame["status"] == 401


def test_subscribe_with_garbage_token_is_refused(client: TestClient) -> None:
    account = register_user(client, identifier="alice@ketsa.io")
    with client.websocket_connect("/api/ws") as ws:
        ws.send_text(
            json.dumps(
                {"type": "sub", "wallet_id": account["wallet"]["id"], "token": "not-a-token"}
            )
        )
        frame = _first(ws)
    assert frame["type"] == "sub_error"
    assert frame["status"] == 401


def test_owner_subscription_is_silent_and_accepted(client: TestClient) -> None:
    """A correct subscription produces no error frame — the feed just works."""
    account = register_user(client, identifier="alice@ketsa.io")
    wid = account["wallet"]["id"]
    engine.credit_balance(wid, 500.0)
    with client.websocket_connect("/api/ws") as ws:
        ws.send_text(
            json.dumps({"type": "sub", "wallet_id": wid, "token": account["token"]})
        )
        # A trade emits a fill notification and flushes the event queue, which
        # proves the subscription was accepted and is routing to this socket.
        res = client.post(
            "/api/trade",
            json={
                "wallet_id": wid,
                "market_id": "nova-finals",
                "outcome": "yes",
                "side": "buy",
                "amount": 10.0,
            },
            headers={"Authorization": f"Bearer {account['token']}"},
        )
        assert res.status_code == 200
        notifications = _drain(ws, "notification")
    assert notifications, "expected the owner's fill notification on the socket"
    assert notifications[0]["wallet_id"] == wid


def test_guest_wallet_subscribe_still_allowed(client: TestClient) -> None:
    """Unclaimed sim wallets keep the id-as-credential flow (no real funds)."""
    guest = client.post("/api/wallet", json={"name": "Guest"}).json()
    engine.credit_balance(guest["id"], 500.0)
    with client.websocket_connect("/api/ws") as ws:
        ws.send_text(json.dumps({"type": "sub", "wallet_id": guest["id"]}))
        res = client.post(
            "/api/trade",
            json={
                "wallet_id": guest["id"],
                "market_id": "nova-finals",
                "outcome": "yes",
                "side": "buy",
                "amount": 10.0,
            },
        )
        assert res.status_code == 200
        notifications = _drain(ws, "notification")
    assert notifications
    assert notifications[0]["wallet_id"] == guest["id"]


def test_non_sub_first_frame_is_ignored(client: TestClient) -> None:
    """A junk first frame must not subscribe anyone or crash the socket."""
    with client.websocket_connect("/api/ws") as ws:
        ws.send_text("hello?")
        ws.send_text(json.dumps({"type": "sub", "wallet_id": "0x" + "ab" * 20}))
    # Socket stayed open long enough to send both frames without erroring.


def test_ws_connection_cap_refuses_excess_clients() -> None:
    """CWE-770: the live feed must not be usable to exhaust memory."""
    import os
    from unittest import mock

    from app.main import create_app

    reset_backend()
    engine.reset()
    with mock.patch.dict(
        os.environ,
        {"KETSA_WS_MAX_CONNECTIONS": "1", "KETSA_RATE_LIMIT_PER_MIN": "0"},
        clear=False,
    ):
        client = TestClient(create_app())
        with client.websocket_connect("/api/ws") as first:
            # Cap reached. The server closes a second socket during the
            # handshake, so entering the context manager raises — we must not
            # call receive_text(), which would block forever.
            refused = False
            try:
                second = client.websocket_connect("/api/ws")
                with second:
                    pass
            except Exception:
                refused = True
            assert refused, "second socket should have been refused at the cap"
            assert first is not None
