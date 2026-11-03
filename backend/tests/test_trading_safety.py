"""Regression tests for the trading safety invariants.

These protect money-adjacent behaviour that is easy to break silently:

* a rejected (insufficient-balance) buy must not consume order-book depth;
* a multi-leg slip is all-or-nothing (later failure rolls back earlier fills,
  their notifications and their tape entries);
* markets cannot be traded after their published end date or once closed.
"""

import pytest
from fastapi.testclient import TestClient

from app import store
from app.engine import engine
from app.main import create_app
from app.storage import reset_backend

FUNDS = 1000.0
MARKET = "btc-120k"
OPEN_MARKET = "eu-dma"


def _fresh() -> TestClient:
    reset_backend()
    engine.reset()
    return TestClient(create_app())


@pytest.fixture()
def client() -> TestClient:
    return _fresh()


def _wallet(client: TestClient, funds: float = FUNDS) -> dict:
    w = client.post("/api/wallet", json={"name": "Risk Tester"}).json()
    if funds:
        engine.credit_balance(w["id"], funds)
    return client.get(f"/api/wallet/{w['id']}").json()


def _trade(client: TestClient, wallet_id: str, **body):
    return client.post("/api/trade", json={"wallet_id": wallet_id, **body})


def _book(client: TestClient, market_id: str = MARKET) -> dict:
    return client.get(f"/api/markets/{market_id}/book").json()


def _set_market(market_id: str, **fields) -> None:
    market = store.get_market(market_id)
    assert market is not None
    store.upsert_market({**market, **fields})


def test_rejected_buy_does_not_consume_liquidity(client: TestClient) -> None:
    w = _wallet(client, funds=10.0)
    before = _book(client)

    res = _trade(
        client,
        w["id"],
        market_id=MARKET,
        outcome="yes",
        side="buy",
        amount=5_000.0,  # far more than the wallet holds
    )
    assert res.status_code == 400
    assert "insufficient" in res.json()["detail"].lower()

    # The probe pass must not have eaten any resting size.
    after = _book(client)
    assert after["yes"] == before["yes"]
    assert after["bids"] == before["bids"]
    assert after["asks"] == before["asks"]

    wallet = client.get(f"/api/wallet/{w['id']}").json()
    assert wallet["balance"] == 10.0
    assert wallet["positions"] == []


def test_multi_leg_failure_rolls_back_everything(client: TestClient) -> None:
    w = _wallet(client)
    before_wallet = client.get(f"/api/wallet/{w['id']}").json()
    before_book = _book(client)
    before_tape = client.get(f"/api/markets/{MARKET}/trades").json()

    res = _trade(
        client,
        w["id"],
        legs=[
            {"market_id": MARKET, "outcome": "yes", "side": "buy", "amount": 100.0},
            # Wallet has 1000; this leg's fill would exceed it, so the slip
            # must abort after leg 1 and undo it.
            {"market_id": MARKET, "outcome": "yes", "side": "buy", "amount": 10_000_000.0},
        ],
    )
    assert res.status_code == 400
    assert "leg 2" in res.json()["detail"].lower()

    after_wallet = client.get(f"/api/wallet/{w['id']}").json()
    assert after_wallet["balance"] == pytest.approx(before_wallet["balance"])
    assert after_wallet["positions"] == before_wallet["positions"]
    assert after_wallet["history"] == before_wallet["history"]

    assert _book(client) == before_book
    assert client.get(f"/api/markets/{MARKET}/trades").json() == before_tape

    # No phantom "Order filled" notices or stream events from rolled-back legs.
    notifications = client.get(
        f"/api/wallet/{w['id']}/notifications"
    ).json()
    assert not any(n.get("title") == "Order filled" for n in notifications)
    assert not any(e.get("type") == "trade" for e in engine.flush_events())

    # The wallet is still fully usable afterwards.
    ok = _trade(
        client,
        w["id"],
        market_id=MARKET,
        outcome="yes",
        side="buy",
        amount=25.0,
    )
    assert ok.status_code == 200
    assert ok.json()["wallet"]["positions"]


def test_trade_after_end_date_is_blocked(client: TestClient) -> None:
    w = _wallet(client)
    _set_market(OPEN_MARKET, end_date="2020-01-01T00:00:00Z")

    res = _trade(
        client, w["id"], market_id=OPEN_MARKET, outcome="yes", side="buy", amount=10.0
    )
    assert res.status_code == 400
    assert "end date" in res.json()["detail"].lower()

    res = _trade(
        client,
        w["id"],
        legs=[
            {"market_id": OPEN_MARKET, "outcome": "yes", "side": "buy", "amount": 10.0}
        ],
    )
    assert res.status_code == 400
    assert "end date" in res.json()["detail"].lower()
    assert client.get(f"/api/wallet/{w['id']}").json()["positions"] == []


def test_closed_market_is_blocked(client: TestClient) -> None:
    w = _wallet(client)
    _set_market(OPEN_MARKET, status="closed")

    res = _trade(
        client, w["id"], market_id=OPEN_MARKET, outcome="yes", side="buy", amount=10.0
    )
    assert res.status_code == 400
    assert "closed" in res.json()["detail"].lower()
