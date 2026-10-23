"""Append-only audit log for privileged and money-moving actions.

Why this exists
---------------
The backend logs almost nothing about *who* did a sensitive thing. Market
resolution pays out real money, an admin can reset any user's password or
delete their account, the payment caps and deposit/withdrawal switches are
editable live, and wallet funds move on every trade and payout. Without a
durable record an operator cannot answer "who resolved this market?", "who
changed the withdrawal limit?", or "did someone pay themselves out?" during a
dispute or an abuse investigation.

Design
------
* **Append-only.** Rows are only ever inserted. There is no update or delete
  path in this module, and `db/schema.sql` grants the anon/publishable role no
  access at all while the service role (used by the backend) can insert and
  read. A `ketsa_audit` row is written *after* the action it describes
  succeeds, so a failed write never masquerades as success.
* **No secrets.** Actors are recorded as a stable id (admin session digest
  prefix, or the acting user/wallet id); reasons and identifiers are recorded
  as given. Tokens, passwords and OTP codes are never recorded.
* **Best-effort.** A logging failure must not fail the privileged action the
  operator just performed (nor roll it back �?" that is worse). Failures are
  logged to the application logger and swallowed.
* **Bounded in memory.** The in-process backend keeps the newest rows only,
  because it is a dev/preview store. Supabase keeps everything.

The action vocabulary is deliberately explicit (`audit_actions`) so the UI and
tests can rely on stable strings rather than grepping free text.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any, Optional

from . import store

logger = logging.getLogger("ketsa.audit")


# --- action vocabulary -------------------------------------------------------

class Actions:
    # Admin / privileged
    ADMIN_LOGIN_OK = "admin.login.ok"
    ADMIN_LOGIN_FAILED = "admin.login.failed"
    ADMIN_LOGIN_LOCKED = "admin.login.locked"
    ADMIN_LOGOUT = "admin.logout"
    ADMIN_PASSWORD_CHANGED = "admin.password.changed"
    ADMIN_CONTENT_RESET = "admin.content.reset"
    ADMIN_CONFIG_CHANGED = "admin.config.changed"

    # User administration
    USER_PASSWORD_RESET = "admin.user.password_reset"
    USER_DELETED = "admin.user.deleted"

    # Staff administration
    STAFF_CREATED = "admin.staff.created"
    STAFF_UPDATED = "admin.staff.updated"
    STAFF_DELETED = "admin.staff.deleted"
    STAFF_BULK_UPLOADED = "admin.staff.uploaded"
    STAFF_INVITED = "admin.staff.invited"

    # Broadcast
    BROADCAST_STARTED = "admin.broadcast.started"

    # Markets / money
    MARKET_CREATED = "admin.market.created"
    MARKET_UPDATED = "admin.market.updated"
    MARKET_DELETED = "admin.market.deleted"
    MARKET_RESOLVED = "admin.market.resolved"

    # Account security (user-facing)
    USER_PASSWORD_CHANGED = "auth.user.password_changed"


# --- recording ---------------------------------------------------------------

def record(
    action: str,
    *,
    actor_type: str,
    actor_id: Optional[str] = None,
    ip: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Optional[dict]:
    """Append one audit row. Returns the row, or None if recording failed.

    Never raises: auditing must not break the action it describes.
    """
    row = {
        "id": "au_" + secrets.token_hex(12),
        "ts": time.time(),
        "action": action,
        "actor_type": actor_type,
        "actor_id": actor_id or "",
        "ip": ip or "",
        "target_type": target_type or "",
        "target_id": target_id or "",
        "metadata": metadata or {},
    }
    try:
        store.append_audit(row)
    except Exception:  # noqa: BLE001 - auditing must never break the caller
        logger.exception("Failed to append audit row for action %s", action)
        return None
    return row


def list_recent(
    *, limit: int = 100, action: Optional[str] = None
) -> list[dict]:
    """Newest-first audit rows, optionally filtered to one action."""
    try:
        rows = store.list_audit(limit=limit, action=action)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to read audit rows")
        return []
    return rows


def count() -> int:
    try:
        return store.count_audit()
    except Exception:  # noqa: BLE001
        return 0
