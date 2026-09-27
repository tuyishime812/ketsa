"""Tests for the wandePay (MWK) payments layer: deposits, withdrawals,
idempotent crediting, refund-on-failure, authentication/ownership gating
(F-01…F-03), transaction + daily caps (F-05), non-finite amount rejection
(F-06) and the write-path rate limiter (F-07).

Network calls are stubbed out by monkeypatching `app.payments._http_post`;
no real funds ever move during tests.
"""

import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app import store
from app import payments as wande
from app.engine import engine
from app.main import create_app
from app.storage import reset_backend
from conftest import register_user

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


def _fresh(wande_mock: FakeWande | None = None, env: dict | None = None) -> TestClient:
    reset_backend()
    engine.reset()
    m_wande = wande_mock or FakeWande()
    extra = {"KETSA_WANDE_TOKEN": TOKEN}
    if env:
        extra = {**extra, **env}
    patcher = mock.patch.object(wande, "_http_post", m_wande)
    patcher.start()
    request_context = mock.patch.dict(os.environ, extra, clear=False)
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


def _account(client: TestClient, identifier: str = "alice@ketsa.io") -> dict:
    """Register a verified account; returns its auth body (token + user + wallet)."""
    return register_user(client, identifier=identifier, name="Alice Trader")


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _deposit(client: TestClient, token: str, wallet_id: str, amount=500.0,
             number="0888123456", correspondent="AIRTEL_MWI"):
    return client.post(
        "/api/payments/deposits",
        json={"wallet_id": wallet_id, "amount": amount, "number": number, "correspondent": correspondent},
        headers=_headers(token),
    )


def _withdraw(client: TestClient, token: str, wallet_id: str, amount=300.0,
              number="0999123456", correspondent="TNM_MWI"):
    return client.post(
        "/api/payments/withdrawals",
        json={"wallet_id": wallet_id, "amount": amount, "number": number, "correspondent": correspondent},
        headers=_headers(token),
    )


def _fund(client: TestClient, token: str, wallet_id: str, amount: float = 1000.0) -> None:
    """Credit a wallet through the real API path (deposit -> poll COMPLETED)."""
    bank = _bank(client)
    rec = _deposit(client, token, wallet_id, amount=amount).json()
    bank.deposit_status = "COMPLETED"
    client.get(f"/api/payments/{rec['id']}", headers=_headers(token))
    bank.deposit_status = "PENDING"
    bank.calls.clear()  # funding plumbing shouldn't pollute later ledger asserts


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
        account = _account(client)
        token, wallet_id = account["token"], account["wallet"]["id"]
        res = _deposit(client, token, wallet_id)
        assert res.status_code == 503
        res = _withdraw(client, token, wallet_id)
        assert res.status_code == 503
    finally:
        request_context.stop()


# --- Auth + ownership gating (F-01 / F-02 / F-03) --------------------------


def test_guest_cannot_create_deposit_or_withdrawal(client: TestClient) -> None:
    account = _account(client)
    wallet_id = account["wallet"]["id"]
    assert _deposit(client, "", wallet_id).status_code == 401
    assert _withdraw(client, "", wallet_id).status_code == 401


def test_other_users_wallet_rejected(client: TestClient) -> None:
    alice = _account(client, "alice@ketsa.io")
    bob = _account(client, "bob@ketsa.io")
    # Bob cannot move money with Alice's wallet…
    assert _deposit(client, bob["token"], alice["wallet"]["id"]).status_code == 403
    assert _withdraw(client, bob["token"], alice["wallet"]["id"]).status_code == 403
    # …nor poll her payments or list them.
    rec = _deposit(client, alice["token"], alice["wallet"]["id"], amount=200.0).json()
    assert client.get(
        f"/api/payments/{rec['id']}", headers=_headers(bob["token"])
    ).status_code == 403
    assert client.get(
        f"/api/payments?wallet_id={alice['wallet']['id']}", headers=_headers(bob["token"])
    ).status_code == 403


def test_account_wallet_read_requires_owner_token(client: TestClient) -> None:
    alice = _account(client, "alice@ketsa.io")
    bob = _account(client, "bob@ketsa.io")
    wid = alice["wallet"]["id"]
    # F-02: no token on an account-owned wallet -> 401; wrong account -> 403.
    assert client.get(f"/api/wallet/{wid}").status_code == 401
    assert client.get(f"/api/wallet/{wid}", headers=_headers(bob["token"])).status_code == 403
    assert client.get(f"/api/wallet/{wid}", headers=_headers(alice["token"])).status_code == 200
    # A guest's unclaimed wallet stays open to anyone holding its id.
    guest = client.post("/api/wallet", json={"name": "Guest"}).json()
    assert client.get(f"/api/wallet/{guest['id']}").status_code == 200
    # Payments list is strictly own-wallet.
    assert client.get("/api/payments", headers=_headers(alice["token"])).status_code == 200
    assert client.get("/api/payments").status_code == 401


def test_unclaimed_guest_wallet_cannot_touch_payments(client: TestClient) -> None:
    alice = _account(client, "alice@ketsa.io")
    guest = client.post("/api/wallet", json={"name": "Guest"}).json()
    # A token holder cannot use an unclaimed wallet for money movement either.
    assert _deposit(client, alice["token"], guest["id"]).status_code == 403
    assert _withdraw(client, alice["token"], guest["id"]).status_code == 403


# --- Deposits ---------------------------------------------------------------


def test_deposit_create_and_idempotent_credit(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    assert client.get(f"/api/wallet/{wallet_id}", headers=_headers(token)).json()["balance"] == 0.0

    res = _deposit(client, token, wallet_id, amount=500.0, number="099 9123 456")
    assert res.status_code == 200
    rec = res.json()
    assert rec["kind"] == "deposit"
    assert rec["status"] == "pending"
    assert rec["amount"] == 500.0
    assert rec["number"] == "999123456"  # spaces + leading zero stripped
    assert rec["wande_id"] == DEPOSIT_ID
    assert [c[0] for c in bank.calls] == ["deposits.php"]

    # Still pending -> no credit.
    res = client.get(f"/api/payments/{rec['id']}", headers=_headers(token))
    assert res.json()["status"] == "pending"
    balance_after_pending = client.get(f"/api/wallet/{wallet_id}", headers=_headers(token)).json()["balance"]
    assert balance_after_pending == 0.0

    # wandePay completes -> credit exactly once, even if polled twice.
    bank.deposit_status = "COMPLETED"
    res = client.get(f"/api/payments/{rec['id']}", headers=_headers(token))
    assert res.json()["status"] == "completed"
    assert res.json()["credited"] is True
    assert client.get(f"/api/wallet/{wallet_id}", headers=_headers(token)).json()["balance"] == 500.0
    res = client.get(f"/api/payments/{rec['id']}", headers=_headers(token))
    assert res.json()["credited"] is True
    assert client.get(f"/api/wallet/{wallet_id}", headers=_headers(token)).json()["balance"] == 500.0


def test_deposit_failed_is_recorded_but_not_credited(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    rec = _deposit(client, token, wallet_id, amount=200.0).json()
    bank.deposit_status = "DECLINED"
    res = client.get(f"/api/payments/{rec['id']}", headers=_headers(token))
    body = res.json()
    assert body["status"] == "failed"
    assert body["credited"] is False
    assert client.get(f"/api/wallet/{wallet_id}", headers=_headers(token)).json()["balance"] == 0.0


def test_deposit_validation(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    assert _deposit(client, token, wallet_id, amount=50.0).status_code == 400  # below minimum
    assert _deposit(client, token, wallet_id, number="123").status_code == 400  # invalid number
    res = _deposit(client, token, wallet_id, correspondent="MTN_MWI")
    assert res.status_code == 400  # unknown correspondent
    assert _deposit(client, token, wallet_id, amount=100.001).status_code == 400  # 3+ decimals
    assert len(bank.calls) == 0


def test_non_finite_amounts_rejected(client: TestClient) -> None:
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    # NaN/Infinity survive JSON parsing — the model validator must reject them.
    # (Raw bodies: httpx's json= serializer refuses NaN before it reaches the API.)
    base = {"Content-Type": "application/json", **_headers(token)}
    assert client.post(
        "/api/payments/deposits",
        content=f'{{"wallet_id": "{wallet_id}", "amount": NaN, '
        f'"number": "0888123456", "correspondent": "AIRTEL_MWI"}}',
        headers=base,
    ).status_code == 422
    assert client.post(
        "/api/payments/withdrawals",
        content=f'{{"wallet_id": "{wallet_id}", "amount": Infinity, '
        f'"number": "0888123456", "correspondent": "AIRTEL_MWI"}}',
        headers=base,
    ).status_code == 422
    assert _bank(client).calls == []


def test_unknown_wallet_rejected(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    assert _deposit(client, account["token"], "0xmissing").status_code == 404
    assert len(bank.calls) == 0


# --- Withdrawals ------------------------------------------------------------


def test_withdrawal_flow(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    _fund(client, token, wallet_id, amount=1000.0)

    res = _withdraw(client, token, wallet_id, amount=300.0, number="0999123456", correspondent="TNM_MWI")
    assert res.status_code == 200
    rec = res.json()
    assert rec["kind"] == "withdraw"
    assert rec["status"] == "pending"
    assert rec["wande_id"] == PAYOUT_ID
    assert [c[0] for c in bank.calls] == ["with.php"]
    # Funds reserved immediately.
    assert client.get(f"/api/wallet/{wallet_id}", headers=_headers(token)).json()["balance"] == 700.0

    bank.withdrawal_status = "COMPLETED"
    res = client.get(f"/api/payments/{rec['id']}", headers=_headers(token))
    assert res.json()["status"] == "completed"
    assert res.json()["rolled_back"] is False
    assert client.get(f"/api/wallet/{wallet_id}", headers=_headers(token)).json()["balance"] == 700.0


def test_withdrawal_failed_refunds_balance(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    _fund(client, token, wallet_id, amount=1000.0)

    rec = _withdraw(client, token, wallet_id, amount=200.0).json()
    bank.withdrawal_status = "ERROR"
    res = client.get(f"/api/payments/{rec['id']}", headers=_headers(token))
    body = res.json()
    assert body["status"] == "failed"
    assert body["rolled_back"] is True
    # Refunded once even when polled again.
    assert client.get(f"/api/wallet/{wallet_id}", headers=_headers(token)).json()["balance"] == 1000.0
    res = client.get(f"/api/payments/{rec['id']}", headers=_headers(token))
    assert res.json()["rolled_back"] is True
    assert client.get(f"/api/wallet/{wallet_id}", headers=_headers(token)).json()["balance"] == 1000.0


def test_withdrawal_insufficient_balance(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    res = _withdraw(client, token, wallet_id, amount=300.0)
    assert res.status_code == 400
    assert len(bank.calls) == 0


def test_min_withdrawal_below_threshold(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    _fund(client, token, wallet_id, amount=1000.0)
    res = _withdraw(client, token, wallet_id, amount=50.0)
    assert res.status_code == 400
    assert len(bank.calls) == 0


# --- Caps (F-05) ------------------------------------------------------------


def test_per_transaction_caps(client: TestClient) -> None:
    client2 = _fresh(env={"KETSA_MAX_DEPOSIT_MWK": "500", "KETSA_MAX_WITHDRAWAL_MWK": "400"})
    try:
        bank = _bank(client2)
        account = _account(client2)
        token, wallet_id = account["token"], account["wallet"]["id"]
        assert _deposit(client2, token, wallet_id, amount=600.0).status_code == 400
        _fund(client2, token, wallet_id, amount=400.0)  # under the 500 deposit cap
        assert _withdraw(client2, token, wallet_id, amount=500.0).status_code == 400
        assert _withdraw(client2, token, wallet_id, amount=300.0).status_code == 200
        assert len(bank.calls) == 1  # only the 300 withdrawal reached wandePay
    finally:
        client2._mock_cleanup[0].stop()
        client2._mock_cleanup[1].stop()


def test_daily_withdrawal_limit(client: TestClient) -> None:
    client2 = _fresh(env={"KETSA_DAILY_WITHDRAWAL_LIMIT_MWK": "400"})
    try:
        account = _account(client2)
        token, wallet_id = account["token"], account["wallet"]["id"]
        _fund(client2, token, wallet_id, amount=1000.0)
        assert _withdraw(client2, token, wallet_id, amount=250.0).status_code == 200
        assert _withdraw(client2, token, wallet_id, amount=200.0).status_code == 400
        # Limit-rejected attempts leave no record — a smaller follow-up that
        # fits the remaining window is allowed.
        assert _withdraw(client2, token, wallet_id, amount=100.0).status_code == 200
    finally:
        client2._mock_cleanup[0].stop()
        client2._mock_cleanup[1].stop()


# --- Ledger scoping (F-02) --------------------------------------------------


def test_payment_history_lists_own_records(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    _fund(client, token, wallet_id, amount=1000.0)
    d = _deposit(client, token, wallet_id, amount=250.0).json()
    c = _withdraw(client, token, wallet_id, amount=120.0).json()
    bank.deposit_status = "COMPLETED"
    client.get(f"/api/payments/{d['id']}", headers=_headers(token))

    items = client.get(f"/api/payments?wallet_id={wallet_id}", headers=_headers(token)).json()
    ids = [p["id"] for p in items]
    assert d["id"] in ids and c["id"] in ids
    by_id = {p["id"]: p for p in items}
    assert by_id[c["id"]]["status"] == "pending"
    assert store.get_payment(d["id"])["credited"] is True

    # Another account's own list does not include these rows.
    bob = _account(client, "bob@ketsa.io")
    bob_items = client.get("/api/payments", headers=_headers(bob["token"])).json()
    assert all(p["wallet_id"] == bob["wallet"]["id"] for p in bob_items)


# --- Write-path rate limiter (F-07) ----------------------------------------


def test_write_endpoints_are_strictly_rate_limited() -> None:
    client2 = _fresh(env={"KETSA_WRITE_RATE_LIMIT_PER_MIN": "2"})
    try:
        assert client2.post("/api/wallet", json={"name": "A"}).status_code == 200
        assert client2.post("/api/wallet", json={"name": "B"}).status_code == 200
        assert client2.post("/api/wallet", json={"name": "C"}).status_code == 429
        # Reads are unaffected by the write budget.
        assert client2.get("/api/markets").status_code == 200
    finally:
        client2._mock_cleanup[0].stop()
        client2._mock_cleanup[1].stop()