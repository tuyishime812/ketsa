"""Tests for the staff directory.

Covers admin CRUD, bulk CSV/JSON upload, the public (PII-free) view, the realtime
`staff` event, and honest invite reporting. The realtime test enters the app's
lifespan so the event-pump task is live and a WebSocket frame is actually pushed.
"""

import json
import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app.engine import engine
from app.main import create_app
from app.storage import reset_backend


@pytest.fixture()
def admin() -> TestClient:
    """Admin client with a fresh store and a known password.

    The env patch stays active for the whole test (the fixture yields inside the
    ``with``), so login and any request-time env reads see these values.
    """
    reset_backend()
    engine.reset()
    with mock.patch.dict(
        os.environ,
        {"KETSA_RATE_LIMIT_PER_MIN": "0", "KETSA_ADMIN_PASSWORD": "pw123"},
        clear=False,
    ):
        yield TestClient(create_app())


def _auth(client: TestClient) -> dict[str, str]:
    r = client.post("/api/admin/login", json={"password": "pw123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _add(
    client: TestClient,
    auth: dict[str, str],
    name: str = "A",
    email: str = "a@ketsa.io",
    phone: str | None = None,
    role: str = "support",
):
    return client.post(
        "/api/admin/staff",
        json={"name": name, "email": email, "phone": phone, "role": role},
        headers=auth,
    )


def test_staff_endpoints_require_admin(admin: TestClient) -> None:
    assert admin.get("/api/admin/staff").status_code == 401
    assert _add(admin, {}).status_code == 401
    assert admin.delete("/api/admin/staff/x").status_code == 401
    assert admin.post("/api/admin/staff/x/invite").status_code == 401


def test_staff_lifecycle_and_public_view_hides_pii(admin: TestClient) -> None:
    a = _auth(admin)
    r = _add(admin, a, name="Maya Support", email="maya@ketsa.io", phone="0991234567")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "maya@ketsa.io"
    assert body["active"] is True
    sid = body["id"]

    listing = admin.get("/api/admin/staff", headers=a).json()
    assert [s["id"] for s in listing] == [sid]

    # Public directory: only active staff, reduced to id/name/role — no PII.
    public = admin.get("/api/staff").json()
    assert public == [{"id": sid, "name": "Maya Support", "role": "support"}]
    assert "email" not in public[0] and "phone" not in public[0]

    d = admin.delete(f"/api/admin/staff/{sid}", headers=a)
    assert d.status_code == 200 and d.json()["ok"] is True
    assert admin.get("/api/admin/staff", headers=a).json() == []
    assert admin.get("/api/staff").json() == []


def test_staff_validation_and_duplicates(admin: TestClient) -> None:
    a = _auth(admin)
    assert _add(admin, a, name="", email="x@y.io").status_code == 400       # no name
    assert _add(admin, a, name="X", email="not-an-email").status_code == 400
    assert _add(admin, a, name="X", email="dup@y.io", role="wizard").status_code == 400
    assert _add(admin, a, name="X", email="dup@y.io").status_code == 200
    # Same email again is a conflict, not a validation error.
    assert _add(admin, a, name="Y", email="dup@y.io").status_code == 409
    # Same phone again is a conflict too.
    assert _add(admin, a, name="P", email="p@y.io", phone="0990000000").status_code == 200
    assert _add(admin, a, name="Q", email="q@y.io", phone="0990000000").status_code == 409


def test_staff_upload_csv_reports_per_row_errors_and_one_event(admin: TestClient) -> None:
    a = _auth(admin)
    engine.flush_events()
    csv_text = (
        "name,email,phone,role\n"
        "Maya,maya@ketsa.io,0991112222,support\n"
        "Bad,bad-email,,support\n"
        "NoRole,nr@ketsa.io,,wizard\n"
    )
    r = admin.post("/api/admin/staff/upload", json={"text": csv_text}, headers=a)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["added"] == 1
    assert res["skipped"] == 2
    assert len(res["errors"]) == 2
    assert [s["email"] for s in admin.get("/api/admin/staff", headers=a).json()] == [
        "maya@ketsa.io"
    ]
    # Exactly one event for the whole batch (not one per row).
    staff_events = [e for e in engine.flush_events() if e["type"] == "staff"]
    assert len(staff_events) == 1 and staff_events[0]["action"] == "upload"


def test_staff_upload_json_updates_existing(admin: TestClient) -> None:
    a = _auth(admin)
    _add(admin, a, name="Old", email="sam@ketsa.io", role="support")
    res = admin.post(
        "/api/admin/staff/upload",
        json={"rows": [{"name": "Sam", "email": "sam@ketsa.io", "role": "finance"}]},
        headers=a,
    ).json()
    assert res["updated"] == 1 and res["added"] == 0
    listing = admin.get("/api/admin/staff", headers=a).json()
    assert listing[0]["name"] == "Sam" and listing[0]["role"] == "finance"


def test_staff_mutation_emits_public_only_event(admin: TestClient) -> None:
    a = _auth(admin)
    engine.flush_events()
    sid = _add(admin, a, name="Zed", email="zed@ketsa.io", phone="0887776665").json()["id"]
    events = [e for e in engine.flush_events() if e["type"] == "staff"]
    assert events and events[-1]["action"] == "add"
    staff_payload = events[-1]["staff"]
    assert staff_payload["name"] == "Zed" and staff_payload["role"] == "support"
    # The socket is unauthenticated: contact details must never ride on it.
    assert "email" not in staff_payload and "phone" not in staff_payload

    admin.delete(f"/api/admin/staff/{sid}", headers=a)
    events = [e for e in engine.flush_events() if e["type"] == "staff"]
    assert events and events[-1]["action"] == "remove" and events[-1]["staff"] is None


def test_staff_update_toggles_active_and_hides_from_public(admin: TestClient) -> None:
    a = _auth(admin)
    sid = _add(admin, a, name="Tog", email="tog@ketsa.io").json()["id"]
    r = admin.put(f"/api/admin/staff/{sid}", json={"active": False}, headers=a)
    assert r.status_code == 200 and r.json()["active"] is False
    assert admin.get("/api/staff").json() == []
    assert admin.put("/api/admin/staff/nope", json={"active": False}, headers=a).status_code == 404


def test_staff_invite_reports_delivery_honestly(admin: TestClient) -> None:
    a = _auth(admin)
    sid = _add(admin, a, name="Ivy", email="ivy@ketsa.io").json()["id"]

    # Unconfigured transport: the mailer logs instead of sending; we must say so.
    with mock.patch("app.mailer.delivery_configured", return_value=False), mock.patch(
        "app.mailer.send_staff_invite", return_value=True
    ):
        body = admin.post(f"/api/admin/staff/{sid}/invite", headers=a).json()
    assert body["ok"] is True
    assert body["delivered"] is False
    assert "not" in body["detail"].lower()

    # Configured transport: reported as truly sent.
    with mock.patch("app.mailer.delivery_configured", return_value=True), mock.patch(
        "app.mailer.send_staff_invite", return_value=True
    ):
        body = admin.post(f"/api/admin/staff/{sid}/invite", headers=a).json()
    assert body["delivered"] is True and body["ok"] is True

    assert admin.post("/api/admin/staff/nope/invite", headers=a).status_code == 404


def test_staff_change_pushes_to_websocket_in_realtime(admin: TestClient) -> None:
    """End-to-end: the event-pump task broadcasts a live frame to clients."""
    with admin:  # entering the context starts the app lifespan (pump task live)
        auth = _auth(admin)
        with admin.websocket_connect("/api/ws") as ws:
            r = admin.post(
                "/api/admin/staff",
                json={"name": "Live", "email": "live@ketsa.io", "role": "support"},
                headers=auth,
            )
            assert r.status_code == 200, r.text
            frame = None
            for _ in range(10):
                payload = json.loads(ws.receive_text())
                if payload.get("type") == "staff":
                    frame = payload
                    break
            assert frame is not None, "expected a live staff frame on the socket"
            assert frame["action"] == "add"
            assert frame["staff"]["name"] == "Live"
