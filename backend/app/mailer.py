"""Email delivery via Resend (https://resend.com).

Sends transactional emails (password-reset OTP, passwordless sign-in OTP,
admin broadcasts) through the Resend REST API. The transport is a thin
``urllib`` POST; the test-suite patches ``send_email`` directly, so no network
is ever touched there.

Dev/offline mode: with ``KETSA_EMAIL_DELIVERY=log`` (or no
``KETSA_RESEND_API_KEY`` under the default ``auto`` mode) the message is logged
instead of sent, so a local checkout can exercise the full forgot-password and
passwordless sign-in flows before a sending domain exists. The OTP visible in
the server log is exactly what the email would have contained — never run this
in production, where the startup banner warns when the transport cannot deliver.
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


def _delivery_mode() -> str:
    """Effective transport, from ``KETSA_EMAIL_DELIVERY``.

    * ``resend`` — always POST to Resend. Missing API key is a hard failure, so
      a misconfigured deployment is loud rather than silently dropping mail.
    * ``log`` — never touch the network; write the message to the server log.
      This is the supported local-dev workflow: the OTP is visible in the
      backend output, so password reset and login codes can be exercised
      end-to-end without a sending domain.
    * ``auto`` (default) — ``resend`` when an API key is configured, else
      ``log``. Keeps a bare checkout working with no setup while still sending
      for real the moment a key appears.
    """
    raw = os.getenv("KETSA_EMAIL_DELIVERY", "auto").strip().lower()
    if raw in ("log", "resend"):
        return raw
    return "resend" if _api_key() else "log"


def delivery_configured() -> bool:
    """True when a sent message is expected to actually leave the building.

    ``log`` mode is a deliberate dev transport, not a misconfiguration, so it
    reports False (nothing is really delivered) even though it lets the OTP
    flow complete locally. ``resend`` mode without an API key is likewise not
    deliverable, so it reports False and ``send_email`` fails closed.
    """
    return _delivery_mode() == "resend" and _api_key() is not None


def email_status() -> dict[str, Any]:
    """Non-secret description of the active transport (for startup logging)."""
    sender = _from_address()
    # Resend's shared sandbox domain: deliverable only to the account owner's
    # own verified inbox, never to arbitrary recipients.
    sandbox = sender.lower().rstrip(">").endswith("@resend.dev")
    return {
        "delivery": _delivery_mode(),
        "from": sender,
        "sandbox_sender": sandbox,
        "api_key_set": _api_key() is not None,
    }


def send_email(to: str, subject: str, html: str) -> bool:
    """Send one transactional email.

    Returns True when the message reached its destination: handed to Resend in
    a configured deployment, or written to the log in dev/offline mode, which
    is exactly where that mode is documented to deliver. Returns False only
    when delivery genuinely failed — Resend rejected the request or the
    transport errored.

    Callers that owe the user an honest answer ("check your inbox") must act on
    False; treating it as success ships a dead-end flow where the UI promises
    an email that was never sent.
    """
    if _delivery_mode() == "log":
        # WARNING, not INFO, on purpose: the app logger has no handler in every
        # launcher, so an INFO body line is silently dropped and the code becomes
        # invisible — defeating the whole point of this dev transport.
        log.warning(
            "email delivery=log — NOT sent. to=%s subject=%s\n%s",
            to,
            subject,
            html,
        )
        return True

    key = _api_key()
    if key is None:
        # Explicit ``resend`` mode with no key: a real misconfiguration. Fail so
        # the caller reports the truth instead of promising an email that can
        # never be sent.
        log.error(
            "KETSA_EMAIL_DELIVERY=resend but KETSA_RESEND_API_KEY is unset — "
            "email to %s not sent",
            to,
        )
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
    if _delivery_mode() == "log":
        # One clean, greppable line so a developer can find the code without
        # parsing the HTML body below.
        log.warning("dev one-time code for %s (%s): %s", to, purpose, code)
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


# Staff invite. The recipient's name and role are interpolated as escaped TEXT:
# a role is already constrained to an allowlist in staff.py, but escaping here
# means even a hand-edited row can never inject markup into the invite.
_STAFF_INVITE_TEMPLATE = """\
<!doctype html>
<html>
  <body style="margin:0;padding:24px;background:#f4f2ec;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
    <div style="max-width:480px;margin:0 auto;background:#ffffff;border:1px solid #e6e2d8;border-radius:12px;padding:28px">
      <div style="font-size:20px;font-weight:700;color:#101926">Ketsa</div>
      <p style="font-size:14px;color:#46536b;line-height:1.6;margin-top:18px">Hi{name},</p>
      <p style="font-size:14px;color:#46536b;line-height:1.6">
        You have been added to the Ketsa team as <strong>{role}</strong>.
        This is a notification that your staff profile was created — no action
        is needed on your part. If you were not expecting this, please let the
        Ketsa team know.</p>
      <p style="font-size:12px;color:#7a8294;line-height:1.5;margin-top:24px;border-top:1px solid #e6e2d8;padding-top:14px">
        Ketsa — prediction markets. Trading involves risk.</p>
    </div>
  </body>
</html>
"""


def send_staff_invite(to: str, name: str = "", role: str = "support") -> bool:
    """Email a newly-added staff member that their profile was created.

    Returns True only when the message actually reached its destination (or was
    written to the log in dev mode) — same contract as ``send_email``, so the
    admin UI can report an honest "invite sent" instead of a silent no-op.
    """
    clean_name = " ".join(str(name or "").split())[:80]
    clean_role = (str(role or "").strip().lower() or "support")[:40]
    greeting = f", {clean_name}" if clean_name else ""
    body_html = _STAFF_INVITE_TEMPLATE.format(
        name=html.escape(greeting, quote=True),
        role=html.escape(clean_role, quote=True),
    )
    if _delivery_mode() == "log":
        log.warning("dev staff invite for %s (role=%s)", to, clean_role)
    return send_email(to, "You've been added to the Ketsa team", body_html)