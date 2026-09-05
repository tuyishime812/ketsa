"""Pluggable storage backend for Ketsa content.

The public read API and the protected admin API funnel through `store.py`,
which delegates to whichever backend is active. Two backends are provided:

  * ``MemoryBackend``  — the default. Seeds from the static ``data.py`` module
    and keeps everything in-process. Used for local dev previews and the test
    suite (no external services required).
  * ``FirestoreBackend`` — reads/writes a Google Cloud Firestore project via
    the Firebase Admin SDK. Used in production so all admin edits persist
    (and survive restarts/redeploys) in a hosted, managed database.

Select the backend with the ``KETSA_DB_BACKEND`` env var:

    KETSA_DB_BACKEND=memory     # default
    KETSA_DB_BACKEND=firestore  # production

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
                    {"label": "Dashboard", "href": "#dashboard"},
                    {"label": "How it works", "href": "#how"},
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
        "kicker": "Order book",
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
    def upsert_payment(self, payment: dict) -> None: ...
    def get_payment(self, payment_id: str) -> dict | None: ...
    def list_payments(self, wallet_id: str | None = None) -> list[dict]: ...


# ---------------------------------------------------------------------------
# Memory backend (default — no external services)
# ---------------------------------------------------------------------------


class MemoryBackend:
    """In-process store seeded from the static data module.

    A naive stand-in for the database so local previews and the test-suite run
    with zero setup. Data is not persisted across restarts; use Firestore for
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
        self._payments: dict[str, dict] = {}
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


# ---------------------------------------------------------------------------
# Firestore backend (production) — uses Firebase Admin SDK
# ---------------------------------------------------------------------------


def _firestore_import():
    try:
        import firebase_admin  # type: ignore
        from firebase_admin import credentials, firestore  # type: ignore
        return firebase_admin, credentials, firestore
    except ImportError as e:  # pragma: no cover - depends on optional dep
        raise RuntimeError(
            "KETSA_DB_BACKEND=firestore requires the 'firebase-admin' package. "
            "Install it with: pip install firebase-admin"
        ) from e


class FirestoreBackend:
    """Persistent storage in Google Cloud Firestore.

    Requires a Firebase service-account credential. Provide it either as the
    path to a service-account JSON via ``GOOGLE_APPLICATION_CREDENTIALS``, or
    the JSON contents via ``FIREBASE_CREDENTIALS_JSON``. The project can be set
    with ``FIREBASE_PROJECT_ID`` (otherwise the default from the credential is
    used).

    Collections: ``markets``, ``watch``, ``ticker``, ``dashboard_ranges``,
    ``positions``, ``stats``, ``proof``, ``settings``.
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
        self._seed_ranges = {key: {"pts": list(s.pts), "balance": s.balance, "change": s.change}
                             for key, s in DASHBOARD.ranges.items()}
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
    def db(self) -> Any:
        if self._client is None:
            self._client = self._connect()
        return self._client

    def _connect(self) -> Any:
        firebase_admin, credentials, firestore = _firestore_import()
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        creds_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
        project = os.getenv("FIREBASE_PROJECT_ID")

        options = {"projectId": project} if project else None
        app = None
        if creds_path:
            app = firebase_admin.initialize_app(
                credentials.Certificate(creds_path), options
            )
        elif creds_json:
            app = firebase_admin.initialize_app(
                credentials.Certificate(creds_json), options
            )
        else:
            # Fall back to Application Default Credentials.
            app = firebase_admin.initialize_app(options)
        return firestore.client(app)

    def init(self) -> None:
        if self._initialized:
            return
        self._build_seed()
        self._seed_if_empty()
        self._seed_settings()
        self._initialized = True

    def _seed_if_empty(self) -> None:
        for market_id, data in self._seed_markets.items():
            doc = self.db.collection("markets").document(market_id)
            if not doc.get().exists:
                doc.set(data)
        for w in self._seed_watch:
            ref = self.db.collection("watch").document(w["name"])
            if not ref.get().exists:
                ref.set(w)
        for i, t in enumerate(self._seed_ticker):
            ref = self.db.collection("ticker").document(f"{i:03d}")
            if not ref.get().exists:
                ref.set({**t, "order": i})
        for key, series in self._seed_ranges.items():
            ref = self.db.collection("dashboard_ranges").document(key)
            if not ref.get().exists:
                ref.set(series)
        for p in self._seed_positions:
            ref = self.db.collection("positions").document(p["name"])
            if not ref.get().exists:
                ref.set(p)
        for name, data in (
            ("stats", self._seed_stats),
            ("proof", self._seed_proof),
        ):
            ref = self.db.collection(name).document("singleton")
            if not ref.get().exists:
                ref.set(data)

    def _seed_settings(self) -> None:
        for key, value in DEFAULT_SETTINGS.items():
            ref = self.db.collection("settings").document(key)
            if not ref.get().exists:
                ref.set({"value": value})

    # --- markets ---
    def list_markets(self) -> list[dict]:
        self.init()
        snap = self.db.collection("markets").stream()
        return [dict(s.to_dict()) for s in snap]

    def get_market(self, market_id: str) -> dict | None:
        self.init()
        doc = self.db.collection("markets").document(market_id).get()
        return dict(doc.to_dict()) if doc.exists else None

    def upsert_market(self, m: dict) -> None:
        self.init()
        self.db.collection("markets").document(m["id"]).set(m)

    def delete_market(self, market_id: str) -> bool:
        self.init()
        ref = self.db.collection("markets").document(market_id)
        if not ref.get().exists:
            return False
        ref.delete()
        return True

    # --- watch ---
    def list_watch(self) -> list[dict]:
        self.init()
        return [dict(s.to_dict()) for s in self.db.collection("watch").stream()]

    def replace_watch(self, items: list[dict]) -> None:
        self.init()
        for doc in self.db.collection("watch").list_documents():
            doc.delete()
        for it in items:
            self.db.collection("watch").document(it["name"]).set(it)

    # --- ticker ---
    def list_ticker(self) -> list[dict]:
        self.init()
        items = [dict(s.to_dict()) for s in self.db.collection("ticker").stream()]
        items.sort(key=lambda t: t.get("order", 0))
        return items

    def replace_ticker(self, items: list[dict]) -> None:
        self.init()
        for doc in self.db.collection("ticker").list_documents():
            doc.delete()
        for i, it in enumerate(items):
            self.db.collection("ticker").document(f"{i:03d}").set({**it, "order": i})

    # --- dashboard ---
    def get_dashboard(self) -> dict:
        self.init()
        ranges = {
            s.id: dict(s.to_dict())
            for s in self.db.collection("dashboard_ranges").stream()
        }
        positions = [
            dict(s.to_dict()) for s in self.db.collection("positions").stream()
        ]
        return {"ranges": ranges, "positions": positions}

    def save_dashboard(self, data: dict) -> None:
        self.init()
        for doc in self.db.collection("dashboard_ranges").list_documents():
            doc.delete()
        for key, series in data.get("ranges", {}).items():
            self.db.collection("dashboard_ranges").document(key).set(series)
        for doc in self.db.collection("positions").list_documents():
            doc.delete()
        for p in data.get("positions", []):
            self.db.collection("positions").document(p["name"]).set(p)

    # --- stats / proof ---
    def get_stats(self) -> dict:
        self.init()
        return dict(self.db.collection("stats").document("singleton").get().to_dict())

    def save_stats(self, s: dict) -> None:
        self.init()
        self.db.collection("stats").document("singleton").set(s)

    def get_proof(self) -> dict:
        self.init()
        return dict(self.db.collection("proof").document("singleton").get().to_dict())

    def save_proof(self, p: dict) -> None:
        self.init()
        self.db.collection("proof").document("singleton").set(p)

    # --- settings ---
    def get_all_settings(self) -> dict[str, Any]:
        self.init()
        out: dict[str, Any] = dict(DEFAULT_SETTINGS)
        for s in self.db.collection("settings").stream():
            out[s.id] = s.to_dict().get("value")
        return out

    def get_setting(self, key: str) -> Any:
        self.init()
        doc = self.db.collection("settings").document(key).get()
        if not doc.exists:
            return DEFAULT_SETTINGS.get(key)
        return doc.to_dict().get("value")

    def set_setting(self, key: str, value: Any) -> None:
        self.init()
        self.db.collection("settings").document(key).set({"value": value})

    def reset_to_seed(self) -> None:
        # Drop all content collections and re-seed (preserve admin_password).
        keep_password = self.get_setting("admin_password")
        for name in (
            "markets", "watch", "ticker", "dashboard_ranges", "positions",
            "stats", "proof",
        ):
            for doc in self.db.collection(name).list_documents():
                doc.delete()
        self._seed_if_empty()
        # Reset all settings to defaults, then restore admin_password if stored.
        for doc in self.db.collection("settings").list_documents():
            doc.delete()
        self._seed_settings()
        if keep_password is not None:
            self.db.collection("settings").document("admin_password").set(
                {"value": keep_password}
            )

    # --- wallets (persisted — never wiped by content reset) -------------------
    def get_wallet(self, wallet_id: str) -> dict | None:
        self.init()
        doc = self.db.collection("wallets").document(wallet_id).get()
        return dict(doc.to_dict()) if doc.exists else None

    def upsert_wallet(self, wallet: dict) -> None:
        self.init()
        self.db.collection("wallets").document(wallet["id"]).set(wallet)

    def list_wallets(self) -> list[dict]:
        self.init()
        return [dict(s.to_dict()) for s in self.db.collection("wallets").stream()]

    # --- payments ------------------------------------------------------------
    def upsert_payment(self, payment: dict) -> None:
        self.init()
        self.db.collection("payments").document(payment["id"]).set(payment)

    def get_payment(self, payment_id: str) -> dict | None:
        self.init()
        doc = self.db.collection("payments").document(payment_id).get()
        return dict(doc.to_dict()) if doc.exists else None

    def list_payments(self, wallet_id: str | None = None) -> list[dict]:
        self.init()
        query = self.db.collection("payments")
        if wallet_id:
            query = query.where("wallet_id", "==", wallet_id)
        items = [dict(s.to_dict()) for s in query.order_by("created", direction="DESCENDING").stream()]
        return items


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

_backend: StoreBackend | None = None


def select_backend() -> StoreBackend:
    mode = os.getenv("KETSA_DB_BACKEND", "memory").strip().lower()
    if mode == "firestore":
        return FirestoreBackend()
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
