"""Admin-configurable runtime controls.

Distinct from *site content* (hero/footer/…): these are operational knobs —
payment limits and enables, the admin-login lockout, the staff role allowlist,
and market-resolution guards. They are stored under their own ``config:*`` keys
in the shared settings store.

They are deliberately kept OUT of the public settings bundle: ``main.py``'s
``_public_settings`` whitelists only the content sections, so nothing here can
reach ``/api/home`` even by accident.

Every default falls back to the matching environment variable, so the env still
acts as the baseline and an admin override simply layers on top (and survives a
restart through the storage backend). Values are validated here — not in the
route — so the admin API, the payment routes, staff validation and market
resolution all read the same, already-sane values.
"""

from __future__ import annotations

import os
import re
from typing import Any

from . import storage
from .models import STAFF_ROLES

_PREFIX = "config:"

# The sections the admin "Settings" tab can read and write.
SECTIONS = ("payments", "security", "staff_roles", "resolution")


class ConfigError(ValueError):
    """A settings value the server refuses to store (bad type or range)."""


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _default(section: str) -> dict:
    """The baseline for a section, sourced from env where one exists."""
    if section == "payments":
        return {
            "deposits_enabled": True,
            "withdrawals_enabled": True,
            "max_deposit_mwk": _env_float("KETSA_MAX_DEPOSIT_MWK", 1_000_000.0),
            "max_withdrawal_mwk": _env_float("KETSA_MAX_WITHDRAWAL_MWK", 1_000_000.0),
            "daily_withdrawal_limit_mwk": _env_float(
                "KETSA_DAILY_WITHDRAWAL_LIMIT_MWK", 3_000_000.0
            ),
        }
    if section == "security":
        return {
            "admin_max_failures": _env_int("KETSA_ADMIN_MAX_FAILURES", 10),
            "admin_lockout_seconds": _env_int("KETSA_ADMIN_LOCKOUT_SECONDS", 900),
        }
    if section == "staff_roles":
        return {"roles": list(STAFF_ROLES)}
    if section == "resolution":
        return {"resolution_enabled": True, "require_end_date": False}
    raise KeyError(section)


# --- validators -------------------------------------------------------------

_MONEY_MIN = 100.0
_MONEY_MAX = 1_000_000_000.0


def _as_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise ConfigError(f"{field} must be true or false")


def _as_float(value: Any, field: str, *, minimum: float, maximum: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{field} must be a number")
    if n != n or n in (float("inf"), float("-inf")):
        raise ConfigError(f"{field} must be a finite number")
    if not (minimum <= n <= maximum):
        raise ConfigError(f"{field} must be between {minimum:g} and {maximum:g}")
    return float(n)


def _as_int(value: Any, field: str, *, minimum: int, maximum: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{field} must be a whole number")
    if not (minimum <= n <= maximum):
        raise ConfigError(f"{field} must be between {minimum} and {maximum}")
    return n


# A role slug: lowercase, starts with a letter, 2-32 chars, [a-z0-9_-].
_ROLE_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")


def _as_roles(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ConfigError("roles must be a list")
    out: list[str] = []
    for item in value:
        slug = str(item).strip().lower()
        if not slug:
            continue
        if not _ROLE_RE.match(slug):
            raise ConfigError(
                f"invalid role {item!r} — use lowercase letters, digits, '-' or "
                "'_' (2-32 chars)"
            )
        if slug not in out:
            out.append(slug)
    if not out:
        raise ConfigError("at least one role is required")
    if len(out) > 20:
        raise ConfigError("too many roles (max 20)")
    return out


def _normalize(section: str, raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ConfigError("expected an object")
    base = _default(section)

    if section == "staff_roles":
        return {"roles": _as_roles(raw.get("roles", base["roles"]))}

    if section == "payments":
        out = {
            "deposits_enabled": _as_bool(
                raw.get("deposits_enabled", base["deposits_enabled"]),
                "deposits_enabled",
            ),
            "withdrawals_enabled": _as_bool(
                raw.get("withdrawals_enabled", base["withdrawals_enabled"]),
                "withdrawals_enabled",
            ),
            "max_deposit_mwk": _as_float(
                raw.get("max_deposit_mwk", base["max_deposit_mwk"]),
                "max_deposit_mwk",
                minimum=_MONEY_MIN,
                maximum=_MONEY_MAX,
            ),
            "max_withdrawal_mwk": _as_float(
                raw.get("max_withdrawal_mwk", base["max_withdrawal_mwk"]),
                "max_withdrawal_mwk",
                minimum=_MONEY_MIN,
                maximum=_MONEY_MAX,
            ),
            "daily_withdrawal_limit_mwk": _as_float(
                raw.get("daily_withdrawal_limit_mwk", base["daily_withdrawal_limit_mwk"]),
                "daily_withdrawal_limit_mwk",
                minimum=_MONEY_MIN,
                maximum=_MONEY_MAX,
            ),
        }
        if out["daily_withdrawal_limit_mwk"] < out["max_withdrawal_mwk"]:
            raise ConfigError(
                "daily_withdrawal_limit_mwk must be at least max_withdrawal_mwk"
            )
        return out

    if section == "security":
        return {
            "admin_max_failures": _as_int(
                raw.get("admin_max_failures", base["admin_max_failures"]),
                "admin_max_failures",
                minimum=1,
                maximum=1000,
            ),
            "admin_lockout_seconds": _as_int(
                raw.get("admin_lockout_seconds", base["admin_lockout_seconds"]),
                "admin_lockout_seconds",
                minimum=30,
                maximum=86_400,
            ),
        }

    if section == "resolution":
        return {
            "resolution_enabled": _as_bool(
                raw.get("resolution_enabled", base["resolution_enabled"]),
                "resolution_enabled",
            ),
            "require_end_date": _as_bool(
                raw.get("require_end_date", base["require_end_date"]),
                "require_end_date",
            ),
        }

    raise KeyError(section)


# --- read / write -----------------------------------------------------------


def get_config(section: str) -> dict:
    """The effective config for a section: stored override over env default."""
    if section not in SECTIONS:
        raise KeyError(section)
    out = _default(section)
    stored = storage.get_setting(_PREFIX + section)
    if isinstance(stored, dict):
        out.update(stored)
    try:
        return _normalize(section, out)
    except ConfigError:
        # A hand-edited/corrupt stored row must never wedge the app: fall back
        # to the (always valid) default rather than surfacing a 500 downstream.
        return _default(section)


def set_config(section: str, patch: Any) -> dict:
    """Merge a partial patch into the section and persist the validated result."""
    if section not in SECTIONS:
        raise KeyError(section)
    if patch is None:
        patch = {}
    if not isinstance(patch, dict):
        raise ConfigError("expected an object")
    merged = {**get_config(section), **patch}
    value = _normalize(section, merged)
    storage.set_setting(_PREFIX + section, value)
    return value


def all_config() -> dict:
    return {section: get_config(section) for section in SECTIONS}


# Convenience accessors used by the routes.
def payments() -> dict:
    return get_config("payments")


def security() -> dict:
    return get_config("security")


def resolution() -> dict:
    return get_config("resolution")


def staff_roles() -> list[str]:
    return list(get_config("staff_roles")["roles"])
