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

import html
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

# Announcement/broadcast template. The admin-authored subject and body are
# injected as TEXT, not markup: every value goes through html.escape() so an
# admin (or anyone who has phished the admin password) cannot smuggle <script>,
# tracking beacons or a spoofed "Ketsa Security" header into other people's
# inboxes. Plain text in an HTML email is the safe default for operator-authored
# copy that is not written as HTML.
_BROADCAST_TEMPLATE = """\
<!doctype html>
<html>
  <body style="margin:0;padding:24px;background:#f4f2ec;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
    <div style="max-width:520px;margin:0 auto;background:#ffffff;border:1px solid #e6e2d8;border-radius:12px;padding:28px">
      <div style="font-size:20px;font-weight:700;color:#101926">Ketsa</div>
      <h1 style="font-size:19px;font-weight:700;color:#101926;line-height:1.35;margin:18px 0 0">{subject}</h1>
      <div style="font-size:14px;color:#46536b;line-height:1.65;white-space:pre-wrap;margin-top:14px">{body}</div>
      <p style="font-size:12px;color:#7a8294;line-height:1.5;margin-top:24px;border-top:1px solid #e6e2d8;padding-top:14px">
        You are receiving this because you have a Ketsa account.
        Trading involves risk. Markets resolve based on published rules.</p>
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

    Returns True when the message reached its destination: handed to Resend in
    a configured deployment, or written to the log in dev/offline mode (no API
    key), which is exactly where that mode is documented to deliver. Returns
    False only when delivery genuinely failed — Resend rejected the request or
    the transport errored.

    Callers that owe the user an honest answer ("check your inbox") must act on
    False; treating it as success ships a dead-end flow where the UI promises
    an email that was never sent.
    """
    key = _api_key()
    if key is None:
        log.warning(
            "KETSA_RESEND_API_KEY not set — email to %s delivered to log only: %s",
            to,
            subject,
        )
        log.info("Email body for %s: %s", to, html)
        return True

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
    """Send a one-time passcode email for signup, password reset or login.

    ``purpose`` selects the wording. The 6-digit code itself is the only
    variable; it is never cached or retried here, because a code that is
    re-sent after a transport failure is a code the attacker may also receive.
    """
    if purpose == "signup":
        subject = "Your Ketsa verification code"
        lead = "Enter this code to activate your Ketsa account."
        greeting = f", {name}" if name else ""
    elif purpose == "login":
        subject = "Your Ketsa sign-in code"
        lead = "Enter this code to sign in to your Ketsa account."
        greeting = f", {name}" if name else ""
    elif purpose == "reset":
        subject = "Your Ketsa password reset code"
        lead = "Enter this code to set a new password for your Ketsa account."
        greeting = ""
    else:
        raise ValueError(f"unknown OTP purpose: {purpose!r}")
    body_html = _OTP_TEMPLATE.format(
        name=greeting, lead=lead, code=code, ttl=max(1, ttl_minutes)
    )
    return send_email(to, subject, body_html)


def send_broadcast_email(to: str, subject: str, body: str) -> bool:
    """Send one admin-authored announcement to a single recipient.

    Always called once per recipient — recipients are never placed together in
    a single ``to``/``bcc`` header, because that discloses the whole user list
    to every recipient and to any mail relay in between (CWE-200).
    """
    clean_subject = " ".join(str(subject or "").split())[:200]
    body_html = _BROADCAST_TEMPLATE.format(
        subject=html.escape(clean_subject, quote=True),
        body=html.escape(str(body or ""), quote=True),
    )
    return send_email(to, clean_subject or "A message from Ketsa", body_html)