"""Email delivery (log-only).

External email delivery (Resend) is disabled. Transactional messages
(password-reset OTP, passwordless sign-in OTP, broadcasts, staff invites and
credential links) are written to the server log so flows can be exercised and
tested without a third-party mail provider.

The log transport redacts credential tokens in logged bodies. Treat server logs
as sensitive operational data.
"""

import html
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# Any ``token=...`` query parameter in a logged email body. Group 1 is kept so
# the log still shows *which* link was sent while the secret itself is masked.
_LOG_TOKEN_RE = re.compile(r"(?i)(token=)[^&\s\"'<>]+")


def _redact_tokens_for_log(body: str) -> str:
    """Mask credential query-string tokens in a log-bound email body."""
    return _LOG_TOKEN_RE.sub(r"\1<redacted>", str(body or ""))


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


def delivery_configured() -> bool:
    """True when a sent message is expected to reach a recipient inbox.

    External delivery is disabled, so this always returns False. Messages are
    written to server logs instead (see ``send_email``).
    """
    return False


def email_status() -> dict[str, Any]:
    """Non-secret description of the active transport (for startup/UI logging)."""
    return {
        "delivery": "log",
        "configured": False,
    }


def send_email(to: str, subject: str, html: str) -> bool:
    """Record one transactional email in the server log.

    Returns True when the message was written to the log. External inbox
    delivery is disabled. Callers should use ``delivery_configured()`` to
    report whether a recipient will actually receive mail.
    """
    # WARNING, not INFO, on purpose: the app logger has no handler in every
    # launcher, so an INFO body line is silently dropped and the code becomes
    # invisible — defeating the whole point of this transport.
    #
    # Redact credential tokens before logging. Without this the log transport
    # would write a working set-password link into the server log, which is a
    # durable, widely-readable location (CWE-532). The rest of the body is
    # still logged so local template work remains possible.
    safe_html = _redact_tokens_for_log(html)
    log.warning(
        "email delivery=log — NOT sent. to=%s subject=%s\n%s",
        to,
        subject,
        safe_html,
    )
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
    """Notify a newly-added staff member that their profile was created.

    Returns True when the message was written to the log. External inbox
    delivery is disabled.
    """
    clean_name = " ".join(str(name or "").split())[:80]
    clean_role = (str(role or "").strip().lower() or "support")[:40]
    greeting = f", {clean_name}" if clean_name else ""
    body_html = _STAFF_INVITE_TEMPLATE.format(
        name=html.escape(greeting, quote=True),
        role=html.escape(clean_role, quote=True),
    )
    log.warning("dev staff invite for %s (role=%s)", to, clean_role)
    return send_email(to, "You've been added to the Ketsa team", body_html)


# Staff credential invite / reset. The link carries a single-use, expiring token
# in its URL fragment (see staffauth._invite_link); the recipient's name and role
# are escaped TEXT.
_STAFF_CREDENTIALS_TEMPLATE = """\
<!doctype html>
<html>
  <body style="margin:0;padding:24px;background:#f4f2ec;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
    <div style="max-width:480px;margin:0 auto;background:#ffffff;border:1px solid #e6e2d8;border-radius:12px;padding:28px">
      <div style="font-size:20px;font-weight:700;color:#101926">Ketsa</div>
      <p style="font-size:14px;color:#46536b;line-height:1.6;margin-top:18px">Hi{name},</p>
      <p style="font-size:14px;color:#46536b;line-height:1.6">{lead}</p>
      <div style="margin:22px 0;text-align:center">
        <a href="{link}" style="display:inline-block;background:#101926;color:#ffffff;text-decoration:none;font-size:14px;font-weight:600;border-radius:8px;padding:12px 22px">{button}</a>
      </div>
      <p style="font-size:13px;color:#7a8294;line-height:1.5">This link expires in {ttl} minutes and can only be used once.
         If you were not expecting it, you can safely ignore this email — no password is changed until the link is opened.</p>
      <p style="font-size:12px;color:#7a8294;line-height:1.5;margin-top:24px;border-top:1px solid #e6e2d8;padding-top:14px">
        Ketsa — prediction markets. Never share this link with anyone.</p>
    </div>
  </body>
</html>
"""


def send_staff_credentials_invite(
    to: str,
    link: str,
    name: str = "",
    role: str = "support",
    ttl_minutes: int = 1440,
    reset: bool = False,
) -> bool:
    """Email a single-use link that lets a staff member set their password.

    ``link`` is server-built from ``KETSA_PUBLIC_URL`` plus an unguessable
    token; it is escaped before interpolation.

    Returns True when the message was written to the log. External inbox
    delivery is disabled.
    """
    clean_name = " ".join(str(name or "").split())[:80]
    clean_role = (str(role or "").strip().lower() or "support")[:40]
    greeting = f", {clean_name}" if clean_name else ""
    safe_link = html.escape(str(link or ""), quote=True)
    if reset:
        subject = "Reset your Ketsa admin password"
        lead = (
            "A password reset was requested for your Ketsa admin account "
            f"(<strong>{html.escape(clean_role, quote=True)}</strong>). "
            "Choose a new password with the button below."
        )
        button = "Reset password"
    else:
        subject = "Set your Ketsa admin password"
        lead = (
            "An admin account has been created for you on the Ketsa admin panel "
            f"(<strong>{html.escape(clean_role, quote=True)}</strong>). "
            "Choose a password to finish setting it up."
        )
        button = "Set my password"
    body_html = _STAFF_CREDENTIALS_TEMPLATE.format(
        name=html.escape(greeting, quote=True),
        lead=lead,
        link=safe_link,
        button=button,
        ttl=max(1, int(ttl_minutes)),
    )
    log.warning(
        "dev staff %s link for %s (role=%s): %s (token redacted in body log; "
        "external email delivery is disabled)",
        "reset" if reset else "invite",
        to,
        clean_role,
        str(link or "").split("?", 1)[0].split("#", 1)[0],
    )
    return send_email(to, subject, body_html)
