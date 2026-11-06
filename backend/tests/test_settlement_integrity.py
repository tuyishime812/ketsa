"""Settlement integrity: idempotency, crash recovery and input hardening.

The resolve path moves real money. Before these tests, settlement was a
read-modify-write loop that persisted each wallet and only marked the market
resolved at the very end. A crash (or a retried request) between wallets could
therefore pay the same wallet twice on the next run (CWE-362 / CWE-667).

The contract pinned here:

* a market that is mid-settlement refuses new orders;
* every payout carries a durable per-wallet marker written with the credit;
* re-running a partial settlement pays only the wallets still missing a marker;
* re-running a completed settlement is a no-op, never a second payout.
"""

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.engine import engine

FUNDS = 1000.0


def _wallet(client: TestClient, name: str) -> dict:
    w = client.post("/api/wallet", json={"name": name}).json()
    engine.credit_balance(w["id"], FUNDS)
    return client.get(f"/api/wallet/{w['id']}").json()


def _buy(client: TestClient, wallet_id: str, market_id: str, amount: float) -> dict:
    res = client.post(
        "/api/trade",
        json={
            "wallet_id": wallet_id,
            "market_id": market_id,
            "outcome": "yes",
            "side": "buy",
            "amount": amount,
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def _balance(client: TestClient, wallet_id: str) -> float:
    return client.get(f"/api/wallet/{wallet_id}").json()["balance"]


def _admin_token(client: TestClient) -> str:
    res = client.post("/api/admin/login", json={"password": "ketsa-admin"})
    assert res.status_code == 200
    return res.json()["token"]


# --- Idempotent replay ------------------------------------------------------


def test_replaying_a_completed_resolution_pays_nothing(client: TestClient) -> None:
    w = _wallet(client, "Winner")
    _buy(client, w["id"], "nova-finals", 40.0)

    first = engine.resolve_market("nova-finals", "yes")
    assert first["wallets_settled"] == 1
    paid = _balance(client, w["id"])

    replay = engine.resolve_market("nova-finals", "yes")
    assert replay["already_resolved"] is True
    assert replay["wallets_settled"] == 0
    assert replay["total_payout"] == 0.0
    assert _balance(client, w["id"]) == paid


def test_resolving_to_a_different_outcome_is_still_rejected(
    client: TestClient,
) -> None:
    _wallet(client, "Trader")
    engine.resolve_market("nova-finals", "yes")
    with pytest.raises(ValueError, match="already resolved"):
        engine.resolve_market("nova-finals", "no")


def test_http_replay_is_a_successful_noop(client: TestClient) -> None:
    w = _wallet(client, "Winner")
    _buy(client, w["id"], "nova-finals", 30.0)
    token = _admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    first = client.post(
        "/api/admin/markets/nova-finals/resolve",
        json={"outcome": "yes"},
        headers=headers,
    )
    assert first.status_code == 200
    paid = _balance(client, w["id"])

    again = client.post(
        "/api/admin/markets/nova-finals/resolve",
        json={"outcome": "yes"},
        headers=headers,
    )
    assert again.status_code == 200
    assert "already resolved" in again.json()["detail"].lower()
    assert _balance(client, w["id"]) == paid


# --- Crash recovery ---------------------------------------------------------


def test_interrupted_settlement_resumes_without_double_paying(
    client: TestClient, monkeypatch
) -> None:
    w1 = _wallet(client, "First")
    w2 = _wallet(client, "Second")
    _buy(client, w1["id"], "nova-finals", 40.0)
    _buy(client, w2["id"], "nova-finals", 40.0)

    original = engine._settle_wallet
    calls = {"n": 0}

    def flaky(wallet, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            # Simulate the process dying / the provider timing out mid-loop,
            # after the first wallet has been credited and persisted.
            raise RuntimeError("simulated crash during settlement")
        return original(wallet, *args, **kwargs)

    monkeypatch.setattr(engine, "_settle_wallet", flaky)
    with pytest.raises(RuntimeError, match="simulated crash"):
        engine.resolve_market("nova-finals", "yes")
    monkeypatch.setattr(engine, "_settle_wallet", original)

    # Exactly one wallet was paid, and the market says a settlement is running.
    after_crash = {w["id"]: _balance(client, w["id"]) for w in (w1, w2)}
    paid_wallets = [wid for wid, bal in after_crash.items() if bal > FUNDS - 40.0]
    assert len(paid_wallets) == 1

    market = client.get("/api/markets/nova-finals").json()
    assert market["status"] == "open"  # not falsely marked resolved
    assert market["settlement"]["status"] == "in_progress"

    # Trading must already be closed: the answer is decided even though the
    # payout is unfinished.
    late = client.post(
        "/api/trade",
        json={
            "wallet_id": w1["id"],
            "market_id": "nova-finals",
            "outcome": "yes",
            "side": "buy",
            "amount": 5.0,
        },
    )
    assert late.status_code == 400
    assert "being resolved" in late.json()["detail"].lower()

    # Resume: pays only the wallet still missing a marker.
    resume = engine.resolve_market("nova-finals", "yes")
    assert resume["wallets_settled"] == 1
    assert resume["already_settled"] == 1

    final = {w["id"]: _balance(client, w["id"]) for w in (w1, w2)}
    for wallet_id in after_crash:
        # The wallet paid before the crash must not have gained anything more.
        if wallet_id in paid_wallets:
            assert final[wallet_id] == after_crash[wallet_id]
        else:
            assert final[wallet_id] > after_crash[wallet_id]

    market = client.get("/api/markets/nova-finals").json()
    assert market["status"] == "resolved"
    assert market["resolved_outcome"] == "yes"
    assert market["settlement"]["status"] == "complete"
    assert market["settlement"]["already_settled"] == 1

    # And a further replay is inert.
    third = engine.resolve_market("nova-finals", "yes")
    assert third["already_resolved"] is True
    assert {w["id"]: _balance(client, w["id"]) for w in (w1, w2)} == final


def test_marker_is_persisted_with_the_payout(client: TestClient) -> None:
    w = _wallet(client, "Winner")
    _buy(client, w["id"], "nova-finals", 40.0)
    engine.resolve_market("nova-finals", "yes")

    from app import store

    persisted = store.get_wallet(w["id"])
    assert persisted is not None
    marker = persisted["settlements"]["nova-finals"]
    assert marker["outcome"] == "yes"
    assert marker["payout"] > 0


def test_failed_wallet_write_rolls_back_instead_of_losing_the_payout(
    client: TestClient, monkeypatch
) -> None:
    """A storage error mid-settlement must not erase the position it popped.

    ``_settle_wallet`` removes the position from the live wallet, then the
    resolve loop persists it. If the durable write fails, the marker and the
    credit are both missing while the position is already gone — a retry would
    skip the wallet and the payout would vanish. The loop must restore the
    pre-settlement state so the retry pays normally.
    """
    from app import store

    w = _wallet(client, "Winner")
    _buy(client, w["id"], "nova-finals", 40.0)
    durable_before = store.get_wallet(w["id"])
    assert durable_before["positions"]["nova-finals"]

    original = engine._persist
    calls = {"n": 0}

    def flaky(wallet_id: str) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated storage timeout")
        return original(wallet_id)

    monkeypatch.setattr(engine, "_persist", flaky)
    with pytest.raises(RuntimeError, match="storage timeout"):
        engine.resolve_market("nova-finals", "yes")
    monkeypatch.setattr(engine, "_persist", original)

    live = engine._wallets[w["id"]]
    assert live["positions"]["nova-finals"] is not None
    assert engine._settlement_marker(live, "nova-finals") is None
    assert live["balance"] == durable_before["balance"]

    # The market is still flagged in progress, so a retry resumes it.
    market = client.get("/api/markets/nova-finals").json()
    assert market["settlement"]["status"] == "in_progress"

    resume = engine.resolve_market("nova-finals", "yes")
    assert resume["wallets_settled"] == 1
    assert resume["already_settled"] == 0

    durable = store.get_wallet(w["id"])
    marker = (durable.get("settlements") or {}).get("nova-finals")
    assert marker is not None and marker.get("payout", 0) > 0
    assert _balance(client, w["id"]) > durable_before["balance"]


def test_resume_with_a_different_outcome_is_rejected(
    client: TestClient, monkeypatch
) -> None:
    w = _wallet(client, "Winner")
    _buy(client, w["id"], "nova-finals", 40.0)

    def crash(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(engine, "_settle_wallet", crash)
    with pytest.raises(RuntimeError):
        engine.resolve_market("nova-finals", "yes")
    monkeypatch.undo()

    with pytest.raises(ValueError, match="original outcome"):
        engine.resolve_market("nova-finals", "no")


# --- Admin delete safety ---------------------------------------------------


def _delete_market(client: TestClient, market_id: str):
    token = _admin_token(client)
    return client.delete(
        f"/api/admin/markets/{market_id}",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_deleting_a_market_with_open_positions_is_refused(
    client: TestClient,
) -> None:
    """Deleting the row would strand holders: positions only settle against it."""
    w = _wallet(client, "Holder")
    _buy(client, w["id"], "nova-finals", 25.0)

    res = _delete_market(client, "nova-finals")
    assert res.status_code == 409
    assert "resolve it before deleting" in res.json()["detail"]

    # Nothing was destroyed, and the position is still there.
    market = client.get("/api/markets/nova-finals").json()
    assert market["status"] == "open"
    from app import store

    assert (store.get_wallet(w["id"])["positions"] or {}).get("nova-finals")


def test_deleting_during_settlement_is_refused(client: TestClient, monkeypatch) -> None:
    w = _wallet(client, "Holder")
    _buy(client, w["id"], "nova-finals", 25.0)

    def crash(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(engine, "_settle_wallet", crash)
    with pytest.raises(RuntimeError):
        engine.resolve_market("nova-finals", "yes")
    monkeypatch.undo()

    res = _delete_market(client, "nova-finals")
    assert res.status_code == 409
    assert "settlement is in progress" in res.json()["detail"].lower()


def test_a_settled_market_can_be_deleted(client: TestClient) -> None:
    w = _wallet(client, "Holder")
    _buy(client, w["id"], "nova-finals", 25.0)
    engine.resolve_market("nova-finals", "yes")

    assert _delete_market(client, "nova-finals").status_code == 200
    assert client.get("/api/markets/nova-finals").status_code == 404


def test_an_unowned_market_can_be_deleted(client: TestClient) -> None:
    assert _delete_market(client, "nova-finals").status_code == 200
    assert client.get("/api/markets/nova-finals").status_code == 404


# --- Admin mass-assignment -------------------------------------------------


def test_admin_cannot_write_settlement_fields(client: TestClient) -> None:
    token = _admin_token(client)
    markets = client.get("/api/markets").json()["all"]
    market = next(m for m in markets if m["id"] == "nova-finals")

    # Only the fields the Markets editor owns, plus the forbidden one. Engine
    # fields like `last_price` are omitted so this test proves the *new*
    # `settlement` guard specifically (any settlement field is rejected).
    payload = {
        "id": market["id"],
        "cat": market["cat"],
        "tag": market["tag"],
        "q": market["q"],
        "yes": market["yes"],
        "no": market["no"],
        "meta": market["meta"],
        "trend": market["trend"],
        "pts": market["pts"],
        "settlement": {"status": "complete", "outcome": "yes"},
    }
    res = client.put(
        "/api/admin/markets",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 400
    assert "Settlement fields" in res.json()["detail"]


# --- Readiness -------------------------------------------------------------


def test_ready_reports_storage_ok(client: TestClient) -> None:
    res = client.get("/api/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "storage": "ok"}
    assert client.get("/ready").status_code == 200


def test_ready_fails_closed_when_storage_is_unreachable(
    client: TestClient, monkeypatch
) -> None:
    def broken() -> None:
        raise RuntimeError("could not connect to db-internal-host:5432")

    monkeypatch.setattr(app_main, "ping_storage", broken)
    res = client.get("/api/ready")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "unavailable"
    # No internals may leak into the probe response (CWE-209).
    assert "db-internal-host" not in res.text
    assert "5432" not in res.text


def test_health_stays_live_even_if_storage_is_down(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        app_main, "ping_storage", lambda: (_ for _ in ()).throw(RuntimeError())
    )
    assert client.get("/api/health").json() == {"status": "ok"}


# --- Input bounds (PBKDF2 CPU-exhaustion guard) ----------------------------


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/auth/register", {"name": "A", "identifier": "a@example.com"}),
        ("/api/auth/login", {"identifier": "a@example.com"}),
    ],
)
def test_oversized_password_is_rejected(client: TestClient, path: str, body: dict) -> None:
    body = {**body, "password": "x" * 5000}
    res = client.post(path, json=body)
    assert res.status_code == 422
