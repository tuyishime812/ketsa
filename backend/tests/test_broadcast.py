"""Admin broadcast: one announcement to every user with an email address.

This is the highest-blast-radius endpoint in the app (one shared admin password
guards a mail blast to the entire user base), so the tests below pin the
controls that keep it from becoming a spam cannon or an address-disclosure
oracle.
"""

import time
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app import admin as admin_mod
from tests.conftest import register_user


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    admin_mod._broadcast_jobs.clear()
    monkeypatch.setattr(admin_mod, "BROADCAST_PAUSE_SECONDS", 0)
    yield
    for job in list(admin_mod._broadcast_jobs.values()):
        task = job.get("task")
        if task is not None and not task.done():
            task.cancel()
    admin_mod._broadcast_jobs.clear()


@pytest.fixture()
def admin_headers(client: TestClient) -> dict:
    token = client.post("/api/admin/login", json={"password": "ketsa-admin"}).json()[
        "token"
    ]
    return {"Authorization": f"Bearer {token}"}


def _add_email_user(client: TestClient, email: str, name: str = "Trader") -> None:
    register_user(client, email, name=name)


def _add_phone_user(client: TestClient, number: str = "0991234567") -> None:
    client.post(
        "/api/auth/register",
        json={"name": "Phone Only", "identifier": number, "password": "password123"},
    )


def _run(client: TestClient, headers: dict, subject: str, body: str):
    """Start a broadcast and poll it to completion, returning (status, calls)."""
    with mock.patch("app.mailer.send_email", return_value=True) as sender:
        res = client.post(
            "/api/admin/broadcast",
            json={"subject": subject, "body": body},
            headers=headers,
        )
        if res.status_code != 200:
            return res, list(sender.call_args_list)
        job_id = res.json()["job_id"]
        status = {}
        for _ in range(200):
            status = client.get(
                f"/api/admin/broadcast/{job_id}", headers=headers
            ).json()
            if status["status"] != "running":
                break
            time.sleep(0.01)
        return res, list(sender.call_args_list)


def test_broadcast_requires_admin_token(client: TestClient) -> None:
    res = client.post("/api/admin/broadcast", json={"subject": "Hi", "body": "Hello"})
    assert res.status_code == 401


def test_status_endpoint_requires_admin_token(client: TestClient) -> None:
    assert client.get("/api/admin/broadcast/whatever").status_code == 401


def test_broadcast_reaches_every_email_user_once(
    client: TestClient, admin_headers: dict
) -> None:
    _add_email_user(client, "alice@ketsa.io", "Alice")
    _add_email_user(client, "bob@ketsa.io", "Bob")

    res, calls = _run(client, admin_headers, "New markets", "Three new markets are live.")
    assert res.status_code == 200
    assert res.json()["total"] == 2

    recipients = [call.args[0] for call in calls]
    assert sorted(recipients) == ["alice@ketsa.io", "bob@ketsa.io"]
    # One message per recipient: never a shared To/CC/Bcc, which would leak the
    # whole user list to every recipient (CWE-200).
    assert len(recipients) == len(set(recipients)) == 2


def test_phone_only_accounts_are_skipped(
    client: TestClient, admin_headers: dict
) -> None:
    _add_email_user(client, "alice@ketsa.io", "Alice")
    _add_phone_user(client)

    res, calls = _run(client, admin_headers, "Notice", "Body copy.")
    assert res.json()["total"] == 1
    assert [call.args[0] for call in calls] == ["alice@ketsa.io"]


def test_duplicate_addresses_are_collapsed(
    client: TestClient, admin_headers: dict
) -> None:
    """A duplicated address must not receive the message twice."""
    _add_email_user(client, "alice@ketsa.io", "Alice")
    _add_phone_user(client)

    _res, calls = _run(client, admin_headers, "Notice", "Body copy.")
    recipients = [call.args[0] for call in calls]
    assert len(recipients) == len(set(recipients))


def test_broadcast_completes_and_reports_progress(
    client: TestClient, admin_headers: dict
) -> None:
    _add_email_user(client, "alice@ketsa.io", "Alice")
    res, _calls = _run(client, admin_headers, "Notice", "Body copy.")

    job_id = res.json()["job_id"]
    status = client.get(f"/api/admin/broadcast/{job_id}", headers=admin_headers).json()
    assert status["status"] == "done"
    assert status["sent"] == status["total"] == 1
    assert status["failed"] == 0
    assert status["error"] is None


def test_admin_html_is_escaped_in_the_message(
    client: TestClient, admin_headers: dict
) -> None:
    """Admin-supplied markup must not execute in a recipient's mail client."""
    _add_email_user(client, "alice@ketsa.io", "Alice")

    _res, calls = _run(
        client,
        admin_headers,
        "Hello",
        "<img src=x onerror=alert(1)><script>alert(2)</script>",
    )
    body = calls[0].args[2]
    assert "<script>" not in body
    assert "<img" not in body
    assert "onerror=alert" in body  # kept as visible text, not as a tag
    assert "&lt;script&gt;" in body


def test_subject_cannot_smuggle_crlf_headers(
    client: TestClient, admin_headers: dict
) -> None:
    """Newlines in an admin-entered subject must be collapsed, not forwarded."""
    _add_email_user(client, "alice@ketsa.io", "Alice")

    _res, calls = _run(
        client, admin_headers, "Deal\r\nX-Injected: pwned", "Body."
    )
    subject = calls[0].args[1]
    assert "\r" not in subject and "\n" not in subject


@pytest.mark.parametrize(
    "payload",
    [
        {"subject": "   ", "body": "Body."},
        {"subject": "Subject", "body": "   "},
        {"subject": "x" * 201, "body": "Body."},
        {"subject": "Subject", "body": "y" * 20_001},
    ],
)
def test_bad_input_is_rejected(
    client: TestClient, admin_headers: dict, payload: dict
) -> None:
    res = client.post("/api/admin/broadcast", json=payload, headers=admin_headers)
    assert res.status_code == 400


def test_unknown_job_id_is_404(client: TestClient, admin_headers: dict) -> None:
    assert client.get("/api/admin/broadcast/nope", headers=admin_headers).status_code == 404


def test_only_one_broadcast_runs_at_a_time(
    client: TestClient, admin_headers: dict, monkeypatch
) -> None:
    """A second blast must be refused while one is in flight."""
    # Slow the sender so the first job is still running when the second starts.
    monkeypatch.setattr(admin_mod, "BROADCAST_PAUSE_SECONDS", 5)
    _add_email_user(client, "alice@ketsa.io", "Alice")
    _add_email_user(client, "bob@ketsa.io", "Bob")

    # Both requests must share one event loop: TestClient otherwise opens (and
    # closes) a fresh portal per request, which would cancel the first job's
    # background task and let the second one start.
    with client, mock.patch("app.mailer.send_email", return_value=True):
        first = client.post(
            "/api/admin/broadcast",
            json={"subject": "One", "body": "Body."},
            headers=admin_headers,
        )
        assert first.status_code == 200
        second = client.post(
            "/api/admin/broadcast",
            json={"subject": "Two", "body": "Body."},
            headers=admin_headers,
        )
        assert second.status_code == 409

        # Cancel the in-flight job so the fixture teardown is clean.
        for job in list(admin_mod._broadcast_jobs.values()):
            task = job.get("task")
            if task is not None:
                task.cancel()


def test_broadcast_with_no_email_users_is_refused(
    client: TestClient, admin_headers: dict
) -> None:
    _add_phone_user(client)
    res = client.post(
        "/api/admin/broadcast",
        json={"subject": "Notice", "body": "Body."},
        headers=admin_headers,
    )
    assert res.status_code == 400