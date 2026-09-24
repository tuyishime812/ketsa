"""Email delivery via Resend (https://resend.com).

Sends transactional emails (signup verification OTP, password-reset OTP)
through the Resend REST API. The transport is a thin ``urllib`` POST; the
test-suite patches ``send_email`` directly, so no network is ever touched
there.

Dev/offline mode: without ``KETSA_RESEND_API_KEY`` the message is logged
instead of sent, so a local checkout can exercise the full register/verify
and forgot-password flows before a key exists. The OTP visible in the server
log is exactly what the email would have contained — never ship this mode to
production without the key.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"

_OTP_TEMPLATE = """\
<!doctype html>
<html>
  <body style="margin:0;padding:24px;background:#f4f2ec;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
    <div style="max-width:480px;margin:0 auto;background:#ffffff;border:1px solid #e6e2d8;border-radius:12px;padding:28px">
      <div style="font-size:20px;font-weight:700;color:#101926">Ketsa</div>
      <p style="font-size:14px;color:#46536b;line-height:1.6">Hi{name},</p>
      <p style="font-size:14px;color:#46536b;line-height:1.6">{lead}</p>
      <div style="margin:20px 0;text-align:center">
        <span style="display:inline-block;font-family:ui-monospace,SFMono-Regular,monospace;font-size:26px;font-weight:700;letter-spacing:8px;color:#101926;background:#f4f2ec;border-radius:8px;padding:14px 20px">{code}</span>
      </div>
      <p style="font-size:13px;color:#7a8294;line-height:1.5">The code expires in {ttl} minutes and can only be used once.
         If you didn't request this, you can safely ignore this email — your account is not affected.</p>
    </div>
  </body>
</html>
"""


def _api_key() -> str | None:
    key = os.getenv("KETSA_RESEND_API_KEY", "").strip()
    return key or None


def _from_address() -> str:
    # Defaults to Resend's sandbox domain, which only delivers to the account
    # owner's verified inbox. Set KETSA_RESEND_FROM to your verified sending
    # domain once one is configured in Resend.
    return os.getenv("KETSA_RESEND_FROM", "Ketsa <onboarding@resend.dev>")


def send_email(to: str, subject: str, html: str) -> bool:
    """Send one transactional email.

    Returns True when the message was handed to Resend, False in dev/offline
    mode (no API key — the message is logged) or on transport failure.
    """
    key = _api_key()
    if key is None:
        log.warning(
            "KETSA_RESEND_API_KEY not set — email to %s not sent: %s", to, subject
        )
        log.info("Email body for %s: %s", to, html)
        return False

    payload: dict[str, Any] = {
        "from": _from_address(),
        "to": [to],
        "subject": subject,
        "html": html,
    }
    request = urllib.request.Request(
        RESEND_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8", "replace")
            if response.status >= 400:
                log.error("Resend rejected email to %s: %s", to, body)
                return False
    except urllib.error.URLError as exc:  # pragma: no cover — real network
        log.error("Resend send failed for %s: %s", to, exc)
        return False
    return True


def send_otp_email(
    to: str, code: str, purpose: str, ttl_minutes: int, name: str = ""
) -> bool:
    """Send a one-time passcode email for signup or password reset."""
    if purpose == "signup":
        subject = "Your Ketsa verification code"
        lead = "Enter this code to activate your Ketsa account."
        greeting = f", {name}" if name else ""
    else:
        subject = "Your Ketsa password reset code"
        lead = "Enter this code to set a new password for your Ketsa account."
        greeting = ""
    html = _OTP_TEMPLATE.format(
        name=greeting, lead=lead, code=code, ttl=max(1, ttl_minutes)
    )
    return send_email(to, subject, html)