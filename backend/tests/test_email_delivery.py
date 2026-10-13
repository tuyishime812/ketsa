"""What the API says when the OTP email cannot be delivered.

Regression cover for the original "Create account button does nothing" report:
the endpoint used to answer 202 and tell the user to check an inbox for an
email the transport had already rejected, leaving them parked on a verify step
that could never be completed.

Two different policies, and the tests below exist to keep them apart:

  * ``/register`` and ``/register/resend`` MAY report the failure. They only
    ever mail a *pending/new* signup, so a distinct status discloses nothing
    that the existing 409 duplicate check does not already disclose.

  * ``/forgot-password`` and ``/login/code`` must NOT report it. Those sends
    happen only when the identifier matched a real account, so a failure status
    would answer "does this address have an account?" — user enumeration
    (CWE-203). Their uniform 200 is a security property, not an oversight.
"""

from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app import auth as auth_mod
from app import authstate
from app import mailer


@pytest.fixture(autouse=True)
def _clean_state():
    authstate.reset()
    yield
    authstate.reset()


def _register(client: TestClient, email: str = "alice@ketsa.io"):
    return client.post(
        "/api/auth/register",
        json={"name": "Alice", "identifier": email, "password": "password123"},
    )


def _rewind_cooldown(email: str = "alice@ketsa.io") -> None:
    """Age the pending signup's `issued` stamp past the resend cooldown.

    Without this every resend test short-circuits on the 60s cooldown and
    never reaches the send path it is meant to cover — a silently vacuous pass.
    """
    import time

    entry = authstate.get_otp(f"signup:{email}")
    assert entry is not None, "expected a pending signup first"
    authstate.age_otp(f"signup:{email}", time.time() - 9999)


# --- /register: honest about a failed send ---------------------------------


def test_register_reports_a_failed_email(client: TestClient) -> None:
    with mock.patch("app.mailer.send_otp_email", return_value=False):
        res = _register(client)
    assert res.status_code == 502, res.text
    assert "verification email" in res.json()["detail"]


def test_failed_send_leaves_no_stuck_pending_state(client: TestClient) -> None:
    """The user must be able to retry immediately after the failure.

    If the half-issued OTP survived, the retry would hit the 60s resend
    cooldown for a code that was never delivered — the button would appear
    broken a second time.
    """
    with mock.patch("app.mailer.send_otp_email", return_value=False):
        assert _register(client).status_code == 502
    assert authstate.get_otp("signup:alice@ketsa.io") is None

    # No cooldown carried over: a fresh send is accepted right away.
    with mock.patch(
        "app.mailer.send_otp_email", side_effect=lambda *a, **k: True
    ) as sender:
        retry = _register(client)
    assert retry.status_code == 202, retry.text
    assert sender.call_count == 1


def test_successful_send_still_returns_pending(client: TestClient) -> None:
    with mock.patch("app.mailer.send_otp_email", return_value=True):
        res = _register(client)
    assert res.status_code == 202, res.text
    assert res.json()["pending"] is True


def test_no_account_is_created_when_the_email_fails(client: TestClient) -> None:
    """A rejected signup must not leave a half-registered account behind."""
    with mock.patch("app.mailer.send_otp_email", return_value=False):
        _register(client)
    assert auth_mod.store.get_user_by_email("alice@ketsa.io") is None


def test_resend_reports_a_failed_email(client: TestClient) -> None:
    with mock.patch("app.mailer.send_otp_email", return_value=True):
        _register(client)
    _rewind_cooldown()

    with mock.patch("app.mailer.send_otp_email", return_value=False):
        res = client.post(
            "/api/auth/register/resend", json={"email": "alice@ketsa.io"}
        )
    assert res.status_code == 502, res.text
    assert "verification email" in res.json()["detail"]


def test_failed_resend_keeps_the_pending_signup_alive(client: TestClient) -> None:
    """The pending signup (name + password hash) must survive a failed resend.

    Dropping it would strand the user on the verify step with no code and no
    way to resend — they would have to fill the form in again.
    """
    with mock.patch("app.mailer.send_otp_email", return_value=True):
        _register(client)
    _rewind_cooldown()

    with mock.patch("app.mailer.send_otp_email", return_value=False):
        resent = client.post("/api/auth/register/resend", json={"email": "alice@ketsa.io"})
    # Guard against the test silently degrading into a cooldown short-circuit.
    assert resent.status_code == 502, resent.text

    entry = authstate.get_otp("signup:alice@ketsa.io")
    assert entry is not None, "pending signup must not be discarded"
    assert (entry.get("payload") or {}).get("password_hash")


# --- enumeration-sensitive endpoints: uniformly 200, always ----------------


@pytest.mark.parametrize(
    "path, payload",
    [
        ("/api/auth/forgot-password", {"identifier": "alice@ketsa.io"}),
        ("/api/auth/login/code", {"identifier": "alice@ketsa.io"}),
    ],
)
def test_account_discovery_endpoints_stay_uniform_on_send_failure(
    client: TestClient, path: str, payload: dict
) -> None:
    """A known address whose mail fails must look exactly like an unknown one.

    Both endpoints only send when the account exists, so returning 502 here
    would let an attacker tell registered addresses apart (CWE-203).
    """
    from tests.conftest import register_user

    register_user(client, "alice@ketsa.io")

    with mock.patch("app.mailer.send_otp_email", return_value=False):
        known = client.post(path, json=payload)

    with mock.patch("app.mailer.send_otp_email", return_value=True):
        unknown = client.post(
            path, json={"identifier": "nobody@ketsa.io"}
        )

    assert known.status_code == 200, known.text
    assert known.json() == {"ok": True}
    # Byte-for-byte identical reply, so the failure is not an oracle.
    assert known.status_code == unknown.status_code
    assert known.json() == unknown.json()


# --- dev mode keeps working ------------------------------------------------


def test_dev_mode_without_a_key_still_delivers_to_the_log(
    client: TestClient, monkeypatch
) -> None:
    """No API key means "logged, not sent" — that must count as delivered.

    Dev mode is the documented local workflow, so register has to succeed
    rather than start returning 502 on every fresh checkout.
    """
    monkeypatch.delenv("KETSA_RESEND_API_KEY", raising=False)
    assert mailer._api_key() is None
    assert mailer.send_email("dev@ketsa.io", "test", "<p>hi</p>") is True

    res = _register(client, email="dev@ketsa.io")
    assert res.status_code == 202, res.text


# --- explicit KETSA_EMAIL_DELIVERY switch ----------------------------------


def test_log_mode_skips_the_network_even_with_a_key(
    client: TestClient, monkeypatch
) -> None:
    """`log` is the local-dev transport: a configured key must NOT be used.

    This is the exact fix for "Create account fails locally": a developer with a
    real Resend key set (whose sandbox sender 403s every other recipient) still
    gets a completed signup, because the code goes to the log instead.
    """
    monkeypatch.setenv("KETSA_RESEND_API_KEY", "re_fake_key")
    monkeypatch.setenv("KETSA_EMAIL_DELIVERY", "log")

    def _boom(*_a, **_k):  # pragma: no cover — must never run
        raise AssertionError("log mode must not touch the network")

    monkeypatch.setattr(mailer.urllib.request, "urlopen", _boom)
    assert mailer.delivery_configured() is False
    assert mailer.send_email("dev@ketsa.io", "test", "<p>hi</p>") is True

    res = _register(client, email="dev@ketsa.io")
    assert res.status_code == 202, res.text


def test_resend_mode_without_a_key_fails_closed(monkeypatch) -> None:
    """`resend` is explicit: a missing key is a hard failure, not a silent log."""
    monkeypatch.delenv("KETSA_RESEND_API_KEY", raising=False)
    monkeypatch.setenv("KETSA_EMAIL_DELIVERY", "resend")
    assert mailer.delivery_configured() is False
    assert mailer.send_email("dev@ketsa.io", "test", "<p>hi</p>") is False


def test_auto_mode_follows_the_key(monkeypatch) -> None:
    """Default `auto`: log without a key, resend with one."""
    monkeypatch.setenv("KETSA_EMAIL_DELIVERY", "auto")
    monkeypatch.delenv("KETSA_RESEND_API_KEY", raising=False)
    assert mailer.email_status()["delivery"] == "log"

    monkeypatch.setenv("KETSA_RESEND_API_KEY", "re_fake_key")
    assert mailer.email_status()["delivery"] == "resend"


def test_email_status_flags_the_sandbox_sender(monkeypatch) -> None:
    """The startup banner relies on this to warn that only the owner inbox works."""
    monkeypatch.setenv("KETSA_RESEND_FROM", "Ketsa <onboarding@resend.dev>")
    monkeypatch.setenv("KETSA_RESEND_API_KEY", "re_fake_key")
    assert mailer.email_status()["sandbox_sender"] is True

    monkeypatch.setenv("KETSA_RESEND_FROM", "Ketsa <no-reply@ketsa.example>")
    assert mailer.email_status()["sandbox_sender"] is False
