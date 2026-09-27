"""Tests for the withdrawable-balance rule (real money vs. play money).

`wallet.balance` is what can be traded with. `wallet.withdrawable` is the
money that actually arrived through wandePay, and it is the only pool a
withdrawal may draw on. The distinction matters because the free 1,000 MWK
seed that pre-change wallets were minted with is still sitting in their
persisted `balance` — without this rule that house money could be paid out
to a mobile-money number.
"""

from fastapi.testclient import TestClient

import pytest

from app.engine import engine
from app.main import create_app
from app.storage import reset_backend
from conftest import make_client, register_user


def _account(client: TestClient, identifier: str = "alice@ketsa.io") -> dict:
    return register_user(client, identifier=identifier)


def _fund_directly(client: TestClient, token: str, wallet_id: str, amount: float) -> None:
    """Credit real funds without standing up the wandePay mock.

    `credit_balance` is exactly what a completed deposit calls, so this
    exercises the same accounting path the payment route uses.
    """
    engine.credit_balance(wallet_id, amount)
    client.get(f"/api/wallet/{wallet_id}", headers={"Authorization": f"Bearer {token}"})


def test_new_wallet_has_no_withdrawable_funds(client: TestClient) -> None:
    account = _account(client)
    w = client.get(
        f"/api/wallet/{account['wallet']['id']}",
        headers={"Authorization": f"Bearer {account['token']}"},
    ).json()
    assert w["balance"] == 0.0
    assert w["withdrawable"] == 0.0


def test_deposit_raises_both_balance_and_withdrawable(client: TestClient) -> None:
    account = _account(client)
    token, wid = account["token"], account["wallet"]["id"]
    _fund_directly(client, token, wid, 500.0)
    w = client.get(f"/api/wallet/{wid}", headers={"Authorization": f"Bearer {token}"}).json()
    assert w["balance"] == 500.0
    assert w["withdrawable"] == 500.0


def test_legacy_seeded_balance_is_not_withdrawable(client: TestClient) -> None:
    """The regression this rule exists for.

    A wallet persisted before the zero-balance change still carries the old
    free seed in `balance`. It must remain spendable on markets but must NOT
    be cashable, otherwise the house pays out money it never received.
    """
    account = _account(client)
    token, wid = account["token"], account["wallet"]["id"]
    # Simulate a legacy persisted wallet: balance present, no `deposited` key.
    wallet = engine._wallets[wid]
    wallet["balance"] = 1000.0
    wallet.pop("deposited", None)

    w = client.get(f"/api/wallet/{wid}", headers={"Authorization": f"Bearer {token}"}).json()
    assert w["balance"] == 1000.0
    assert w["withdrawable"] == 0.0

    # And the engine refuses to pay it out.
    with pytest.raises(ValueError, match="deposited"):
        engine.debit_balance(wid, 100.0)


def test_withdrawal_debits_withdrawable_pool(client: TestClient) -> None:
    account = _account(client)
    token, wid = account["token"], account["wallet"]["id"]
    _fund_directly(client, token, wid, 1000.0)
    engine.debit_balance(wid, 300.0)
    w = client.get(f"/api/wallet/{wid}", headers={"Authorization": f"Bearer {token}"}).json()
    assert w["balance"] == 700.0
    assert w["withdrawable"] == 700.0


def test_withdrawal_cannot_exceed_deposited(client: TestClient) -> None:
    account = _account(client)
    token, wid = account["token"], account["wallet"]["id"]
    # Balance inflated by trading winnings, but no real money deposited.
    engine._wallets[wid]["balance"] = 5000.0
    with pytest.raises(ValueError, match="deposited"):
        engine.debit_balance(wid, 100.0)
    # Nothing was debited.
    w = client.get(f"/api/wallet/{wid}", headers={"Authorization": f"Bearer {token}"}).json()
    assert w["balance"] == 5000.0
    assert w["withdrawable"] == 0.0


def test_withdrawal_limited_to_the_smaller_of_the_two_pools(client: TestClient) -> None:
    account = _account(client)
    token, wid = account["token"], account["wallet"]["id"]
    _fund_directly(client, token, wid, 1000.0)
    # Trade some of it away: balance drops, withdrawable does not.
    engine._wallets[wid]["balance"] = 200.0
    with pytest.raises(ValueError, match="Insufficient balance"):
        engine.debit_balance(wid, 500.0)
    w = client.get(f"/api/wallet/{wid}", headers={"Authorization": f"Bearer {token}"}).json()
    assert w["withdrawable"] == 1000.0


def test_wallet_view_defaults_missing_deposited_to_zero() -> None:
    """A wallet dict from an older schema has no `deposited` key at all."""
    reset_backend()
    engine.reset()
    client = make_client()
    account = register_user(client, identifier="legacy@ketsa.io")
    wid = account["wallet"]["id"]
    stored = engine._wallets[wid]
    del stored["deposited"]
    view = engine.wallet_view(wid)
    assert view is not None
    assert view["withdrawable"] == 0.0


def test_api_rejects_withdrawal_above_withdrawable() -> None:
    """End-to-end: the payments route surfaces the rule as a 400."""
    import os
    from unittest import mock

    from app import payments as wande

    reset_backend()
    engine.reset()
    m_wande = mock.Mock()
    m_wande.create_withdrawal.return_value = {"data": {"payoutId": "p1"}}
    m_wande.create_deposit.return_value = {"data": {"orderId": "d1"}}
    with mock.patch.object(wande, "_http_post", m_wande), mock.patch.dict(
        os.environ, {"KETSA_WANDE_TOKEN": "t"}, clear=False
    ):
        client = TestClient(create_app())
        account = register_user(client, identifier="bob@ketsa.io")
        token, wid = account["token"], account["wallet"]["id"]
        # Play balance only — the deposit-free path must not pay out.
        engine._wallets[wid]["balance"] = 900.0
        res = client.post(
            "/api/payments/withdrawals",
            json={
                "wallet_id": wid,
                "amount": 500.0,
                "number": "0999123456",
                "correspondent": "TNM_MWI",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 400
        assert "deposited" in res.json()["detail"].lower()
        # wandePay was never called.
        assert m_wande.create_withdrawal.call_count == 0
