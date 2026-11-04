"""Tests for the append-only audit log (app/audit.py).

The audit log is the system of record for privileged and money-moving actions,
so these tests pin the important properties:

* the expected actions are recorded, with actor + IP + target;
* failures (bad and locked-out logins) are recorded too;
* **no secret ever appears in a row** (passwords, OTP codes, tokens);
* the log survives a content reset (it is not operational content);
* reads are newest-first and filterable.
"""

from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app import audit
from app.main import create_app
from app.storage import reset_backend


@pytest.fixture()
def admin_client() -> TestClient:
    """Admin panel client with a known password and no rate limiting."""
    reset_backend()
    from app.engine import engine

    engine.reset()
    import os

    with mock.patch.dict(
        os.environ,
        {"KETSA_RATE_LIMIT_PER_MIN": "0", "KETSA_ADMIN_PASSWORD": "pw123"},
        clear=False,
    ):
        yield TestClient(create_app())


def _auth(client: TestClient, password: str = "pw123") -> dict[str, str]:
    r = client.post("/api/admin/login", json={"password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _actions() -> list[str]:
    return [r["action"] for r in audit.list_recent(limit=200)]


def test_successful_login_is_recorded(admin_client: TestClient) -> None:
    _auth(admin_client)
    rows = audit.list_recent(action=audit.Actions.ADMIN_LOGIN_OK)
    assert len(rows) == 1
    row = rows[0]
    assert row["actor_type"] == "admin"
    assert row["actor_id"]  # digest prefix, never the token
    assert audit.Actions.ADMIN_LOGIN_OK in _actions()


def test_failed_login_is_recorded_without_secret(admin_client: TestClient) -> None:
    assert admin_client.post("/api/admin/login", json={"password": "wrong"}).status_code == 401
    rows = audit.list_recent(action=audit.Actions.ADMIN_LOGIN_FAILED)
    assert len(rows) == 1
    # The attempted password must never appear anywhere in the row.
    assert "wrong" not in repr(rows[0])


def test_lockout_is_recorded(admin_client: TestClient) -> None:
    # Default admin_max_failures is 10; trip it.
    for _ in range(10):
        admin_client.post("/api/admin/login", json={"password": "wrong"})
    res = admin_client.post("/api/admin/login", json={"password": "pw123"})
    assert res.status_code == 429
    assert audit.Actions.ADMIN_LOGIN_LOCKED in _actions()


def test_logout_is_recorded(admin_client: TestClient) -> None:
    headers = _auth(admin_client)
    assert admin_client.post("/api/admin/logout", headers=headers).status_code == 200
    assert audit.Actions.ADMIN_LOGOUT in _actions()


def test_password_change_is_recorded_without_the_password(admin_client: TestClient) -> None:
    headers = _auth(admin_client)
    res = admin_client.post(
        "/api/admin/password",
        json={"current": "pw123", "new": "brandnewpass1"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    rows = audit.list_recent(action=audit.Actions.ADMIN_PASSWORD_CHANGED)
    assert len(rows) == 1
    assert "brandnewpass1" not in repr(rows)


def test_market_resolution_is_recorded_with_payout(admin_client: TestClient) -> None:
    headers = _auth(admin_client)
    # Seed a resolvable market via the admin create endpoint, then resolve it.
    market = {
        "id": "audit-res",
        "cat": "tech",
        "tag": "test",
        "q": "Will this resolve?",
        "yes": 50,
        "no": 50,
        "meta": ["$0 vol", "0 traders"],
        "trend": "up",
        "pts": [50, 50],
        "description": "",
        "end_date": None,
        "created": "2026-01-01T00:00:00Z",
        "volume": 0,
        "liquidity": 500,
        "status": "open",
    }
    assert admin_client.post("/api/admin/markets", json=market, headers=headers).status_code == 200
    res = admin_client.post(
        "/api/admin/markets/audit-res/resolve", json={"outcome": "yes"}, headers=headers
    )
    assert res.status_code == 200, res.text
    rows = audit.list_recent(action=audit.Actions.MARKET_RESOLVED)
    assert len(rows) == 1
    assert rows[0]["target_type"] == "market"
    assert rows[0]["target_id"] == "audit-res"
    assert rows[0]["metadata"]["outcome"] == "yes"
    assert "total_payout" in rows[0]["metadata"]


def test_config_change_is_recorded(admin_client: TestClient) -> None:
    headers = _auth(admin_client)
    res = admin_client.put(
        "/api/admin/config/payments",
        json={"deposits_enabled": False},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    rows = audit.list_recent(action=audit.Actions.ADMIN_CONFIG_CHANGED)
    assert len(rows) == 1
    assert rows[0]["target_id"] == "payments"


def test_user_password_reset_is_recorded(admin_client: TestClient) -> None:
    # Register a user through the auth flow, then reset via admin.
    from conftest import register_user

    register_user(admin_client, identifier="audit-user@ketsa.io", password="password123")
    headers = _auth(admin_client)
    res = admin_client.post(
        "/api/admin/users/reset-password",
        json={"identifier": "audit-user@ketsa.io", "new_password": "newpassword123"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    rows = audit.list_recent(action=audit.Actions.USER_PASSWORD_RESET)
    assert len(rows) == 1
    assert "newpassword123" not in repr(rows)
    assert rows[0]["metadata"]["identifier"] == "audit-user@ketsa.io"


def test_audit_survives_content_reset(admin_client: TestClient) -> None:
    headers = _auth(admin_client)
    before = audit.count()
    assert before >= 1
    assert admin_client.post("/api/admin/reset", headers=headers).status_code == 200
    # A content reset must never erase the record of privileged actions.
    assert audit.count() >= before
    assert audit.Actions.ADMIN_LOGIN_OK in _actions()


def test_reads_are_newest_first_and_filterable(admin_client: TestClient) -> None:
    _auth(admin_client)
    admin_client.post("/api/admin/login", json={"password": "wrong"})
    recent = audit.list_recent(limit=50)
    assert recent  # newest-first
    assert recent[0]["ts"] >= recent[-1]["ts"]
    only_failed = audit.list_recent(action=audit.Actions.ADMIN_LOGIN_FAILED)
    assert only_failed and all(
        r["action"] == audit.Actions.ADMIN_LOGIN_FAILED for r in only_failed
    )


def test_read_endpoint_requires_admin_and_returns_rows(admin_client: TestClient) -> None:
    # No token -> 401. The audit log is privileged.
    assert admin_client.get("/api/admin/audit").status_code == 401
    headers = _auth(admin_client)
    res = admin_client.get("/api/admin/audit", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] >= 1
    assert any(r["action"] == audit.Actions.ADMIN_LOGIN_OK for r in body["rows"])
    # The action filter is honoured.
    filtered = admin_client.get(
        "/api/admin/audit", params={"action": "does.not.exist"}, headers=headers
    )
    assert filtered.status_code == 200
    assert filtered.json()["rows"] == []


def test_memory_backend_is_bounded() -> None:
    # The in-process store keeps only the newest rows so a long-lived process
    # cannot grow without bound. Supabase keeps everything.
    from app.storage import MEMORY_MAX_AUDIT_ROWS, MemoryBackend

    backend = MemoryBackend()
    for i in range(MEMORY_MAX_AUDIT_ROWS + 50):
        backend.append_audit({"id": f"au_{i}", "ts": float(i), "action": "x"})
    assert backend.count_audit() == MEMORY_MAX_AUDIT_ROWS
    # The newest row survived, the oldest were dropped.
    assert backend.list_audit(limit=1)[0]["id"] == f"au_{MEMORY_MAX_AUDIT_ROWS + 49}"
