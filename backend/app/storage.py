"""Pluggable storage backend for Ketsa content.

The public read API and the protected admin API funnel through `store.py`,
which delegates to whichever backend is active. Two backends are provided:

  * ``MemoryBackend``   — the default. Seeds from the static ``data.py`` module
    and keeps everything in-process. Used for local dev previews and the test
    suite (no external services required).
  * ``SupabaseBackend`` — reads/writes a Supabase Postgres database via the
    Supabase REST API (PostgREST). Used in production so all admin edits
    (and funded wallet balances + the payment ledger) persist across
    restarts/redeploys in a hosted, managed database.

Select the backend with the ``KETSA_DB_BACKEND`` env var:

    KETSA_DB_BACKEND=memory     # default
    KETSA_DB_BACKEND=supabase   # production

Both backends expose the same operations and seed from the same source data,
so switching is transparent to the rest of the app.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any, Protocol

from . import data as seed
from .data import (
    CATEGORIES,
    DASHBOARD,
    MARKETS,
    PROOF,
    STATS,
    TICKER,
    WATCH,
)

# ---------------------------------------------------------------------------
# Shared seed / defaults
# ---------------------------------------------------------------------------

# Defaults for flexible content (hero, steps, CTA, footer, nav). Stored per-key
# in the `settings` collection. Editing these from the admin panel updates the
# site without touching code.
DEFAULT_SETTINGS: dict[str, Any] = {
    "hero": {
        "headline_1": "Trade on ",
        "headline_accent": "what happens next.",
        "description": (
            "Ketsa is a real-time market for the outcomes that matter — politics, "
            "crypto, sport, and culture. Prices move with the crowd, not a "
            "bookmaker, and you can exit the instant the odds turn your way."
        ),
        "badge": "$97.4M traded this week",
    },
    "cta": {
        "title": "Markets are opinions with a price.",
        "description": (
            "Put a number on what you believe. Ketsa turns your read on the world "
            "into a position you can trade."
        ),
        "button": "Create an account",
    },
    "steps": {
        "kicker": "Mechanics",
        "title": "Three steps, one price",
        "description": (
            "No order forms, no fine print. Shares trade between 1\u00a2 and 99\u00a2 "
            "based on what the market believes."
        ),
        "items": [
            {
                "num": "01",
                "title": "Pick a market",
                "body": "Browse thousands of questions on politics, crypto, sport, and culture — each priced by real trading, not a bookmaker\u2019s line.",
            },
            {
                "num": "02",
                "title": "Buy Yes or No",
                "body": "Shares cost between 1\u00a2 and 99\u00a2. If you\u2019re right, each share resolves to $1. If you\u2019re wrong, it resolves to zero.",
            },
            {
                "num": "03",
                "title": "Cash out anytime",
                "body": "Sell your position the moment the odds move your way — you don\u2019t have to wait for the market to resolve.",
            },
        ],
    },
    "footer": {
        "tagline": (
            "A real-time market for the questions everyone's arguing about. "
            "Trade the odds, not the opinions."
        ),
        "columns": [
            {
                "title": "Product",
                "links": [
                    {"label": "Markets", "href": "#markets"},
                    {"label": "Portfolio", "href": "/portfolio"},
                    {"label": "All markets", "href": "/markets"},
                    {"label": "Pricing", "href": "#top"},
                ],
            },
            {
                "title": "Company",
                "links": [
                    {"label": "About", "href": "#top"},
                    {"label": "Careers", "href": "#top"},
                    {"label": "Blog", "href": "#top"},
                    {"label": "Contact", "href": "#top"},
                ],
            },
            {
                "title": "Resources",
                "links": [
                    {"label": "Docs", "href": "#top"},
                    {"label": "API", "href": "#top"},
                    {"label": "Status", "href": "#top"},
                    {"label": "Support", "href": "#top"},
                ],
            },
        ],
        "copyright": "\u00a9 2026 Ketsa. All rights reserved.",
        "disclaimer": "Trading involves risk. Markets resolve based on published rules.",
    },
    "markets_section": {
        "kicker": "Live",
        "title": "Markets moving right now",
        "description": (
            "Every price is a probability. Buy the side you believe, sell whenever "
            "the market catches up to you."
        ),
    },
    "dashboard_section": {
        "kicker": "Dashboard",
        "title": "Your positions, priced live",
        "description": (
            "Track performance across every market you're in, updated in real time "
            "as odds move."
        ),
    },
}


def _market_dict(m) -> dict:
    return {
        "id": m.id,
        "cat": m.cat,
        "tag": m.tag,
        "q": m.q,
        "yes": m.yes,
        "no": m.no,
        "meta": list(m.meta),
        "trend": m.trend,
        "pts": list(m.pts),
        "description": m.description,
        "end_date": m.end_date,
        "created": m.created,
        "volume": m.volume,
        "liquidity": m.liquidity,
        "status": m.status,
        "resolved_outcome": getattr(m, "resolved_outcome", None),
        "resolved_price": getattr(m, "resolved_price", None),
        "resolved_ts": getattr(m, "resolved_ts", None),
    }


def _watch_dict(w) -> dict:
    return {"name": w.name, "cat": w.cat, "price": w.price, "pts": list(w.pts)}


def _ticker_dict(t) -> dict:
    return {"t": t.t, "v": t.v, "d": t.d}


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------


class StoreBackend(Protocol):
    def init(self) -> None: ...
    def list_markets(self) -> list[dict]: ...
    def get_market(self, market_id: str) -> dict | None: ...
    def upsert_market(self, m: dict) -> None: ...
    def delete_market(self, market_id: str) -> bool: ...
    def list_watch(self) -> list[dict]: ...
    def replace_watch(self, items: list[dict]) -> None: ...
    def list_ticker(self) -> list[dict]: ...
    def replace_ticker(self, items: list[dict]) -> None: ...
    def get_dashboard(self) -> dict: ...
    def save_dashboard(self, data: dict) -> None: ...
    def get_stats(self) -> dict: ...
    def save_stats(self, s: dict) -> None: ...
    def get_proof(self) -> dict: ...
    def save_proof(self, p: dict) -> None: ...
    def get_all_settings(self) -> dict[str, Any]: ...
    def get_setting(self, key: str) -> Any: ...
    def set_setting(self, key: str, value: Any) -> None: ...
    def reset_to_seed(self) -> None: ...
    def get_wallet(self, wallet_id: str) -> dict | None: ...
    def upsert_wallet(self, wallet: dict) -> None: ...
    def list_wallets(self) -> list[dict]: ...
    def get_user(self, user_id: str) -> dict | None: ...
    def get_user_by_email(self, email: str) -> dict | None: ...
    def get_user_by_auth0_sub(self, sub: str) -> dict | None: ...
    def upsert_user(self, user: dict) -> None: ...
    def list_users(self) -> list[dict]: ...
    def delete_user(self, user_id: str) -> bool: ...
    def upsert_payment(self, payment: dict) -> None: ...
    def get_payment(self, payment_id: str) -> dict | None: ...
    def list_payments(self, wallet_id: str | None = None) -> list[dict]: ...
    def upsert_notification(self, notification: dict) -> None: ...
    def list_notifications(self, wallet_id: str | None = None, limit: int = 50) -> list[dict]: ...
    def mark_notifications_read(self, wallet_id: str, ids: list[str] | None = None) -> int: ...


# ---------------------------------------------------------------------------
# Memory backend (default — no external services)
# ---------------------------------------------------------------------------


class MemoryBackend:
    """In-process store seeded from the static data module.

    A naive stand-in for the database so local previews and the test-suite run
    with zero setup. Data is not persisted across restarts; use Supabase for
    production.
    """

    def __init__(self) -> None:
        self._markets: dict[str, dict] = {}
        self._watch: list[dict] = []
        self._ticker: list[dict] = []
        self._ranges: dict[str, dict] = {}
        self._positions: list[dict] = []
        self._stats: dict = {}
        self._proof: dict = {}
        self._settings: dict[str, Any] = json.loads(json.dumps(DEFAULT_SETTINGS))
        self._wallets: dict[str, dict] = {}
        self._users: dict[str, dict] = {}
        self._payments: dict[str, dict] = {}
        self._notifications: dict[str, dict] = {}
        self._initialized = False

    def init(self) -> None:
        if self._initialized:
            return
        for m in MARKETS:
            self._markets[m.id] = _market_dict(m)
        self._watch = [_watch_dict(w) for w in WATCH]
        self._ticker = [_ticker_dict(t) for t in TICKER]
        self._ranges = {key: {"pts": list(s.pts), "balance": s.balance, "change": s.change}
                        for key, s in DASHBOARD.ranges.items()}
        self._positions = [
            {"name": p.name, "avg": p.avg, "cur": p.cur, "pts": list(p.pts)}
            for p in DASHBOARD.positions
        ]
        self._stats = {
            "pnl": STATS.pnl,
            "open_positions": STATS.open_positions,
            "win_rate": STATS.win_rate,
        }
        self._proof = {
            "traders_k": PROOF.traders_k,
            "live_markets": PROOF.live_markets,
            "total_volume_m": PROOF.total_volume_m,
        }
        self._initialized = True

    def force_reseed(self) -> None:
        """Drop everything and re-seed (admin "reset content")."""
        keep_password = self._settings.get("admin_password")
        self._markets.clear()
        self._watch.clear()
        self._ticker.clear()
        self._ranges.clear()
        self._positions.clear()
        self._stats.clear()
        self._proof.clear()
        self._settings = json.loads(json.dumps(DEFAULT_SETTINGS))
        if keep_password is not None:
            self._settings["admin_password"] = keep_password
        self._initialized = False
        self.init()

    # --- markets ---
    def list_markets(self) -> list[dict]:
        self.init()
        return list(self._markets.values())

    def get_market(self, market_id: str) -> dict | None:
        self.init()
        return self._markets.get(market_id)

    def upsert_market(self, m: dict) -> None:
        self.init()
        self._markets[m["id"]] = m

    def delete_market(self, market_id: str) -> bool:
        self.init()
        return self._markets.pop(market_id, None) is not None

    # --- watch ---
    def list_watch(self) -> list[dict]:
        self.init()
        return list(self._watch)

    def replace_watch(self, items: list[dict]) -> None:
        self.init()
        self._watch = [dict(it) for it in items]

    # --- ticker ---
    def list_ticker(self) -> list[dict]:
        self.init()
        return list(self._ticker)

    def replace_ticker(self, items: list[dict]) -> None:
        self.init()
        self._ticker = [dict(it) for it in items]

    # --- dashboard ---
    def get_dashboard(self) -> dict:
        self.init()
        return {"ranges": dict(self._ranges), "positions": list(self._positions)}

    def save_dashboard(self, data: dict) -> None:
        self.init()
        self._ranges = {k: dict(v) for k, v in data.get("ranges", {}).items()}
        self._positions = [dict(p) for p in data.get("positions", [])]

    # --- stats / proof ---
    def get_stats(self) -> dict:
        self.init()
        return dict(self._stats)

    def save_stats(self, s: dict) -> None:
        self.init()
        self._stats = dict(s)

    def get_proof(self) -> dict:
        self.init()
        return dict(self._proof)

    def save_proof(self, p: dict) -> None:
        self.init()
        self._proof = dict(p)

    # --- settings ---
    def get_all_settings(self) -> dict[str, Any]:
        self.init()
        out: dict[str, Any] = dict(DEFAULT_SETTINGS)
        out.update(self._settings)
        return out

    def get_setting(self, key: str) -> Any:
        self.init()
        return self._settings.get(key)

    def set_setting(self, key: str, value: Any) -> None:
        self.init()
        self._settings[key] = value

    def reset_to_seed(self) -> None:
        self.force_reseed()

    # --- wallets (persisted outside reset) -----------------------------------
    def get_wallet(self, wallet_id: str) -> dict | None:
        self.init()
        w = self._wallets.get(wallet_id)
        return copy.deepcopy(w) if w else None

    def upsert_wallet(self, wallet: dict) -> None:
        self.init()
        self._wallets[wallet["id"]] = copy.deepcopy(wallet)

    def list_wallets(self) -> list[dict]:
        self.init()
        return [copy.deepcopy(w) for w in self._wallets.values()]

    # --- users ---------------------------------------------------------------
    def get_user(self, user_id: str) -> dict | None:
        self.init()
        u = self._users.get(user_id)
        return copy.deepcopy(u) if u else None

    def get_user_by_email(self, email: str) -> dict | None:
        self.init()
        for u in self._users.values():
            if u.get("email", "").lower() == (email or "").lower():
                return copy.deepcopy(u)
        return None

    def get_user_by_auth0_sub(self, sub: str) -> dict | None:
        self.init()
        if not sub:
            return None
        for u in self._users.values():
            if u.get("auth0_sub") == sub:
                return copy.deepcopy(u)
        return None

    def upsert_user(self, user: dict) -> None:
        self.init()
        self._users[user["id"]] = copy.deepcopy(user)

    def list_users(self) -> list[dict]:
        self.init()
        return [copy.deepcopy(u) for u in self._users.values()]

    def delete_user(self, user_id: str) -> bool:
        self.init()
        return self._users.pop(user_id, None) is not None

    # --- payments -------------------------------------------------------------
    def upsert_payment(self, payment: dict) -> None:
        self.init()
        self._payments[payment["id"]] = dict(payment)

    def get_payment(self, payment_id: str) -> dict | None:
        self.init()
        p = self._payments.get(payment_id)
        return dict(p) if p else None

    def list_payments(self, wallet_id: str | None = None) -> list[dict]:
        self.init()
        items = self._payments.values()
        if wallet_id:
            items = [p for p in items if p.get("wallet_id") == wallet_id]
        return [dict(p) for p in sorted(items, key=lambda p: p.get("created", 0), reverse=True)]

    # --- notifications --------------------------------------------------------
    def upsert_notification(self, notification: dict) -> None:
        self.init()
        self._notifications[notification["id"]] = dict(notification)

    def list_notifications(self, wallet_id: str | None = None, limit: int = 50) -> list[dict]:
        self.init()
        items = self._notifications.values()
        if wallet_id:
            items = [n for n in items if n.get("wallet_id") == wallet_id]
        return [dict(n) for n in sorted(items, key=lambda n: n.get("ts", 0), reverse=True)[:limit]]

    def mark_notifications_read(self, wallet_id: str, ids: list[str] | None = None) -> int:
        self.init()
        marked = 0
        for n in self._notifications.values():
            if n.get("wallet_id") != wallet_id:
                continue
            if ids is not None and n["id"] not in ids:
                continue
            if not n.get("read"):
                n["read"] = True
                marked += 1
        return marked


# ---------------------------------------------------------------------------
# Supabase backend (production) — Postgres via Supabase REST (PostgREST)
# ---------------------------------------------------------------------------

KV_TABLE = "ketsa_kv"
WALLETS_TABLE = "ketsa_wallets"
PAYMENTS_TABLE = "ketsa_payments"
USERS_TABLE = "ketsa_users"
NOTIFICATIONS_TABLE = "ketsa_notifications"


def _supabase_import():
    try:
        from supabase import create_client  # type: ignore
        return create_client
    except ImportError as e:  # pragma: no cover - depends on optional dep
        raise RuntimeError(
            "KETSA_DB_BACKEND=supabase requires the 'supabase' package. "
            "Install it with: pip install supabase"
        ) from e


def _as_json(value: Any) -> Any:
    """Round-trip a value through JSON so only JSON-safe types reach Postgres."""
    return json.loads(json.dumps(value, default=str))


class SupabaseBackend:
    """Persistent storage in a Supabase Postgres database.

    Requires a Supabase project URL and a service-role key: set ``SUPABASE_URL``
    and ``SUPABASE_SERVICE_ROLE_KEY``. The service role bypasses Row Level
    Security, so the key must be kept secret (server-side only).
    """

    def __init__(self) -> None:
        self._client = None
        self._initialized = False
        self._seed_markets: dict[str, dict] = {}
        self._seed_watch: list[dict] = []
        self._seed_ticker: list[dict] = []
        self._seed_ranges: dict[str, dict] = {}
        self._seed_positions: list[dict] = []
        self._seed_stats: dict = {}
        self._seed_proof: dict = {}

    def _build_seed(self) -> None:
        for m in MARKETS:
            self._seed_markets[m.id] = _market_dict(m)
        self._seed_watch = [_watch_dict(w) for w in WATCH]
        self._seed_ticker = [_ticker_dict(t) for t in TICKER]
        self._seed_ranges = {
            key: {"pts": list(s.pts), "balance": s.balance, "change": s.change}
            for key, s in DASHBOARD.ranges.items()
        }
        self._seed_positions = [
            {"name": p.name, "avg": p.avg, "cur": p.cur, "pts": list(p.pts)}
            for p in DASHBOARD.positions
        ]
        self._seed_stats = {
            "pnl": STATS.pnl,
            "open_positions": STATS.open_positions,
            "win_rate": STATS.win_rate,
        }
        self._seed_proof = {
            "traders_k": PROOF.traders_k,
            "live_markets": PROOF.live_markets,
            "total_volume_m": PROOF.total_volume_m,
        }

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._connect()
        return self._client

    def _connect(self) -> Any:
        create_client = _supabase_import()
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise RuntimeError(
                "KETSA_DB_BACKEND=supabase requires SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY to be set"
            )
        return create_client(url, key)

    # --- generic PostgREST helpers ------------------------------------------
    def _get_row(self, table: str, row_id: str) -> dict | None:
        data = self.client.table(table).select("*").eq("id", row_id).limit(1).execute().data
        if not data:
            return None
        return _as_json(data[0].get("value"))

    def _upsert_row(self, table: str, row_id: str, value: Any) -> None:
        self.client.table(table).upsert({"id": row_id, "value": _as_json(value)}).execute()

    def _delete_row(self, table: str, row_id: str) -> None:
        self.client.table(table).delete().eq("id", row_id).execute()

    def _list_rows(self, table: str) -> list[dict]:
        data = self.client.table(table).select("*").execute().data or []
        return [_as_json(r.get("value")) for r in data]

    def _count_kind(self, kind: str) -> int:
        res = self.client.table(KV_TABLE).select("id", count="exact").eq("kind", kind).execute()
        return int(res.count or 0)

    def _list_kind(self, kind: str) -> list[dict]:
        data = self.client.table(KV_TABLE).select("*").eq("kind", kind).execute().data or []
        return [_as_json(r.get("value")) for r in data]

    def _get_kv(self, key: str) -> dict | None:
        return self._get_row(KV_TABLE, key)

    def _upsert_kv(self, key: str, kind: str, value: Any) -> None:
        self.client.table(KV_TABLE).upsert(
            {"id": key, "kind": kind, "value": _as_json(value)}
        ).execute()

    def _delete_kv(self, key: str) -> None:
        self._delete_row(KV_TABLE, key)

    # --- init / seed ---------------------------------------------------------
    def init(self) -> None:
        if self._initialized:
            return
        self._build_seed()
        if self._count_kind("market") == 0:
            for m in self._seed_markets.values():
                self._upsert_kv(m["id"], "market", m)
        if self._get_kv("watch") is None:
            self._upsert_kv("watch", "content", self._seed_watch)
        if self._get_kv("ticker") is None:
            self._upsert_kv("ticker", "content", self._seed_ticker)
        if self._get_kv("dashboard") is None:
            self._upsert_kv(
                "dashboard",
                "content",
                {"ranges": self._seed_ranges, "positions": self._seed_positions},
            )
        if self._get_kv("stats") is None:
            self._upsert_kv("stats", "content", self._seed_stats)
        if self._get_kv("proof") is None:
            self._upsert_kv("proof", "content", self._seed_proof)
        if self._get_kv("settings") is None:
            self._upsert_kv("settings", "content", DEFAULT_SETTINGS)
        self._initialized = True

    # --- markets ---
    def list_markets(self) -> list[dict]:
        self.init()
        return self._list_kind("market")

    def get_market(self, market_id: str) -> dict | None:
        self.init()
        return self._get_kv(market_id)

    def upsert_market(self, m: dict) -> None:
        self.init()
        self._upsert_kv(m["id"], "market", m)

    def delete_market(self, market_id: str) -> bool:
        self.init()
        if self._get_kv(market_id) is None:
            return False
        self._delete_kv(market_id)
        return True

    # --- watch ---
    def list_watch(self) -> list[dict]:
        self.init()
        return list(self._get_kv("watch") or [])

    def replace_watch(self, items: list[dict]) -> None:
        self.init()
        self._upsert_kv("watch", "content", [dict(it) for it in items])

    # --- ticker ---
    def list_ticker(self) -> list[dict]:
        self.init()
        return list(self._get_kv("ticker") or [])

    def replace_ticker(self, items: list[dict]) -> None:
        self.init()
        self._upsert_kv("ticker", "content", [dict(it) for it in items])

    # --- dashboard ---
    def get_dashboard(self) -> dict:
        self.init()
        d = self._get_kv("dashboard") or {}
        return {"ranges": d.get("ranges", {}), "positions": d.get("positions", [])}

    def save_dashboard(self, data: dict) -> None:
        self.init()
        self._upsert_kv(
            "dashboard",
            "content",
            {"ranges": data.get("ranges", {}), "positions": data.get("positions", [])},
        )

    # --- stats / proof ---
    def get_stats(self) -> dict:
        self.init()
        return dict(self._get_kv("stats") or {})

    def save_stats(self, s: dict) -> None:
        self.init()
        self._upsert_kv("stats", "content", s)

    def get_proof(self) -> dict:
        self.init()
        return dict(self._get_kv("proof") or {})

    def save_proof(self, p: dict) -> None:
        self.init()
        self._upsert_kv("proof", "content", p)

    # --- settings ---
    def get_all_settings(self) -> dict[str, Any]:
        self.init()
        out: dict[str, Any] = dict(DEFAULT_SETTINGS)
        stored = self._get_kv("settings") or {}
        out.update({k: v for k, v in stored.items() if v is not None})
        return out

    def get_setting(self, key: str) -> Any:
        self.init()
        stored = self._get_kv("settings") or {}
        if key in stored:
            return stored.get(key)
        return DEFAULT_SETTINGS.get(key)

    def set_setting(self, key: str, value: Any) -> None:
        self.init()
        stored = dict(self._get_kv("settings") or {})
        stored[key] = value
        self._upsert_kv("settings", "content", stored)

    def reset_to_seed(self) -> None:
        # Preserve the admin password across the reset.
        keep_password = self.get_setting("admin_password")
        # Drop all content + market rows; wallets/payments are never touched.
        self.client.table(KV_TABLE).delete().eq("kind", "market").execute()
        for key in ("watch", "ticker", "dashboard", "stats", "proof", "settings"):
            self._delete_kv(key)
        self._initialized = False
        self.init()
        if keep_password is not None:
            self.set_setting("admin_password", keep_password)

    # --- wallets (persisted — never wiped by content reset) -------------------
    def get_wallet(self, wallet_id: str) -> dict | None:
        self.init()
        return self._get_row(WALLETS_TABLE, wallet_id)

    def upsert_wallet(self, wallet: dict) -> None:
        self.init()
        self._upsert_row(WALLETS_TABLE, wallet["id"], wallet)

    def list_wallets(self) -> list[dict]:
        self.init()
        return self._list_rows(WALLETS_TABLE)

    # --- users ---------------------------------------------------------------
    def get_user(self, user_id: str) -> dict | None:
        self.init()
        return self._get_row(USERS_TABLE, user_id)

    def get_user_by_email(self, email: str) -> dict | None:
        self.init()
        if not email:
            return None
        needle = email.lower()
        for u in self._list_rows(USERS_TABLE):
            if (u.get("email") or "").lower() == needle:
                return u
        return None

    def get_user_by_auth0_sub(self, sub: str) -> dict | None:
        self.init()
        if not sub:
            return None
        for u in self._list_rows(USERS_TABLE):
            if u.get("auth0_sub") == sub:
                return u
        return None

    def upsert_user(self, user: dict) -> None:
        self.init()
        self._upsert_row(USERS_TABLE, user["id"], user)

    def list_users(self) -> list[dict]:
        self.init()
        return self._list_rows(USERS_TABLE)

    def delete_user(self, user_id: str) -> bool:
        self.init()
        if self._get_row(USERS_TABLE, user_id) is None:
            return False
        self._delete_row(USERS_TABLE, user_id)
        return True

    # --- payments ------------------------------------------------------------
    def upsert_payment(self, payment: dict) -> None:
        self.init()
        self._upsert_row(PAYMENTS_TABLE, payment["id"], payment)

    def get_payment(self, payment_id: str) -> dict | None:
        self.init()
        return self._get_row(PAYMENTS_TABLE, payment_id)

    def list_payments(self, wallet_id: str | None = None) -> list[dict]:
        self.init()
        items = self._list_rows(PAYMENTS_TABLE)
        if wallet_id:
            items = [p for p in items if p.get("wallet_id") == wallet_id]
        return sorted(items, key=lambda p: p.get("created", 0), reverse=True)

    # --- notifications --------------------------------------------------------
    def upsert_notification(self, notification: dict) -> None:
        self.init()
        self._upsert_row(NOTIFICATIONS_TABLE, notification["id"], notification)

    def list_notifications(self, wallet_id: str | None = None, limit: int = 50) -> list[dict]:
        self.init()
        items = self._list_rows(NOTIFICATIONS_TABLE)
        if wallet_id:
            items = [n for n in items if n.get("wallet_id") == wallet_id]
        return sorted(items, key=lambda n: n.get("ts", 0), reverse=True)[:limit]

    def mark_notifications_read(self, wallet_id: str, ids: list[str] | None = None) -> int:
        self.init()
        marked = 0
        for n in self._list_rows(NOTIFICATIONS_TABLE):
            if n.get("wallet_id") != wallet_id:
                continue
            if ids is not None and n.get("id") not in ids:
                continue
            if not n.get("read"):
                n["read"] = True
                self._upsert_row(NOTIFICATIONS_TABLE, n["id"], n)
                marked += 1
        return marked

# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

_backend: StoreBackend | None = None


def select_backend() -> StoreBackend:
    mode = os.getenv("KETSA_DB_BACKEND", "memory").strip().lower()
    if mode == "supabase":
        return SupabaseBackend()
    if mode in ("memory", "sqlite", ""):
        return MemoryBackend()
    raise ValueError(f"Unknown KETSA_DB_BACKEND: {mode!r}")


def get_backend() -> StoreBackend:
    global _backend
    if _backend is None:
        _backend = select_backend()
    return _backend


def reset_backend() -> None:
    """Drop the cached backend so the next access rebuilds it (test isolation)."""
    global _backend
    _backend = None


def init_db() -> None:
    """Initialise and seed the active backend."""
    get_backend().init()


def reset_db() -> None:
    """Re-seed the active backend to original content (admin reset)."""
    get_backend().reset_to_seed()


# Facade re-exports used by main.py / admin.py
def get_all_settings() -> dict[str, Any]:
    return get_backend().get_all_settings()


def get_setting(key: str) -> Any:
    return get_backend().get_setting(key)


def set_setting(key: str, value: Any) -> None:
    get_backend().set_setting(key, value)
