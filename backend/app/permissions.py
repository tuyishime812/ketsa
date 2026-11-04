"""Role → capability mapping for the admin panel.

The admin gate used to be a single shared password, so every caller was
implicitly a super-user. Per-staff accounts change that: a support agent and
the owner now reach the same routes, and the server — not the UI — must decide
what each may do.

Design notes
------------
* **Deny by default.** A route declares the capability it needs; a role only
  gets what is listed here. A role that is not in the table (the role allowlist
  is admin-configurable, so custom roles exist) falls back to the read-only
  *support* baseline rather than failing open.
* **The master password is still a break-glass super-user.** Sessions created
  from ``KETSA_ADMIN_PASSWORD`` are treated as ``owner`` and hold every
  capability, so losing staff credentials can never lock the operator out.
* **Writes are deliberately narrower than reads.** Viewing users/markets is
  low risk; deleting users, changing withdrawal limits, resolving markets
  (which settles real money) and broadcasting to every inbox are not.
"""

from __future__ import annotations

from typing import FrozenSet

# Every capability the admin API understands. Keep this list explicit so a
# typo in a route dependency fails loudly (an unknown capability grants
# nothing) instead of silently opening a gate.
CONTENT_READ = "content:read"
CONTENT_WRITE = "content:write"
MARKETS_READ = "markets:read"
MARKETS_WRITE = "markets:write"
MARKETS_RESOLVE = "markets:resolve"
USERS_READ = "users:read"
USERS_WRITE = "users:write"
STAFF_READ = "staff:read"
STAFF_WRITE = "staff:write"
CONFIG_READ = "config:read"
CONFIG_WRITE = "config:write"
AUDIT_READ = "audit:read"
BROADCAST_WRITE = "broadcast:write"

ALL_CAPABILITIES: FrozenSet[str] = frozenset(
    {
        CONTENT_READ,
        CONTENT_WRITE,
        MARKETS_READ,
        MARKETS_WRITE,
        MARKETS_RESOLVE,
        USERS_READ,
        USERS_WRITE,
        STAFF_READ,
        STAFF_WRITE,
        CONFIG_READ,
        CONFIG_WRITE,
        AUDIT_READ,
        BROADCAST_WRITE,
    }
)

# Read-only baseline. Also the fallback for custom roles that are not listed
# below: they can look at the dashboard but cannot change anything.
_SUPPORT = frozenset(
    {
        CONTENT_READ,
        MARKETS_READ,
        USERS_READ,
    }
)

ROLE_CAPABILITIES: dict[str, FrozenSet[str]] = {
    # Break-glass / account owner. Full control.
    "owner": ALL_CAPABILITIES,
    # Day-to-day administrator. Everything except the security configuration
    # (login lockout, role allowlist) and the shared master password, which are
    # owner-only so a compromised admin session cannot weaken its own guard.
    "admin": frozenset(ALL_CAPABILITIES - {CONFIG_WRITE}),
    # Front-line support: look up users and read site/market data.
    "support": _SUPPORT,
    # Money operations: read users and resolve markets (settlement), but no
    # account deletion or content editing.
    "finance": frozenset(
        {
            CONTENT_READ,
            MARKETS_READ,
            MARKETS_RESOLVE,
            USERS_READ,
        }
    ),
    # Content/marketing: edit site copy and markets content, read-only users.
    "marketing": frozenset(
        {
            CONTENT_READ,
            CONTENT_WRITE,
            MARKETS_READ,
        }
    ),
    # Community moderation: read-only visibility.
    "moderation": _SUPPORT,
}

# The safe fallback for any role not in the table above.
DEFAULT_CAPABILITIES: FrozenSet[str] = _SUPPORT


def capabilities_for_role(role: str | None) -> FrozenSet[str]:
    """Capabilities granted to ``role`` (case/space tolerant, deny by default)."""
    slug = (role or "").strip().lower()
    return ROLE_CAPABILITIES.get(slug, DEFAULT_CAPABILITIES)


def is_allowed(role: str | None, capability: str) -> bool:
    """True when ``role`` may exercise ``capability``.

    Unknown capability names are denied: a route that asks for a typo must not
    become an accidental open gate.
    """
    if capability not in ALL_CAPABILITIES:
        return False
    return capability in capabilities_for_role(role)
