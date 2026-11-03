"""Tests for the marketplace layer: wallets, order books, order execution,
price discovery, and the live WebSocket feed."""

import pytest
from fastapi.testclient import TestClient

from app import store
from app.engine import engine, WALLET_START_BALANCE
from app.main import create_app
from app.storage import reset_backend


def _fresh() -> TestClient:
    reset_backend()
    engine.reset()
    return TestClient(create_app())


# Test wallets start at the real zero balance (no free mint); trading tests
# fund them explicitly so order execution can be exercised.
FUNDS = 1000.0


def _wallet(client: TestClient, name="Tester", funds: float = FUNDS) -> dict:
    w = client.post("/api/wallet", json={"name": name}).json()
    if funds:
        engine.credit_balance(w["id"], funds)
    return client.get(f"/api/wallet/{w['id']}").json()


@pytest.fixture()
def client() -> TestClient:
    return _fresh()


# --- Wallets ---------------------------------------------------------------


def test_wallet_create_and_reuse(client: TestClient) -> None:
    w = _wallet(client, "Alice", funds=0.0)  # new wallets mint at zero
    assert w["balance"] == WALLET_START_BALANCE == 0.0
    assert w["currency"] == "MWK"
    assert round(w["equity"], 2) == round(WALLET_START_BALANCE, 2)
    assert w["positions"] == []
    assert w["history"] == []
    # Same id -> same wallet (get-or-create).
    again = client.post("/api/wallet", json={"id": w["id"], "name": "Bob"}).json()
    assert again["id"] == w["id"]
    assert again["name"] == "Alice"  # existing wallet wins over new name
    # A client-supplied id for an unknown wallet is ignored — a fresh
    # server-minted id is returned instead (no id squatting).
    minted = client.post("/api/wallet", json={"id": "0x0000000000000000000000000000000000000000", "name": "Squatter"}).json()
    assert minted["id"] != "0x0000000000000000000000000000000000000000"
    fetched = client.get(f"/api/wallet/{w['id']}").json()
    assert fetched["id"] == w["id"]


def test_wallet_get_unknown_404(client: TestClient) -> None:
    assert client.get("/api/wallet/0xdeadbeef").status_code == 404


# --- Market detail fields --------------------------------------------------


def test_market_detail_fields(client: TestClient) -> None:
    m = client.get("/api/markets/btc-120k").json()
    assert m["description"]
    assert m["end_date"]
    assert m["created"]
    assert m["volume"] > 0
    assert m["liquidity"] > 0
    assert m["status"] == "open"
    assert m["yes"] + m["no"] == 100
    assert 1 <= m["yes"] <= 99


def test_all_markets_enriched(client: TestClient) -> None:
    data = client.get("/api/markets").json()
    assert len(data["all"]) >= 9
    for m in data["all"]:
        assert m["yes"] + m["no"] == 100
        assert "description" in m
        assert "end_date" in m
        assert "volume" in m


# --- Order book ------------------------------------------------------------


def test_order_book_shape(client: TestClient) -> None:
    book = client.get("/api/markets/btc-120k/book").json()
    assert book["bids"] and book["asks"]
    # YES asks ascending, YES bids descending.
    ask_prices = [lv["price"] for lv in book["asks"]]
    bid_prices = [lv["price"] for lv in book["bids"]]
    assert ask_prices == sorted(ask_prices)
    assert bid_prices == sorted(bid_prices, reverse=True)
    assert book["bids"][0]["price"] < book["asks"][0]["price"]
    assert book["spread"] == book["asks"][0]["price"] - book["bids"][0]["price"]
    assert 1 <= book["spread"] <= 99
    # NO side mirrors the YES book (complementary prices).
    assert book["no_bids"][0]["price"] == 100 - book["asks"][0]["price"]
    assert book["no_asks"][0]["price"] == 100 - book["bids"][0]["price"]


def test_order_book_unknown_404(client: TestClient) -> None:
    assert client.get("/api/markets/nope/book").status_code == 404


# --- Execution: BUY YES ----------------------------------------------------


def test_buy_yes_updates_wallet_and_market(client: TestClient) -> None:
    w = _wallet(client)
    before = client.get("/api/markets/btc-120k").json()
    res = client.post(
        "/api/trade",
        json={
            "wallet_id": w["id"],
            "market_id": "btc-120k",
            "outcome": "yes",
            "side": "buy",
            "amount": 25.0,
        },
    ).json()
    assert len(res["wallet"]["positions"]) == 1
    pos = res["wallet"]["positions"][0]
    assert pos["market_id"] == "btc-120k"
    assert pos["outcome"] == "yes"
    assert pos["shares"] > 0
    wallet_now = client.get(f"/api/wallet/{w['id']}").json()
    assert wallet_now["balance"] == pytest.approx(FUNDS - 25.0, abs=0.01)
    # Market price moved toward/at the ask, and the tape now has a trade.
    after = client.get("/api/markets/btc-120k").json()
    assert after["yes"] >= before["yes"]
    assert after["volume"] > before["volume"]
    trades = client.get("/api/markets/btc-120k/trades").json()
    assert trades and trades[0]["outcome"] == "yes"
    assert trades[0]["side"] == "buy"


def test_buy_yes_reduces_book_depth(client: TestClient) -> None:
    w = _wallet(client)
    book0 = client.get("/api/markets/nova-finals/book").json()
    total0 = sum(lv["size"] for lv in book0["asks"])
    client.post(
        "/api/trade",
        json={
            "wallet_id": w["id"],
            "market_id": "nova-finals",
            "outcome": "yes",
            "side": "buy",
            "amount": 200.0,
        },
    )
    book1 = client.get("/api/markets/nova-finals/book").json()
    total1 = sum(lv["size"] for lv in book1["asks"])
    assert total1 < total0


def test_buy_exhausting_book_is_partial_and_never_overdraws(client: TestClient) -> None:
    # A tiny market whose whole book is worth less than the wallet balance.
    store.upsert_market(
        {
            "id": "tiny", "cat": "culture", "tag": "Test", "q": "Will a tiny market fill?",
            "yes": 50, "no": 50, "meta": ["$1 vol", "1 trader"], "trend": "up",
            "pts": [50], "volume": 0.0, "liquidity": 120.0,
        }
    )
    w = _wallet(client)
    res = client.post(
        "/api/trade",
        json={
            "wallet_id": w["id"],
            "market_id": "tiny",
            "outcome": "yes",
            "side": "buy",
            "amount": 1_000.0,  # ~8x the entire book
        },
    ).json()
    assert res["market"]["volume"] < 1000  # partial fill, not the full request
    assert res["wallet"]["balance"] >= 0
    assert res["trade"]["qty"] > 0


def test_buy_beyond_balance_rejected(client: TestClient) -> None:
    w = _wallet(client)
    res = client.post(
        "/api/trade",
        json={
            "wallet_id": w["id"],
            "market_id": "ai-10t",
            "outcome": "yes",
            "side": "buy",
            "amount": 50_000.0,  # book depth is deeper, but the wallet has 1,000 MWK funded
        },
    )
    assert res.status_code == 400


# --- Execution: BUY/SELL NO -----------------------------------------------


def test_buy_no_then_sell_no(client: TestClient) -> None:
    w = _wallet(client)
    buy = client.post(
        "/api/trade",
        json={
            "wallet_id": w["id"],
            "market_id": "eu-dma",
            "outcome": "no",
            "side": "buy",
            "amount": 30.0,
        },
    ).json()
    pos = buy["wallet"]["positions"][0]
    assert pos["outcome"] == "no"
    assert pos["shares"] > 0
    assert buy["wallet"]["balance"] == pytest.approx(FUNDS - 30.0, abs=0.01)
    shares = pos["shares"]
    sell = client.post(
        "/api/trade",
        json={
            "wallet_id": w["id"],
            "market_id": "eu-dma",
            "outcome": "no",
            "side": "sell",
            "shares": shares,
        },
    ).json()
    assert sell["wallet"]["balance"] > buy["wallet"]["balance"]
    assert not any(p["outcome"] == "no" for p in sell["wallet"]["positions"])


def test_sell_without_position_rejected(client: TestClient) -> None:
    w = _wallet(client)
    res = client.post(
        "/api/trade",
        json={
            "wallet_id": w["id"],
            "market_id": "eu-dma",
            "outcome": "yes",
            "side": "sell",
            "shares": 100.0,
        },
    )
    assert res.status_code == 400


def test_yes_no_price_invariants_hold_under_trading(client: TestClient) -> None:
    w = _wallet(client)
    ids = ["btc-120k", "eu-dma", "nova-finals", "ai-10t", "hottest-year"]
    for i, market_id in enumerate(ids):
        outcome = "yes" if i % 2 == 0 else "no"
        client.post(
            "/api/trade",
            json={
                "wallet_id": w["id"],
                "market_id": market_id,
                "outcome": outcome,
                "side": "buy",
                "amount": 40.0 + i * 5,
            },
        )
        m = client.get(f"/api/markets/{market_id}").json()
        assert m["yes"] + m["no"] == 100
        assert 1 <= m["yes"] <= 99
        assert 1 <= m["no"] <= 99
        assert m["yes"] >= 10 and m["no"] >= 10


# --- Live feed -------------------------------------------------------------


def test_websocket_receives_market_and_trade_events() -> None:
    client = _fresh()
    w = _wallet(client)
    with client.websocket_connect("/api/ws") as ws:
        client.post(
            "/api/trade",
            json={
                "wallet_id": w["id"],
                "market_id": "btc-120k",
                "outcome": "yes",
                "side": "buy",
                "amount": 20.0,
            },
        )
        got_market = False
        got_trade = False
        for _ in range(10):
            payload = ws.receive_json()
            if payload.get("type") == "market" and payload["market"]["id"] == "btc-120k":
                got_market = True
            if payload.get("type") == "trade":
                got_trade = True
            if got_market and got_trade:
                break
        assert got_market, "expected a market update on the websocket"
        assert got_trade, "expected a trade event on the websocket"


def test_random_tick_keeps_invariants(client: TestClient) -> None:
    client.get("/api/markets/btc-120k/book")
    for _ in range(5):
        engine.random_tick()
        m = engine.snapshot_market("btc-120k")
        assert m["yes"] + m["no"] == 100
        assert 1 <= m["yes"] <= 99