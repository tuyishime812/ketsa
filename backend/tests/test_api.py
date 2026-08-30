"""Tests for the public API endpoints and their response shapes."""

import pytest
from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_markets_shape(client: TestClient) -> None:
    res = client.get("/api/markets")
    assert res.status_code == 200
    body = res.json()
    assert "all" in body and "by_category" in body
    # We seed 9 markets across 6 categories.
    assert len(body["all"]) == 9
    assert set(body["by_category"].keys()) >= {
        "politics",
        "crypto",
        "sports",
        "culture",
        "tech",
        "climate",
    }


def test_market_item_fields(client: TestClient) -> None:
    res = client.get("/api/markets")
    m = res.json()["all"][0]
    for field in ("id", "cat", "tag", "q", "yes", "no", "meta", "trend", "pts"):
        assert field in m, f"market missing field {field}"
    assert isinstance(m["yes"], int)
    assert isinstance(m["no"], int)
    assert len(m["meta"]) == 2
    assert all(isinstance(p, int) for p in m["pts"])


def test_market_detail_found(client: TestClient) -> None:
    res = client.get("/api/markets/btc-120k")
    assert res.status_code == 200
    assert res.json()["id"] == "btc-120k"


def test_market_detail_missing_returns_404(client: TestClient) -> None:
    res = client.get("/api/markets/does-not-exist")
    assert res.status_code == 404
    assert res.json() == {"detail": "Market not found"}


def test_watch(client: TestClient) -> None:
    res = client.get("/api/watch")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 5
    assert all("name" in i and "price" in i for i in items)


def test_ticker(client: TestClient) -> None:
    res = client.get("/api/ticker")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 8
    assert all(i["d"] in ("up", "down") for i in items)


def test_dashboard(client: TestClient) -> None:
    res = client.get("/api/dashboard")
    assert res.status_code == 200
    body = res.json()
    assert "ranges" in body and "positions" in body
    assert "1D" in body["ranges"] and "1Y" in body["ranges"]


def test_stats(client: TestClient) -> None:
    res = client.get("/api/stats")
    assert res.status_code == 200
    assert {"pnl", "open_positions", "win_rate"} <= set(res.json().keys())


def test_proof(client: TestClient) -> None:
    res = client.get("/api/proof")
    assert res.status_code == 200
    assert {"traders_k", "live_markets", "total_volume_m"} <= set(res.json().keys())


def test_home_bundle(client: TestClient) -> None:
    res = client.get("/api/home")
    assert res.status_code == 200
    body = res.json()
    for key in ("markets", "watch", "ticker", "dashboard", "stats", "proof"):
        assert key in body


def test_non_get_method_rejected(client: TestClient) -> None:
    assert client.post("/api/markets").status_code == 405
    assert client.put("/api/markets").status_code == 405
    assert client.delete("/api/markets").status_code == 405


@pytest.mark.parametrize(
    ("path", "model"),
    [
        ("/api/markets", "application/json"),
        ("/api/watch", "application/json"),
        ("/api/ticker", "application/json"),
        ("/api/dashboard", "application/json"),
        ("/api/stats", "application/json"),
        ("/api/proof", "application/json"),
        ("/api/home", "application/json"),
    ],
)
def test_json_content_type(client: TestClient, path: str, model: str) -> None:
    res = client.get(path)
    assert res.headers["content-type"].startswith(model)
