"""Tests for the admin login brute-force throttle (F-04).

`KETSA_ADMIN_PASSWORD` is the single key to the whole site: it can delete
accounts, reset any user's password, and resolve markets — which settles
real money. Before this, `/api/admin/login` was reachable at the global
request rate limit (~120/min/IP), which is a guessing budget, not a control.
"""

import time
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app import authstate
from app.main import create_app
from app.storage import reset_backend


@pytest.fixture()
def locked_client():
    """A client whose admin login tolerates 3 failures before locking out."""
    reset_backend()
    authstate.reset()
    with mock.patch.dict(
        "os.environ",
        {"KETSA_ADMIN_MAX_FAILURES": "3", "KETSA_ADMIN_LOCKOUT_SECONDS": "900"},
        clear=False,
    ):
        client = TestClient(create_app())
        yield client
    authstate.reset()


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
    # Counter is empty, so a fresh burst is allowed again. TestClient always
    # reports the same "testclient" IP, which is the throttle key here.
    assert authstate.throttle_get("throttle:admin:testclient") == []


def test_lockout_expires_and_login_recovers(locked_client: TestClient) -> None:
    for _ in range(3):
        locked_client.post("/api/admin/login", json={"password": "wrong"})
    assert locked_client.post("/api/admin/login", json={"password": "ketsa-admin"}).status_code == 429
    # Simulate the window elapsing: age the recorded failure stamps.
    bucket = "throttle:admin:testclient"
    stamps = authstate.throttle_get(bucket)
    assert len(stamps) == 3
    authstate.throttle_set(bucket, [t - 1000 for t in stamps], 900)
    assert locked_client.post("/api/admin/login", json={"password": "ketsa-admin"}).status_code == 200


def test_attempt_tracker_is_pruned_not_unbounded() -> None:
    """Expired throttle rows are swept so the store can't grow forever (CWE-400)."""
    authstate.reset()
    authstate.throttle_set("throttle:admin:1.1.1.1", [time.time() - 10_000], 900)  # aged stamps
    authstate.throttle_set("throttle:admin:2.2.2.2", [time.time() - 1], 900)  # fresh stamps
    # Nothing has expired yet — both rows survive a sweep.
    authstate.sweep(time.time())
    assert authstate.throttle_get("throttle:admin:1.1.1.1")
    assert authstate.throttle_get("throttle:admin:2.2.2.2")
    # After both windows have elapsed, the sweep drops the rows entirely.
    authstate.sweep(time.time() + 1800)
    assert authstate.throttle_get("throttle:admin:1.1.1.1") == []
    assert authstate.throttle_get("throttle:admin:2.2.2.2") == []
    authstate.reset()


def test_admin_endpoints_still_work_after_login(locked_client: TestClient) -> None:
    """Sanity: the throttle did not break the normal admin flow."""
    token = locked_client.post(
        "/api/admin/login", json={"password": "ketsa-admin"}
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert locked_client.get("/api/admin/me", headers=headers).json() == {"authenticated": True}
    assert locked_client.get("/api/admin/settings", headers=headers).status_code == 200
    assert locked_client.post("/api/admin/logout", headers=headers).status_code == 200
