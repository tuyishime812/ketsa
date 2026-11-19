"""Email delivery policy + account-discovery safety.

Registration no longer sends an OTP (email signups create the account and
wallet immediately), so the only transactional mail left is:

  * ``/forgot-password`` — a reset code, and
  * ``/login/code`` — a passwordless sign-in code.

Both endpoints *only* send when the identifier matched a real account. A
distinct failure status on those paths would therefore answer "does this
address have an account?" — user enumeration (CWE-203). Their uniform 200 is a
security property, not an oversight, and the tests below keep that guarantee
alongside the log-only delivery behavior.
"""

from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app import authstate
from app import mailer


@pytest.fixture(autouse=True)
def _clean_state():
    authstate.reset()
    yield
    authstate.reset()


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


# --- log-only delivery -----------------------------------------------------


def test_email_is_log_only_and_not_inbox_configured(monkeypatch) -> None:
    """External delivery is disabled: messages are logged, not sent to inboxes."""
    # Ensure no Resend-related env influences behavior (feature removed).
    monkeypatch.delenv("KETSA_RESEND_API_KEY", raising=False)
    monkeypatch.delenv("KETSA_EMAIL_DELIVERY", raising=False)

    status = mailer.email_status()
    assert status["delivery"] == "log"
    assert status["configured"] is False
    assert mailer.delivery_configured() is False
    assert mailer.send_email("dev@ketsa.io", "test", "<p>hi</p>") is True


def test_log_transport_never_touches_network(monkeypatch) -> None:
    """Log-only mode must never make outbound HTTP calls."""
    import urllib.request

    def _boom(*_a, **_k):  # pragma: no cover — must never run
        raise AssertionError("log-only mailer must not touch the network")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    assert mailer.send_email("dev@ketsa.io", "test", "<p>hi</p>") is True
    assert mailer.send_otp_email("dev@ketsa.io", "123456", "login", 10) is True
