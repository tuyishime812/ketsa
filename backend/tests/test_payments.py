"""Tests for the wandePay (MWK) payments layer: deposits, withdrawals,
idempotent crediting, refund-on-failure, and configuration guards.

Network calls are stubbed out by monkeypatching `app.payments._http_post`;
no real funds ever move during tests.
"""

import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app import store
from app import payments as wande
from app.engine import engine, WALLET_START_BALANCE
from app.main import create_app
from app.storage import reset_backend

TOKEN = "test-token-123"
DEPOSIT_ID = "wande_dep_1"
PAYOUT_ID = "wande_out_1"


class FakeWande:
    """Scripted stand-in for the wandePay HTTP client."""

    def __init__(self, deposit_status="PENDING", withdrawal_status="PENDING") -> None:
        self.deposit_status = deposit_status
        self.withdrawal_status = withdrawal_status
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, data: dict, timeout: int = 30) -> dict:
        name = url.rstrip("/").rsplit("/", 1)[-1]
        self.calls.append((name, data))
        if name == "balance.php":
            return {"success": True, "message": "ok", "total_balance": "1250.00"}
        if name == "deposits.php":
            return {
                "status": "success",
                "data": {"transaction": {"id": DEPOSIT_ID, "status": "Success."}},
            }
        if name == "status.php":
            return {
                "status": "success",
                "transaction_status": self.deposit_status,
                "message": "ok",
            }
        if name == "with.php":
            return {
                "status": "success",
                "message": "payout queued",
                "data": {"payoutId": PAYOUT_ID, "status": "PENDING"},
            }
        if name == "withdrawST.php":
            return {
                "status": "success",
                "withdrawal_status": self.withdrawal_status,
                "data": {"payoutId": data.get("withdrawSTId"), "status": "PENDING"},
            }
        return {"status": "success"}


def _fresh(wande_mock: FakeWande | None = None) -> TestClient:
    reset_backend()
    engine.reset()
    if wande_mock is not None:
        m_wande = wande_mock
    else:
        m_wande = FakeWande()
    patcher = mock.patch.object(wande, "_http_post", m_wande)
    patcher.start()
    request_context = mock.patch.dict(
        os.environ, {"KETSA_WANDE_TOKEN": TOKEN}, clear=False
    )
    request_context.start()
    client = TestClient(create_app())
    client._wande_fixture = m_wande  # type: ignore[attr-defined]
    # Keep the patch alive for the lifetime of the client.
    client._mock_cleanup = (  # type: ignore[attr-defined]
        patcher,
        request_context,
    )
    return client


@pytest.fixture()
def client() -> TestClient:
    yield _fresh()


def _bank(client: TestClient) -> FakeWande:
    return client._wande_fixture  # type: ignore[attr-defined]


def _wallet(client: TestClient) -> dict:
    return client.post("/api/wallet", json={"name": "Payer"}).json()


def _deposit(client: TestClient, wallet_id: str, amount=500.0, number="0888123456", correspondent="AIRTEL_MWI") -> dict:
    return client.post(
        "/api/payments/deposits",
        json={"wallet_id": wallet_id, "amount": amount, "number": number, "correspondent": correspondent},
    )


def test_payments_503_when_token_missing() -> None:
    reset_backend()
    engine.reset()
    request_context = mock.patch.dict(
        os.environ,
        {"KETSA_WANDE_TOKEN": ""},
        clear=False,
    )
    request_context.start()
    client = TestClient(create_app())
    try:
        w = _wallet(client)
        res = _deposit(client, w["id"])
        assert res.status_code == 503
        res = client.post("/api/payments/withdrawals", json={
            "wallet_id": w["id"], "amount": 500.0, "number": "0888123456", "correspondent": "TNM_MWI"})
        assert res.status_code == 503
    finally:
        request_context.stop()


def test_deposit_create_and_idempotent_credit(client: TestClient) -> None:
    bank = _bank(client)
    w = _wallet(client)
    assert w["balance"] == WALLET_START_BALANCE

    res = _deposit(client, w["id"], amount=500.0, number="099 9123 456")
    assert res.status_code == 200
    rec = res.json()
    assert rec["kind"] == "deposit"
    assert rec["status"] == "pending"
    assert rec["amount"] == 500.0
    assert rec["number"] == "999123456"  # spaces + leading zero stripped
    assert rec["wande_id"] == DEPOSIT_ID
    assert [c[0] for c in bank.calls] == ["deposits.php"]

    # Still pending -> no credit.
    res = client.get(f"/api/payments/{rec['id']}")
    assert res.json()["status"] == "pending"
    balance_after_pending = client.get(f"/api/wallet/{w['id']}").json()["balance"]
    assert balance_after_pending == WALLET_START_BALANCE

    # wandePay completes -> credit exactly once, even if polled twice.
    bank.deposit_status = "COMPLETED"
    res = client.get(f"/api/payments/{rec['id']}")
    assert res.json()["status"] == "completed"
    assert res.json()["credited"] is True
    assert client.get(f"/api/wallet/{w['id']}").json()["balance"] == WALLET_START_BALANCE + 500.0
    res = client.get(f"/api/payments/{rec['id']}")
    assert res.json()["credited"] is True
    assert client.get(f"/api/wallet/{w['id']}").json()["balance"] == WALLET_START_BALANCE + 500.0


def test_deposit_failed_is_recorded_but_not_credited(client: TestClient) -> None:
    bank = _bank(client)
    w = _wallet(client)
    res = _deposit(client, w["id"], amount=200.0)
    rec = res.json()
    bank.deposit_status = "DECLINED"
    res = client.get(f"/api/payments/{rec['id']}")
    body = res.json()
    assert body["status"] == "failed"
    assert body["credited"] is False
    assert client.get(f"/api/wallet/{w['id']}").json()["balance"] == WALLET_START_BALANCE


def test_deposit_validation(client: TestClient) -> None:
    bank = _bank(client)
    w = _wallet(client)
    assert _deposit(client, w["id"], amount=50.0).status_code == 400  # below minimum
    assert _deposit(client, w["id"], number="123").status_code == 400  # invalid number
    res = _deposit(client, w["id"], correspondent="MTN_MWI")
    assert res.status_code == 400  # unknown correspondent
    assert len(bank.calls) == 0


def test_unknown_wallet_rejected(client: TestClient) -> None:
    bank = _bank(client)
    assert _deposit(client, "0xmissing").status_code == 404
    assert len(bank.calls) == 0


def test_withdrawal_flow(client: TestClient) -> None:
    bank = _bank(client)
    w = _wallet(client)
    res = client.post(
        "/api/payments/withdrawals",
        json={"wallet_id": w["id"], "amount": 300.0, "number": "0999123456", "correspondent": "TNM_MWI"},
    )
    assert res.status_code == 200
    rec = res.json()
    assert rec["kind"] == "withdraw"
    assert rec["status"] == "pending"
    assert rec["wande_id"] == PAYOUT_ID
    assert [c[0] for c in bank.calls] == ["with.php"]
    # Funds reserved immediately.
    assert client.get(f"/api/wallet/{w['id']}").json()["balance"] == WALLET_START_BALANCE - 300.0

    bank.withdrawal_status = "COMPLETED"
    res = client.get(f"/api/payments/{rec['id']}")
    assert res.json()["status"] == "completed"
    assert res.json()["rolled_back"] is False
    assert client.get(f"/api/wallet/{w['id']}").json()["balance"] == WALLET_START_BALANCE - 300.0


def test_withdrawal_failed_refunds_balance(client: TestClient) -> None:
    bank = _bank(client)
    w = _wallet(client)
    res = client.post(
        "/api/payments/withdrawals",
        json={"wallet_id": w["id"], "amount": 200.0, "number": "0999123456", "correspondent": "AIRTEL_MWI"},
    )
    rec = res.json()
    bank.withdrawal_status = "ERROR"
    res = client.get(f"/api/payments/{rec['id']}")
    body = res.json()
    assert body["status"] == "failed"
    assert body["rolled_back"] is True
    # Refunded once even when polled again.
    assert client.get(f"/api/wallet/{w['id']}").json()["balance"] == WALLET_START_BALANCE
    res = client.get(f"/api/payments/{rec['id']}")
    assert res.json()["rolled_back"] is True
    assert client.get(f"/api/wallet/{w['id']}").json()["balance"] == WALLET_START_BALANCE


def test_withdrawal_insufficient_balance(client: TestClient) -> None:
    bank = _bank(client)
    w = _wallet(client)
    res = client.post(
        "/api/payments/withdrawals",
        json={"wallet_id": w["id"], "amount": WALLET_START_BALANCE * 2, "number": "0999123456", "correspondent": "AIRTEL_MWI"},
    )
    assert res.status_code == 400
    assert len(bank.calls) == 0


def test_payment_history_lists_records(client: TestClient) -> None:
    bank = _bank(client)
    w = _wallet(client)
    d = _deposit(client, w["id"], amount=250.0).json()
    c = client.post(
        "/api/payments/withdrawals",
        json={"wallet_id": w["id"], "amount": 120.0, "number": "0999123456", "correspondent": "AIRTEL_MWI"},
    ).json()
    bank.deposit_status = "COMPLETED"
    client.get(f"/api/payments/{d['id']}")

    items = client.get(f"/api/payments?wallet_id={w['id']}").json()
    ids = [p["id"] for p in items]
    assert d["id"] in ids and c["id"] in ids
    by_id = {p["id"]: p for p in items}
    assert by_id[c["id"]]["status"] == "pending"
    assert store.get_payment(d["id"])["credited"] is True


def test_min_withdrawal_below_threshold(client: TestClient) -> None:
    bank = _bank(client)
    w = _wallet(client)
    res = client.post(
        "/api/payments/withdrawals",
        json={"wallet_id": w["id"], "amount": 50.0, "number": "0999123456", "correspondent": "AIRTEL_MWI"},
    )
    assert res.status_code == 400
    assert len(bank.calls) == 0