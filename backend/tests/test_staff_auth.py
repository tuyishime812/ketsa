"""Tests for per-staff admin credentials, sessions and role enforcement.

Covers the invite â†’ set-password â†’ login flow, single-use/expiring links,
session revocation on deactivation, object-level owner protections and the
capability matrix that the server (not the UI) enforces.
"""

import os
import time
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app import authstate, store
from app.main import create_app
from app.storage import reset_backend


@pytest.fixture()
def client() -> TestClient:
    reset_backend()
    authstate.reset()
    with mock.patch.dict(
        os.environ,
        {
            "KETSA_RATE_LIMIT_PER_MIN": "0",
            "KETSA_ADMIN_PASSWORD": "pw123",
            "KETSA_EMAIL_DELIVERY": "log",
            "KETSA_PUBLIC_URL": "https://ketsa.test",
        },
        clear=False,
    ):
        yield TestClient(create_app())
    authstate.reset()


def _master(c: TestClient) -> dict[str, str]:
    r = c.post("/api/admin/login", json={"password": "pw123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _add(c: TestClient, auth: dict[str, str], email: str, role: str = "support") -> str:
    r = c.post(
        "/api/admin/staff",
        json={"name": email.split("@")[0], "email": email, "role": role},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _capture_link(c: TestClient, auth: dict[str, str], staff_id: str, reset: bool = False) -> str:
    """Trigger a credential link and return the emailed token (never the URL)."""
    captured: dict[str, str] = {}

    def fake(to, link, *a, **kw):
        captured["link"] = link
        return True

    with mock.patch("app.mailer.send_staff_credentials_invite", side_effect=fake):
        path = "reset" if reset else "invite"
        r = c.post(f"/api/admin/staff/{staff_id}/credentials/{path}", headers=auth)
    assert r.status_code == 200, r.text
    token = parse_qs(urlparse(captured["link"]).fragment)["token"][0]
    assert token
    return token


def _set_password(c: TestClient, auth: dict[str, str], email: str, role: str, password: str) -> None:
    sid = _add(c, auth, email, role)
    token = _capture_link(c, auth, sid)
    r = c.post(
        "/api/admin/staff/accept-invite",
        json={"token": token, "password": password},
    )
    assert r.status_code == 200, r.text


def _staff_login(c: TestClient, email: str, password: str) -> dict[str, str]:
    r = c.post("/api/admin/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_invite_set_password_login_session_and_logout(client: TestClient) -> None:
    master = _master(client)
    sid = _add(client, master, "maya@ketsa.io", "support")
    token = _capture_link(client, master, sid)

    # The admin view exposes credential *state* but never credential material.
    listing = client.get("/api/admin/staff", headers=master).json()
    assert listing[0]["login_enabled"] is False and listing[0]["invite_pending"] is True
    for leaked in ("password_hash", "invite_token_hash", "invite_expires", "password"):
        assert leaked not in listing[0]

    r = client.post("/api/admin/staff/accept-invite", json={"token": token, "password": "s3cret-pass"})
    assert r.status_code == 200, r.text

    # Single use: replaying the same link must fail.
    again = client.post("/api/admin/staff/accept-invite", json={"token": token, "password": "other-pass"})
    assert again.status_code == 400

    headers = _staff_login(client, "maya@ketsa.io", "s3cret-pass")
    session = client.get("/api/admin/session", headers=headers).json()
    assert session["kind"] == "staff"
    assert session["id"] == sid
    assert session["role"] == "support"
    assert "content:read" in session["capabilities"]
    assert "staff:write" not in session["capabilities"]

    # Legacy contract stays byte-for-byte identical.
    assert client.get("/api/admin/me", headers=headers).json() == {"authenticated": True}

    assert client.post("/api/admin/logout", headers=headers).status_code == 200
    assert client.get("/api/admin/session", headers=headers).status_code == 401


def test_wrong_password_is_generic_and_does_not_enumerate(client: TestClient) -> None:
    unknown = client.post(
        "/api/admin/login", json={"email": "nobody@ketsa.io", "password": "whatever"}
    )
    assert unknown.status_code == 401
    assert unknown.json()["detail"] == "Invalid email or password"


def test_expired_invite_is_rejected(client: TestClient) -> None:
    master = _master(client)
    sid = _add(client, master, "exp@ketsa.io")
    token = _capture_link(client, master, sid)
    member = store.get_staff(sid)
    member["invite_expires"] = time.time() - 1
    store.upsert_staff(member)

    r = client.post("/api/admin/staff/accept-invite", json={"token": token, "password": "valid-pass"})
    assert r.status_code == 400


def test_deactivation_revokes_live_sessions_and_blocks_login(client: TestClient) -> None:
    master = _master(client)
    _set_password(client, master, "fin@ketsa.io", "finance", "fin-password")
    headers = _staff_login(client, "fin@ketsa.io", "fin-password")
    assert client.get("/api/admin/session", headers=headers).status_code == 200

    sid = client.get("/api/admin/session", headers=headers).json()["id"]
    assert client.put(f"/api/admin/staff/{sid}", json={"active": False}, headers=master).status_code == 200

    # The live session is dead immediately, and a fresh login is refused.
    assert client.get("/api/admin/session", headers=headers).status_code == 401
    assert client.post(
        "/api/admin/login", json={"email": "fin@ketsa.io", "password": "fin-password"}
    ).status_code == 401


def test_forgot_password_is_generic_and_sends_for_known_account(client: TestClient) -> None:
    master = _master(client)
    sid = _add(client, master, "help@ketsa.io")
    token = _capture_link(client, master, sid)  # set an initial password
    assert client.post(
        "/api/admin/staff/accept-invite", json={"token": token, "password": "initial-pass"}
    ).status_code == 200

    unknown = client.post("/api/admin/staff/forgot", json={"email": "ghost@ketsa.io"})
    assert unknown.status_code == 200
    assert "if that email belongs" in unknown.json()["detail"].lower()

    captured: dict[str, str] = {}

    def fake(to, link, *a, **kw):
        captured["link"] = link
        return True

    with mock.patch("app.mailer.send_staff_credentials_invite", side_effect=fake):
        known = client.post("/api/admin/staff/forgot", json={"email": "help@ketsa.io"})
    assert known.status_code == 200
    assert known.json() == unknown.json()
    token = parse_qs(urlparse(captured["link"]).fragment)["token"][0]
    assert client.post(
        "/api/admin/staff/accept-invite", json={"token": token, "password": "reset-pass"}
    ).status_code == 200
    _staff_login(client, "help@ketsa.io", "reset-pass")


def test_read_only_roles_cannot_write(client: TestClient) -> None:
    master = _master(client)
    _set_password(client, master, "sup@ketsa.io", "support", "sup-password")
    support = _staff_login(client, "sup@ketsa.io", "sup-password")

    assert client.get("/api/admin/settings", headers=support).status_code == 200
    assert client.put(
        "/api/admin/settings", json={"hero": {"title": "x"}}, headers=support
    ).status_code == 403
    assert client.get("/api/admin/users", headers=support).status_code == 200
    assert client.delete("/api/admin/users/whatever", headers=support).status_code == 403
    assert client.post(
        "/api/admin/staff",
        json={"name": "N", "email": "new@ketsa.io", "role": "support"},
        headers=support,
    ).status_code == 403


def test_role_matrix_for_privileged_writes(client: TestClient) -> None:
    master = _master(client)
    _set_password(client, master, "mk@ketsa.io", "marketing", "mk-password")
    _set_password(client, master, "adm@ketsa.io", "admin", "adm-password")
    marketing = _staff_login(client, "mk@ketsa.io", "mk-password")
    admin = _staff_login(client, "adm@ketsa.io", "adm-password")

    # Marketing may edit content but not read/change operational config.
    assert client.put(
        "/api/admin/settings", json={"hero": {"title": "ok"}}, headers=marketing
    ).status_code == 200
    assert client.get("/api/admin/config", headers=marketing).status_code == 403

    # Admin has broad access but cannot change security configuration...
    assert client.get("/api/admin/config", headers=admin).status_code == 200
    assert client.put("/api/admin/config/security", json={}, headers=admin).status_code == 403
    # ...while the break-glass master session can.
    assert client.put("/api/admin/config/security", json={}, headers=master).status_code == 200


def test_staff_owner_cannot_change_security_fence(client: TestClient) -> None:
    """An `owner` *staff* row is powerful, but the security fence stays master-only."""
    master = _master(client)
    _set_password(client, master, "own2@ketsa.io", "owner", "own-password")
    owner = _staff_login(client, "own2@ketsa.io", "own-password")

    assert client.get("/api/admin/config", headers=owner).status_code == 200
    assert client.put("/api/admin/config/security", json={}, headers=owner).status_code == 403
    assert client.put("/api/admin/config/staff_roles", json={}, headers=owner).status_code == 403
    # Operational, non-security sections remain available to an owner role.
    assert client.put("/api/admin/config/resolution", json={}, headers=owner).status_code == 200


def test_bulk_upload_cannot_escalate_or_demote_owner(client: TestClient) -> None:
    master = _master(client)
    owner_email = "owner@ketsa.io"
    _add(client, master, owner_email, "owner")
    _set_password(client, master, "adm@ketsa.io", "admin", "adm-password")
    admin = _staff_login(client, "adm@ketsa.io", "adm-password")

    # Creating a new owner through the bulk path is escalation.
    assert client.post(
        "/api/admin/staff/upload",
        json={"rows": [{"name": "X", "email": "x@ketsa.io", "role": "owner"}]},
        headers=admin,
    ).status_code == 403

    # Rewriting the existing owner row (e.g. demoting it) is sabotage.
    assert client.post(
        "/api/admin/staff/upload",
        json={"rows": [{"name": "Owner", "email": owner_email, "role": "support"}]},
        headers=admin,
    ).status_code == 403

    # The master session is allowed to manage the owner row.
    assert client.post(
        "/api/admin/staff/upload",
        json={"rows": [{"name": "Owner", "email": owner_email, "role": "owner"}]},
        headers=master,
    ).status_code == 200


def test_non_master_cannot_grant_or_touch_owner_role(client: TestClient) -> None:
    master = _master(client)
    owner_sid = _add(client, master, "owner@ketsa.io", "owner")
    _set_password(client, master, "adm@ketsa.io", "admin", "adm-password")
    admin = _staff_login(client, "adm@ketsa.io", "adm-password")

    # Cannot create a new owner...
    assert client.post(
        "/api/admin/staff",
        json={"name": "Sneaky", "email": "sneaky@ketsa.io", "role": "owner"},
        headers=admin,
    ).status_code == 403
    # ...cannot promote themselves...
    admin_id = client.get("/api/admin/session", headers=admin).json()["id"]
    assert client.put(
        f"/api/admin/staff/{admin_id}", json={"role": "owner"}, headers=admin
    ).status_code == 403
    # ...and cannot reset/disable the existing owner.
    assert client.post(
        f"/api/admin/staff/{owner_sid}/credentials/reset", headers=admin
    ).status_code == 403
    assert client.put(
        f"/api/admin/staff/{owner_sid}", json={"active": False}, headers=admin
    ).status_code == 403

    # The master session still can.
    assert client.post(
        f"/api/admin/staff/{owner_sid}/credentials/reset", headers=master
    ).status_code == 200


def test_self_service_password_change_revokes_sessions(client: TestClient) -> None:
    master = _master(client)
    _set_password(client, master, "self@ketsa.io", "finance", "old-password")
    headers = _staff_login(client, "self@ketsa.io", "old-password")

    assert client.post(
        "/api/admin/staff/password",
        json={"current": "wrong", "new": "new-password"},
        headers=headers,
    ).status_code == 400
    assert client.post(
        "/api/admin/staff/password",
        json={"current": "old-password", "new": "new-password"},
        headers=headers,
    ).status_code == 200
    # Every device (including this one) must sign in again.
    assert client.get("/api/admin/session", headers=headers).status_code == 401
    _staff_login(client, "self@ketsa.io", "new-password")


def test_credential_link_keeps_token_out_of_the_query_string(client: TestClient) -> None:
    """Fragments never reach server/proxy/CDN logs; query strings do."""
    master = _master(client)
    sid = _add(client, master, "frag@ketsa.io")
    captured: dict[str, str] = {}

    def fake(to, link, *a, **kw):
        captured["link"] = link
        return True

    with mock.patch("app.mailer.send_staff_credentials_invite", side_effect=fake):
        r = client.post(f"/api/admin/staff/{sid}/credentials/invite", headers=master)
    assert r.status_code == 200, r.text
    link = captured["link"]
    assert "#token=" in link
    assert "?token=" not in link


def test_credentials_are_never_returned_or_logged(client: TestClient, caplog) -> None:
    from app import mailer

    master = _master(client)
    sid = _add(client, master, "log@ketsa.io")
    _capture_link(client, master, sid)  # mints a real token; never returned

    # The dev log transport must mask credential tokens in the email body.
    with caplog.at_level("WARNING", logger="app.mailer"):
        mailer.send_staff_credentials_invite(
            "log@ketsa.io",
            "https://ketsa.test/admin/set-password?token=SUPERSECRETTOKEN",
            "Log",
            "support",
        )

    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert "SUPERSECRETTOKEN" not in blob
    assert "redacted" in blob

    body = client.get("/api/admin/staff", headers=master).text
    assert "password_hash" not in body
    assert "invite_token_hash" not in body


def test_bootstrap_script_creates_a_working_owner(
    client: TestClient, monkeypatch
) -> None:
    """Recovery path: an operator with server access can set a staff password."""
    import importlib.util
    import io
    from pathlib import Path

    from app import staff, staffauth

    script = Path(__file__).resolve().parents[1] / "scripts" / "set_staff_password.py"
    spec = importlib.util.spec_from_file_location("set_staff_password", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # load_dotenv() must not drag the test onto a real Supabase project or leak
    # values from backend/.env into the rest of the suite.
    monkeypatch.setattr(module, "load_dotenv", lambda: None)
    monkeypatch.setenv("KETSA_DB_BACKEND", "memory")
    monkeypatch.setattr(
        "sys.argv",
        [
            "set_staff_password.py",
            "--email",
            "boot@ketsa.io",
            "--name",
            "Boot",
            "--role",
            "owner",
            "--password-stdin",
        ],
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("boot-password\n"))
    assert module.main() == 0

    member = staff.find_by_email("boot@ketsa.io")
    assert member is not None
    assert member["role"] == "owner"
    assert member["password_hash"]
    assert member["password_hash"] != "boot-password"
    assert staffauth.verify_credentials("boot@ketsa.io", "boot-password") is not None
