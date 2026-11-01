"""Email delivery policy + account-discovery safety.

Registration no longer sends an OTP (email signups create the account and
wallet immediately), so the only transactional mail left is:

  * ``/forgot-password`` — a reset code, and
  * ``/login/code`` — a passwordless sign-in code.

Both endpoints *only* send when the identifier matched a real account. A
distinct failure status on those paths would therefore answer "does this
address have an account?" — user enumeration (CWE-203). Their uniform 200 is a
security property, not an oversight, and the tests below keep that guarantee
alongside the transport-mode matrix.
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


# --- dev mode keeps working ------------------------------------------------


def test_dev_mode_without_a_key_still_delivers_to_the_log(monkeypatch) -> None:
    """No API key means "logged, not sent" — that must count as delivered.

    Dev mode is the documented local workflow (the reset/sign-in code is
    printed to the backend log), so a fresh checkout must not fail closed.
    """
    monkeypatch.delenv("KETSA_RESEND_API_KEY", raising=False)
    assert mailer._api_key() is None
    assert mailer.send_email("dev@ketsa.io", "test", "<p>hi</p>") is True


# --- explicit KETSA_EMAIL_DELIVERY switch ----------------------------------


def test_log_mode_skips_the_network_even_with_a_key(monkeypatch) -> None:
    """`log` is the local-dev transport: a configured key must NOT be used."""
    monkeypatch.setenv("KETSA_RESEND_API_KEY", "re_fake_key")
    monkeypatch.setenv("KETSA_EMAIL_DELIVERY", "log")

    def _boom(*_a, **_k):  # pragma: no cover — must never run
        raise AssertionError("log mode must not touch the network")

    monkeypatch.setattr(mailer.urllib.request, "urlopen", _boom)
    assert mailer.delivery_configured() is False
    assert mailer.send_email("dev@ketsa.io", "test", "<p>hi</p>") is True


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
