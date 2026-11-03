"""Tests for the admin-configurable operational controls (Settings tab).

Covers GET/PUT /api/admin/config[/{section}] — payments limits + enables,
security lockout, the staff role allowlist, and market-resolution guards — plus
the security-relevant guarantee that none of it leaks into the public bundle.
"""

import os
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app import authstate
from app.engine import engine
from app.main import create_app
from app.storage import reset_backend


@pytest.fixture()
def admin() -> TestClient:
    reset_backend()
    engine.reset()
    authstate.reset()
    with mock.patch.dict(
        os.environ,
        {"KETSA_RATE_LIMIT_PER_MIN": "0", "KETSA_ADMIN_PASSWORD": "pw123"},
        clear=False,
    ):
        yield TestClient(create_app())
    authstate.reset()


def _auth(client: TestClient) -> dict[str, str]:
    r = client.post("/api/admin/login", json={"password": "pw123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _market(market_id: str, end_date: str | None = None) -> dict:
    m = {
        "id": market_id,
        "cat": "tech",
        "tag": "Tech",
        "q": f"Will {market_id} resolve?",
        "yes": 42,
        "no": 58,
        "meta": ["$1M vol", "2K traders"],
        "trend": "up",
        "pts": [10, 12, 14, 16],
    }
    if end_date is not None:
        m["end_date"] = end_date
    return m


def test_config_requires_admin(admin: TestClient) -> None:
    assert admin.get("/api/admin/config").status_code == 401
    assert admin.put("/api/admin/config/payments", json={}).status_code == 401


def test_config_get_returns_all_sections_with_defaults(admin: TestClient) -> None:
    a = _auth(admin)
    cfg = admin.get("/api/admin/config", headers=a).json()
    assert set(cfg) == {"payments", "security", "staff_roles", "resolution"}
    assert cfg["payments"] == {
        "deposits_enabled": True,
        "withdrawals_enabled": True,
        "max_deposit_mwk": 1_000_000.0,
        "max_withdrawal_mwk": 1_000_000.0,
        "daily_withdrawal_limit_mwk": 3_000_000.0,
    }
    assert cfg["security"] == {"admin_max_failures": 10, "admin_lockout_seconds": 900}
    assert cfg["staff_roles"]["roles"] == [
        "owner",
        "admin",
        "support",
        "finance",
        "marketing",
        "moderation",
    ]
    assert cfg["resolution"] == {"resolution_enabled": True, "require_end_date": False}


def test_config_defaults_follow_env(admin: TestClient) -> None:
    """With no stored override, the env var is the effective default."""
    a = _auth(admin)
    with mock.patch.dict(os.environ, {"KETSA_MAX_DEPOSIT_MWK": "5000"}, clear=False):
        cfg = admin.get("/api/admin/config", headers=a).json()
    assert cfg["payments"]["max_deposit_mwk"] == 5000.0


def test_config_validation_rejects_bad_values(admin: TestClient) -> None:
    a = _auth(admin)
    # Non-numeric and out-of-range money.
    assert (
        admin.put("/api/admin/config/payments", json={"max_deposit_mwk": "abc"}, headers=a).status_code
        == 400
    )
    assert (
        admin.put("/api/admin/config/payments", json={"max_deposit_mwk": -5}, headers=a).status_code
        == 400
    )
    # Daily cap below the per-transaction cap is incoherent.
    assert (
        admin.put(
            "/api/admin/config/payments",
            json={"max_withdrawal_mwk": 9000, "daily_withdrawal_limit_mwk": 100},
            headers=a,
        ).status_code
        == 400
    )
    # Lockout bounds.
    assert (
        admin.put("/api/admin/config/security", json={"admin_max_failures": 0}, headers=a).status_code
        == 400
    )
    # Unknown section is a 404, not a silent no-op.
    assert admin.put("/api/admin/config/nope", json={}, headers=a).status_code == 404


def test_config_persists_and_partial_merge_keeps_other_fields(admin: TestClient) -> None:
    a = _auth(admin)
    r = admin.put(
        "/api/admin/config/payments",
        json={"deposits_enabled": False, "max_deposit_mwk": 250_000},
        headers=a,
    )
    assert r.status_code == 200, r.text
    cfg = admin.get("/api/admin/config", headers=a).json()["payments"]
    assert cfg["deposits_enabled"] is False
    assert cfg["max_deposit_mwk"] == 250_000.0
    # Fields we didn't send keep their defaults.
    assert cfg["max_withdrawal_mwk"] == 1_000_000.0


def test_staff_roles_allowlist_is_configurable(admin: TestClient) -> None:
    a = _auth(admin)
    r = admin.put(
        "/api/admin/config/staff_roles",
        json={"roles": ["captain", "support"]},
        headers=a,
    )
    assert r.status_code == 200, r.text

    ok = admin.post(
        "/api/admin/staff",
        json={"name": "Cap", "email": "cap@ketsa.io", "role": "captain"},
        headers=a,
    )
    assert ok.status_code == 200, ok.text

    # A role no longer in the allowlist is rejected.
    bad = admin.post(
        "/api/admin/staff",
        json={"name": "Fin", "email": "fin@ketsa.io", "role": "finance"},
        headers=a,
    )
    assert bad.status_code == 400

    # Invalid slugs and empty lists are rejected.
    assert (
        admin.put("/api/admin/config/staff_roles", json={"roles": ["Bad Role!"]}, headers=a).status_code
        == 400
    )
    assert admin.put("/api/admin/config/staff_roles", json={"roles": []}, headers=a).status_code == 400


def test_existing_staff_keep_a_removed_role(admin: TestClient) -> None:
    """Narrowing the allowlist must not break edits of existing members.

    Removing a role only affects *new* assignments; a member who already holds
    it can still be toggled/edited, and a role-less upload row falls back to the
    first allowed role rather than a hard-coded "support".
    """
    a = _auth(admin)
    sid = admin.post(
        "/api/admin/staff",
        json={"name": "Fin", "email": "fin@ketsa.io", "role": "finance"},
        headers=a,
    ).json()["id"]

    # Remove "finance" and "support" from the allowlist.
    assert (
        admin.put("/api/admin/config/staff_roles", json={"roles": ["captain"]}, headers=a).status_code
        == 200
    )
    # Toggling the existing member (who still holds "finance") still works.
    r = admin.put(f"/api/admin/staff/{sid}", json={"active": False}, headers=a)
    assert r.status_code == 200, r.text
    assert r.json()["active"] is False and r.json()["role"] == "finance"

    # A role-less upload row defaults to the first allowed role, not "support".
    admin.post(
        "/api/admin/staff/upload",
        json={"rows": [{"name": "Cap", "email": "cap2@ketsa.io"}]},
        headers=a,
    )
    roles = {s["email"]: s["role"] for s in admin.get("/api/admin/staff", headers=a).json()}
    assert roles["cap2@ketsa.io"] == "captain"


def test_payments_disabled_blocks_deposits_and_withdrawals(admin: TestClient) -> None:
    a = _auth(admin)
    body = {
        "wallet_id": "w-anything",
        "amount": 500,
        "number": "0991234567",
        "correspondent": "AIRTEL",
    }
    # Pretend the gateway is configured, so the only reason left to refuse is the
    # admin toggle (the enabled check runs before auth).
    with mock.patch("app.main.paychangu.configured", return_value=True):
        assert (
            admin.put("/api/admin/config/payments", json={"deposits_enabled": False}, headers=a).status_code
            == 200
        )
        r = admin.post("/api/payments/deposits", json=body)
        assert r.status_code == 503
        assert "disabled" in r.json()["detail"].lower()

        assert (
            admin.put(
                "/api/admin/config/payments",
                json={"deposits_enabled": True, "withdrawals_enabled": False},
                headers=a,
            ).status_code
            == 200
        )
        r = admin.post("/api/payments/withdrawals", json=body)
        assert r.status_code == 503
        assert "disabled" in r.json()["detail"].lower()


def test_resolution_disabled_blocks_settlement(admin: TestClient) -> None:
    a = _auth(admin)
    assert admin.post("/api/admin/markets", json=_market("cfg-res"), headers=a).status_code == 200
    assert (
        admin.put("/api/admin/config/resolution", json={"resolution_enabled": False}, headers=a).status_code
        == 200
    )
    r = admin.post("/api/admin/markets/cfg-res/resolve", json={"outcome": "yes"}, headers=a)
    assert r.status_code == 503


def test_resolution_require_end_date_guard(admin: TestClient) -> None:
    a = _auth(admin)
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    assert (
        admin.post("/api/admin/markets", json=_market("cfg-future", future), headers=a).status_code
        == 200
    )
    assert (
        admin.put("/api/admin/config/resolution", json={"require_end_date": True}, headers=a).status_code
        == 200
    )
    # Not due yet → refused.
    assert (
        admin.post("/api/admin/markets/cfg-future/resolve", json={"outcome": "yes"}, headers=a).status_code
        == 400
    )
    # A market with no end date is treated as due and settles normally.
    assert admin.post("/api/admin/markets", json=_market("cfg-due"), headers=a).status_code == 200
    assert (
        admin.post("/api/admin/markets/cfg-due/resolve", json={"outcome": "yes"}, headers=a).status_code
        == 200
    )


def test_security_lockout_threshold_is_configurable(admin: TestClient) -> None:
    a = _auth(admin)
    assert (
        admin.put("/api/admin/config/security", json={"admin_max_failures": 1}, headers=a).status_code
        == 200
    )
    # One failure is now enough to trip the fence for this IP.
    assert admin.post("/api/admin/login", json={"password": "wrong"}).status_code == 401
    assert admin.post("/api/admin/login", json={"password": "pw123"}).status_code == 429
    authstate.reset()


def test_public_home_never_leaks_config(admin: TestClient) -> None:
    a = _auth(admin)
    admin.put("/api/admin/config/payments", json={"max_deposit_mwk": 777_000}, headers=a)
    admin.put("/api/admin/config/security", json={"admin_max_failures": 2}, headers=a)

    settings = admin.get("/api/home").json()["settings"]
    for leaked in ("payments", "security", "staff_roles", "resolution"):
        assert leaked not in settings
        assert f"config:{leaked}" not in settings
    # The real public content is still present.
    assert "hero" in settings and "footer" in settings
