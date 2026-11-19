"""Tests for the PayChangu (MWK) payments layer.

Covers deposits, withdrawals (with admin approval), idempotent crediting,
refund-on-terminal-failure, authentication/ownership gating (F-01…F-03),
transaction + daily caps (F-05), non-finite amount rejection (F-06), the
write-path rate limiter (F-07) and the webhook (signature verification +
replay safety).

Network calls are stubbed by replacing `app.payments._http`; no real funds ever
move during tests. The fake mirrors the *documented* PayChangu payload shapes:
init responses carry `data.charge_id`, and verify responses report status at
`data.status`.
"""

import hashlib
import hmac
import json
import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app import payments as paychangu
from app import store
from app.engine import engine
from app.main import create_app
from app.storage import reset_backend
from conftest import register_user

TOKEN = "test-key"
WEBHOOK_SECRET = "test-webhook-secret"
AIRTEL_REF = "20be6c20-adeb-4b5b-a7ba-0769820df4fb"
TNM_REF = "27494cb5-ba9e-437f-a114-4e7a7686bcca"


class FakePayChangu:
    """Scripted stand-in for the PayChangu HTTP client."""

    def __init__(self, deposit_status="pending", withdrawal_status="pending") -> None:
        self.deposit_status = deposit_status
        self.withdrawal_status = withdrawal_status
        # Status PayChangu reports on the *initialize* response. Deposits are
        # normally "pending"; a payout may settle (or fail) immediately.
        self.deposit_init_status = "pending"
        self.withdrawal_init_status = "pending"
        # When set, the corresponding initialize call raises PayChanguError with
        # this HTTP status (a definitive 4xx rejection).
        self.deposit_init_error: int | None = None
        self.withdrawal_init_error: int | None = None
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method: str, path: str, data: dict | None = None, timeout: int = 30) -> dict:
        self.calls.append((method, path, data))
        if method == "POST" and path == "/mobile-money/payments/initialize":
            assert data and data.get("charge_id"), "deposit must send a charge_id"
            if self.deposit_init_error:
                raise paychangu.PayChanguError(
                    "rejected by provider", status_code=self.deposit_init_error
                )
            return {
                "status": "success",
                "message": "Payment initiated",
                "data": {"charge_id": data["charge_id"], "status": self.deposit_init_status},
            }
        if method == "GET" and path.startswith("/mobile-money/payments/") and path.endswith("/verify"):
            return {
                "status": "successful",
                "message": "ok",
                "data": {"status": self.deposit_status},
            }
        if method == "POST" and path == "/mobile-money/payouts/initialize":
            assert data and data.get("charge_id"), "payout must send a charge_id"
            if self.withdrawal_init_error:
                raise paychangu.PayChanguError(
                    "rejected by provider", status_code=self.withdrawal_init_error
                )
            return {
                "status": "success",
                "message": "payout queued",
                "data": {"charge_id": data["charge_id"], "status": self.withdrawal_init_status},
            }
        if method == "GET" and path.startswith("/mobile-money/payments/") and path.endswith("details"):
            return {
                "status": "success",
                "message": "ok",
                "data": {"status": self.withdrawal_status},
            }
        if method == "GET" and path.startswith("/balance"):
            return {"status": "success", "data": {"available_balance": "1250.00"}}
        raise AssertionError(f"unexpected PayChangu call: {method} {path}")


def _fresh(bank: FakePayChangu | None = None, env: dict | None = None) -> TestClient:
    reset_backend()
    engine.reset()
    fake = bank or FakePayChangu()
    extra = {
        "PAYCHANGU_SECRET_KEY": TOKEN,
        "PAYCHANGU_WEBHOOK_SECRET": WEBHOOK_SECRET,
        # Tests poll immediately; disable the anti-hammer throttle.
        "KETSA_PAYMENT_POLL_SECONDS": "0",
        "KETSA_ADMIN_PASSWORD": os.getenv("KETSA_ADMIN_PASSWORD", "ketsa-admin"),
    }
    if env:
        extra = {**extra, **env}
    patcher = mock.patch.object(paychangu, "_http", fake)
    patcher.start()
    request_context = mock.patch.dict(os.environ, extra, clear=False)
    request_context.start()
    client = TestClient(create_app())
    client._paychangu_fixture = fake  # type: ignore[attr-defined]
    # Keep both patches alive for the lifetime of the client.
    client._mock_cleanup = (patcher, request_context)  # type: ignore[attr-defined]
    return client


def _stop(client: TestClient) -> None:
    for patcher in client._mock_cleanup:  # type: ignore[attr-defined]
        patcher.stop()


@pytest.fixture()
def client() -> TestClient:
    yield _fresh()


def _bank(client: TestClient) -> FakePayChangu:
    return client._paychangu_fixture  # type: ignore[attr-defined]


def _admin_headers(client: TestClient) -> dict:
    res = client.post(
        "/api/admin/login",
        json={"password": os.getenv("KETSA_ADMIN_PASSWORD", "ketsa-admin")},
    )
    assert res.status_code == 200, res.text
    token = res.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _account(client: TestClient, identifier: str = "alice@ketsa.io") -> dict:
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


def _approve_withdrawal(client: TestClient, payment_id: str):
    return client.post(
        f"/api/admin/withdrawals/{payment_id}/approve",
        headers=_admin_headers(client),
    )


def _reject_withdrawal(client: TestClient, payment_id: str, reason: str | None = None):
    body = {"reason": reason} if reason else {}
    return client.post(
        f"/api/admin/withdrawals/{payment_id}/reject",
        json=body,
        headers=_admin_headers(client),
    )


def _balance(client: TestClient, token: str, wallet_id: str) -> float:
    return client.get(f"/api/wallet/{wallet_id}", headers=_headers(token)).json()["balance"]


def _fund(client: TestClient, token: str, wallet_id: str, amount: float = 1000.0) -> None:
    """Credit a wallet through the real API path (deposit -> verify completed)."""
    bank = _bank(client)
    rec = _deposit(client, token, wallet_id, amount=amount).json()
    bank.deposit_status = "success"
    client.get(f"/api/payments/{rec['id']}", headers=_headers(token))
    bank.deposit_status = "pending"
    bank.calls.clear()  # funding plumbing shouldn't pollute later ledger asserts


def _webhook(client: TestClient, payload: dict, signature: str | None = None):
    raw = json.dumps(payload).encode("utf-8")
    sig = signature or hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return client.post(
        "/api/payments/webhook",
        content=raw,
        headers={"Content-Type": "application/json", "Signature": sig},
    )


def test_payments_503_when_token_missing() -> None:
    reset_backend()
    engine.reset()
    with mock.patch.dict(os.environ, {"PAYCHANGU_SECRET_KEY": ""}, clear=False):
        client = TestClient(create_app())
        account = _account(client)
        token, wallet_id = account["token"], account["wallet"]["id"]
        assert _deposit(client, token, wallet_id).status_code == 503
        assert _withdraw(client, token, wallet_id).status_code == 503


# --- Auth + ownership gating (F-01 / F-02 / F-03) --------------------------


def test_guest_cannot_create_deposit_or_withdrawal(client: TestClient) -> None:
    account = _account(client)
    wallet_id = account["wallet"]["id"]
    assert _deposit(client, "", wallet_id).status_code == 401
    assert _withdraw(client, "", wallet_id).status_code == 401


def test_other_users_wallet_rejected(client: TestClient) -> None:
    alice = _account(client, "alice@ketsa.io")
    bob = _account(client, "bob@ketsa.io")
    assert _deposit(client, bob["token"], alice["wallet"]["id"]).status_code == 403
    assert _withdraw(client, bob["token"], alice["wallet"]["id"]).status_code == 403

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
    assert client.get(f"/api/wallet/{wid}").status_code == 401
    assert client.get(f"/api/wallet/{wid}", headers=_headers(bob["token"])).status_code == 403
    assert client.get(f"/api/wallet/{wid}", headers=_headers(alice["token"])).status_code == 200
    guest = client.post("/api/wallet", json={"name": "Guest"}).json()
    assert client.get(f"/api/wallet/{guest['id']}").status_code == 200
    assert client.get("/api/payments", headers=_headers(alice["token"])).status_code == 200
    assert client.get("/api/payments").status_code == 401


def test_unclaimed_guest_wallet_cannot_touch_payments(client: TestClient) -> None:
    alice = _account(client, "alice@ketsa.io")
    guest = client.post("/api/wallet", json={"name": "Guest"}).json()
    assert _deposit(client, alice["token"], guest["id"]).status_code == 403
    assert _withdraw(client, alice["token"], guest["id"]).status_code == 403


# --- Deposits ---------------------------------------------------------------


def test_deposit_uses_documented_contract_and_idempotent_credit(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    assert _balance(client, token, wallet_id) == 0.0

    res = _deposit(client, token, wallet_id, amount=500.0, number="099 9123 456")
    assert res.status_code == 200
    rec = res.json()
    assert rec["kind"] == "deposit"
    assert rec["status"] == "pending"
    assert rec["amount"] == 500.0
    assert rec["number"] == "+265999123456"  # E.164 for PayChangu
    assert rec["correspondent"] == "AIRTEL"  # legacy _MWI alias normalised
    # The payment id doubles as the provider charge_id (idempotency key).
    assert rec["provider_charge_id"] == rec["id"]
    assert rec["wande_id"] == rec["id"]

    method, path, sent = bank.calls[0]
    assert (method, path) == ("POST", "/mobile-money/payments/initialize")
    assert sent["charge_id"] == rec["id"]
    assert sent["mobile_money_operator_ref_id"] == AIRTEL_REF
    assert sent["mobile"] == "999123456"

    # Still pending -> no credit.
    client.get(f"/api/payments/{rec['id']}", headers=_headers(token))
    assert _balance(client, token, wallet_id) == 0.0

    # Provider completes -> credit exactly once, even if polled again.
    bank.deposit_status = "success"
    body = client.get(f"/api/payments/{rec['id']}", headers=_headers(token)).json()
    assert body["status"] == "completed"
    assert body["credited"] is True
    assert _balance(client, token, wallet_id) == 500.0
    body = client.get(f"/api/payments/{rec['id']}", headers=_headers(token)).json()
    assert body["credited"] is True
    assert _balance(client, token, wallet_id) == 500.0


def test_deposit_failed_is_recorded_but_not_credited(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    rec = _deposit(client, token, wallet_id, amount=200.0).json()
    bank.deposit_status = "failed"
    body = client.get(f"/api/payments/{rec['id']}", headers=_headers(token)).json()
    assert body["status"] == "failed"
    assert body["credited"] is False
    assert _balance(client, token, wallet_id) == 0.0


def test_deposit_rejected_by_provider_is_failed_not_credited(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    bank.deposit_init_error = 400

    res = _deposit(client, token, wallet_id, amount=200.0)
    assert res.status_code == 502
    assert _balance(client, token, wallet_id) == 0.0
    items = client.get("/api/payments", headers=_headers(token)).json()
    assert [p["status"] for p in items] == ["failed"]
    assert items[0]["credited"] is False


def test_deposit_validation(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    assert _deposit(client, token, wallet_id, amount=50.0).status_code == 400  # below minimum
    assert _deposit(client, token, wallet_id, number="123").status_code == 400  # invalid number
    assert _deposit(client, token, wallet_id, correspondent="MTN_MWI").status_code == 400
    assert _deposit(client, token, wallet_id, amount=100.001).status_code == 400  # 3+ decimals
    assert bank.calls == []


def test_non_finite_amounts_rejected(client: TestClient) -> None:
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
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
    assert bank.calls == []


# --- Withdrawals (admin approval required) ----------------------------------


def test_withdrawal_flow_uses_payout_endpoints(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    _fund(client, token, wallet_id, amount=1000.0)

    res = _withdraw(client, token, wallet_id, amount=300.0, number="0999123456", correspondent="TNM_MWI")
    assert res.status_code == 200
    rec = res.json()
    assert rec["kind"] == "withdraw"
    assert rec["status"] == "pending_approval"
    assert rec["provider_charge_id"] == rec["id"]
    assert rec["correspondent"] == "TNM"
    assert _balance(client, token, wallet_id) == 700.0
    assert bank.calls == []

    appr = _approve_withdrawal(client, rec["id"])
    assert appr.status_code == 200
    rec = appr.json()
    assert rec["status"] == "pending"

    method, path, sent = bank.calls[0]
    assert (method, path) == ("POST", "/mobile-money/payouts/initialize")
    assert sent["charge_id"] == rec["id"]
    assert sent["mobile_money_operator_ref_id"] == TNM_REF

    bank.withdrawal_status = "success"
    body = client.get(f"/api/payments/{rec['id']}", headers=_headers(token)).json()
    assert body["status"] == "completed"
    assert body["rolled_back"] is False
    assert _balance(client, token, wallet_id) == 700.0
    # Payout status must use the /details endpoint, not /verify.
    assert bank.calls[-1][1].endswith("details")


def test_withdrawal_failed_refunds_balance(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    _fund(client, token, wallet_id, amount=1000.0)

    rec = _withdraw(client, token, wallet_id, amount=200.0).json()
    assert rec["status"] == "pending_approval"
    rec = _approve_withdrawal(client, rec["id"]).json()
    bank.withdrawal_status = "failed"
    body = client.get(f"/api/payments/{rec['id']}", headers=_headers(token)).json()
    assert body["status"] == "failed"
    assert body["rolled_back"] is True
    assert _balance(client, token, wallet_id) == 1000.0
    body = client.get(f"/api/payments/{rec['id']}", headers=_headers(token)).json()
    assert body["rolled_back"] is True
    assert _balance(client, token, wallet_id) == 1000.0


def test_withdrawal_failed_at_init_refunds_immediately(client: TestClient) -> None:
    """A definitive failure on the payout *initialize* response refunds now."""
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    _fund(client, token, wallet_id, amount=1000.0)

    rec = _withdraw(client, token, wallet_id, amount=200.0).json()
    bank.withdrawal_init_status = "failed"
    body = _approve_withdrawal(client, rec["id"]).json()
    assert body["status"] == "failed"
    assert body["rolled_back"] is True
    assert _balance(client, token, wallet_id) == 1000.0


def test_withdrawal_rejected_by_provider_refunds_and_returns_failed_state(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    _fund(client, token, wallet_id, amount=1000.0)

    rec = _withdraw(client, token, wallet_id, amount=200.0).json()
    bank.withdrawal_init_error = 400
    res = _approve_withdrawal(client, rec["id"])
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "failed"
    assert body["rolled_back"] is True
    assert _balance(client, token, wallet_id) == 1000.0
    items = client.get("/api/payments", headers=_headers(token)).json()
    failed = [p for p in items if p["kind"] == "withdraw" and p["status"] == "failed"]
    assert failed and failed[0]["rolled_back"] is True


def test_admin_can_reject_withdrawal(client: TestClient) -> None:
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    _fund(client, token, wallet_id, amount=1000.0)

    rec = _withdraw(client, token, wallet_id, amount=200.0).json()
    assert rec["status"] == "pending_approval"
    assert _balance(client, token, wallet_id) == 800.0

    res = _reject_withdrawal(client, rec["id"], "KYC required")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "rejected"
    assert body["rolled_back"] is True
    assert "KYC required" in (body.get("message") or "")
    assert _balance(client, token, wallet_id) == 1000.0


def test_withdrawal_insufficient_balance(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    assert _withdraw(client, token, wallet_id, amount=300.0).status_code == 400
    assert bank.calls == []


def test_min_withdrawal_below_threshold(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    _fund(client, token, wallet_id, amount=1000.0)
    assert _withdraw(client, token, wallet_id, amount=50.0).status_code == 400
    assert bank.calls == []


# --- Caps (F-05) ------------------------------------------------------------


def test_per_transaction_caps() -> None:
    client2 = _fresh(env={"KETSA_MAX_DEPOSIT_MWK": "500", "KETSA_MAX_WITHDRAWAL_MWK": "400"})
    try:
        bank = _bank(client2)
        account = _account(client2)
        token, wallet_id = account["token"], account["wallet"]["id"]
        assert _deposit(client2, token, wallet_id, amount=600.0).status_code == 400
        _fund(client2, token, wallet_id, amount=400.0)
        assert _withdraw(client2, token, wallet_id, amount=500.0).status_code == 400
        rec = _withdraw(client2, token, wallet_id, amount=300.0).json()
        assert rec["status"] == "pending_approval"
        assert len(bank.calls) == 0
        _approve_withdrawal(client2, rec["id"])
        assert len(bank.calls) == 1
    finally:
        _stop(client2)


def test_daily_withdrawal_limit_ignores_failed_withdrawals() -> None:
    client2 = _fresh(env={"KETSA_DAILY_WITHDRAWAL_LIMIT_MWK": "400"})
    try:
        bank = _bank(client2)
        account = _account(client2)
        token, wallet_id = account["token"], account["wallet"]["id"]
        _fund(client2, token, wallet_id, amount=1000.0)

        first = _withdraw(client2, token, wallet_id, amount=250.0).json()
        # pending_approval still consumes the daily cap
        assert _withdraw(client2, token, wallet_id, amount=200.0).status_code == 400
        # Reject/refund the first withdrawal; it must not keep consuming the cap.
        _reject_withdrawal(client2, first["id"])
        assert _withdraw(client2, token, wallet_id, amount=250.0).status_code == 200
    finally:
        _stop(client2)


# --- Ledger scoping (F-02) --------------------------------------------------


def test_payment_history_lists_own_records(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    _fund(client, token, wallet_id, amount=1000.0)
    d = _deposit(client, token, wallet_id, amount=250.0).json()
    c = _withdraw(client, token, wallet_id, amount=120.0).json()
    bank.deposit_status = "success"
    client.get(f"/api/payments/{d['id']}", headers=_headers(token))

    items = client.get(f"/api/payments?wallet_id={wallet_id}", headers=_headers(token)).json()
    ids = [p["id"] for p in items]
    assert d["id"] in ids and c["id"] in ids
    by_id = {p["id"]: p for p in items}
    assert by_id[c["id"]]["status"] == "pending_approval"
    assert store.get_payment(d["id"])["credited"] is True

    bob = _account(client, "bob@ketsa.io")
    bob_items = client.get("/api/payments", headers=_headers(bob["token"])).json()
    assert all(p["wallet_id"] == bob["wallet"]["id"] for p in bob_items)


# --- Webhooks ---------------------------------------------------------------


def test_webhook_credits_deposit_once_and_replay_is_idempotent(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    rec = _deposit(client, token, wallet_id, amount=500.0).json()

    bank.deposit_status = "success"
    payload = {
        "event_type": "api.charge.payment",
        "charge_id": rec["id"],
        "status": "success",
        "amount": 500,
        "currency": "MWK",
    }
    assert _webhook(client, payload).status_code == 200
    assert _balance(client, token, wallet_id) == 500.0
    assert store.get_payment(rec["id"])["status"] == "completed"
    assert store.get_payment(rec["id"])["credited"] is True

    # Replaying the same event must not double-credit.
    assert _webhook(client, payload).status_code == 200
    assert _balance(client, token, wallet_id) == 500.0


def test_webhook_rejects_bad_signature(client: TestClient) -> None:
    bank = _bank(client)
    account = _account(client)
    token, wallet_id = account["token"], account["wallet"]["id"]
    rec = _deposit(client, token, wallet_id, amount=500.0).json()

    bank.deposit_status = "success"
    res = _webhook(
        client,
        {"charge_id": rec["id"], "status": "success"},
        signature="0" * 64,
    )
    assert res.status_code == 401
    assert _balance(client, token, wallet_id) == 0.0
    assert store.get_payment(rec["id"])["status"] == "pending"


def test_webhook_ignores_unknown_charge(client: TestClient) -> None:
    assert _webhook(client, {"charge_id": "does-not-exist", "status": "success"}).status_code == 200


def test_verify_webhook_rejects_non_ascii_signature() -> None:
    # compare_digest() raises TypeError on non-ASCII str; that must be a clean
    # authentication failure, never an unhandled 500.
    assert paychangu.verify_webhook(b"{}", "\u00e9" * 64) is False


def test_webhook_rejects_oversized_body(client: TestClient) -> None:
    # An unauthenticated caller must not force a large allocation before HMAC.
    res = _webhook(client, {"charge_id": "x", "pad": "a" * 100_000})
    assert res.status_code == 413


# --- Provider status parsing ------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"status": "success"}, "pending"),  # request accepted, not settled
        ({"status": "success", "data": None}, "pending"),
        ({"status": "success", "data": {"status": "pending"}}, "pending"),
        ({"status": "successful", "data": {"status": "success"}}, "completed"),
        ({"status": "success", "data": {"status": "failed"}}, "failed"),
        ({"status": "failed", "data": None}, "failed"),
    ],
)
def test_charge_status_only_completes_on_transaction_status(payload, expected) -> None:
    # A bare top-level `success` means "accepted", never "settled"; treating it
    # as completed would credit a deposit before the money actually moved.
    assert paychangu.charge_status(payload)[0] == expected


# --- Write-path rate limiter (F-07) ----------------------------------------


def test_write_endpoints_are_strictly_rate_limited() -> None:
    client2 = _fresh(env={"KETSA_WRITE_RATE_LIMIT_PER_MIN": "2"})
    try:
        assert client2.post("/api/wallet", json={"name": "A"}).status_code == 200
        assert client2.post("/api/wallet", json={"name": "B"}).status_code == 200
        assert client2.post("/api/wallet", json={"name": "C"}).status_code == 429
        assert client2.get("/api/markets").status_code == 200
    finally:
        _stop(client2)
