"""Tests for the admin login brute-force throttle (F-04).

`KETSA_ADMIN_PASSWORD` is the single key to the whole site: it can delete
accounts, reset any user's password, and resolve markets — which settles
real money. Before this, `/api/admin/login` was reachable at the global
request rate limit (~120/min/IP), which is a guessing budget, not a control.
"""

from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app import admin
from app.main import create_app
from app.storage import reset_backend


@pytest.fixture()
def locked_client():
    """A client whose admin login tolerates 3 failures before locking out."""
    reset_backend()
    admin._login_attempts.clear()
    with mock.patch.dict(
        "os.environ",
        {"KETSA_ADMIN_MAX_FAILURES": "3", "KETSA_ADMIN_LOCKOUT_SECONDS": "900"},
        clear=False,
    ):
        client = TestClient(create_app())
        yield client
    admin._login_attempts.clear()


def test_admin_login_locks_out_after_max_failures(locked_client: TestClient) -> None:
    for _ in range(3):
        res = locked_client.post("/api/admin/login", json={"password": "wrong"})
        assert res.status_code == 401
    # Fourth attempt is refused even with the CORRECT password.
    res = locked_client.post("/api/admin/login", json={"password": "ketsa-admin"})
    assert res.status_code == 429
    assert "s" in res.json()["detail"]  # retry-after seconds


def test_admin_lockout_window_is_reported(locked_client: TestClient) -> None:
    for _ in range(3):
        locked_client.post("/api/admin/login", json={"password": "wrong"})
    res = locked_client.post("/api/admin/login", json={"password": "ketsa-admin"})
    assert res.status_code == 429
    detail = res.json()["detail"]
    assert "Try again in" in detail
    # ~900s window, allowing for the sub-second time the test itself consumed.
    assert detail.endswith("s.") and 895 <= int(detail.split()[-1].rstrip("s.")) <= 900


def test_successful_login_clears_the_failure_counter(locked_client: TestClient) -> None:
    assert locked_client.post(
        "/api/admin/login", json={"password": "ketsa-admin"}
    ).status_code == 200
    # Counter is empty, so a fresh burst is allowed again.
    assert admin._login_attempts == {} or all(
        not v for v in admin._login_attempts.values()
    )


def test_lockout_expires_and_login_recovers(locked_client: TestClient) -> None:
    for _ in range(3):
        locked_client.post("/api/admin/login", json={"password": "wrong"})
    assert locked_client.post("/api/admin/login", json={"password": "ketsa-admin"}).status_code == 429
    # Simulate the window elapsing.
    admin._login_attempts = {k: [t - 1000 for t in v] for k, v in admin._login_attempts.items()}
    assert locked_client.post("/api/admin/login", json={"password": "ketsa-admin"}).status_code == 200


def test_attempt_tracker_is_pruned_not_unbounded() -> None:
    """Expired entries are dropped so the dict can't grow forever (CWE-400)."""
    admin._login_attempts.clear()
    now = 10_000.0
    admin._login_attempts["1.1.1.1"] = [now - 10_000]  # long expired
    admin._login_attempts["2.2.2.2"] = [now - 1]  # still live
    admin._prune_login_attempts(now, 900)
    assert "1.1.1.1" not in admin._login_attempts
    assert "2.2.2.2" in admin._login_attempts
    admin._login_attempts.clear()


def test_admin_endpoints_still_work_after_login(locked_client: TestClient) -> None:
    """Sanity: the throttle did not break the normal admin flow."""
    token = locked_client.post(
        "/api/admin/login", json={"password": "ketsa-admin"}
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert locked_client.get("/api/admin/me", headers=headers).json() == {"authenticated": True}
    assert locked_client.get("/api/admin/settings", headers=headers).status_code == 200
    assert locked_client.post("/api/admin/logout", headers=headers).status_code == 200
