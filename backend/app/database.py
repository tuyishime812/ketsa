"""SQLite persistence layer for the Ketsa admin backend.

All public read endpoints read from this database so changes made through the
admin panel take effect immediately. On first run the database is seeded from
the static `data.py` module so behaviour matches the original read-only build.
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from . import data as seed

# Database lives next to the backend package by default. Override via
# KETSA_DB_PATH (e.g. an absolute path or a volume-mounted path in Docker).
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ketsa.db"
)

_lock = threading.Lock()


def db_path() -> str:
    return os.getenv("KETSA_DB_PATH", DEFAULT_DB_PATH)


SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    id TEXT PRIMARY KEY,
    cat TEXT NOT NULL,
    tag TEXT NOT NULL,
    q TEXT NOT NULL,
    yes INTEGER NOT NULL,
    no INTEGER NOT NULL,
    meta0 TEXT NOT NULL,
    meta1 TEXT NOT NULL,
    trend TEXT NOT NULL,
    pts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watch (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    cat TEXT NOT NULL,
    price INTEGER NOT NULL,
    pts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticker (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    t TEXT NOT NULL,
    v TEXT NOT NULL,
    d TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dashboard_ranges (
    range_key TEXT PRIMARY KEY,
    pts TEXT NOT NULL,
    balance INTEGER NOT NULL,
    change REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    avg INTEGER NOT NULL,
    cur INTEGER NOT NULL,
    pts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stats (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    pnl INTEGER NOT NULL,
    open_positions INTEGER NOT NULL,
    win_rate INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS proof (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    traders_k INTEGER NOT NULL,
    live_markets INTEGER NOT NULL,
    total_volume_m REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _seed(conn: sqlite3.Connection) -> None:
    for m in seed.MARKETS:
        conn.execute(
            "INSERT OR REPLACE INTO markets "
            "(id, cat, tag, q, yes, no, meta0, meta1, trend, pts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (m.id, m.cat, m.tag, m.q, m.yes, m.no, m.meta[0], m.meta[1], m.trend,
             json.dumps(m.pts)),
        )

    for w in seed.WATCH:
        conn.execute(
            "INSERT OR IGNORE INTO watch (name, cat, price, pts) VALUES (?, ?, ?, ?)",
            (w.name, w.cat, w.price, json.dumps(w.pts)),
        )

    for i, t in enumerate(seed.TICKER):
        conn.execute(
            "INSERT OR IGNORE INTO ticker (t, v, d, sort_order) VALUES (?, ?, ?, ?)",
            (t.t, t.v, t.d, i),
        )

    for key, series in seed.DASHBOARD.ranges.items():
        conn.execute(
            "INSERT OR IGNORE INTO dashboard_ranges (range_key, pts, balance, change) "
            "VALUES (?, ?, ?, ?)",
            (key, json.dumps(series.pts), series.balance, series.change),
        )

    for p in seed.DASHBOARD.positions:
        conn.execute(
            "INSERT OR IGNORE INTO positions (name, avg, cur, pts) VALUES (?, ?, ?, ?)",
            (p.name, p.avg, p.cur, json.dumps(p.pts)),
        )

    conn.execute(
        "INSERT OR IGNORE INTO stats (id, pnl, open_positions, win_rate) VALUES (1, ?, ?, ?)",
        (seed.STATS.pnl, seed.STATS.open_positions, seed.STATS.win_rate),
    )

    conn.execute(
        "INSERT OR IGNORE INTO proof (id, traders_k, live_markets, total_volume_m) "
        "VALUES (1, ?, ?, ?)",
        (seed.PROOF.traders_k, seed.PROOF.live_markets, seed.PROOF.total_volume_m),
    )

    _seed_settings(conn)


# Defaults for flexible content (hero, steps, CTA, footer, nav). Stored as
# JSON in the `settings` key/value table. Editing these from the admin panel
# updates the site without touching code.
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
            "No order forms, no fine print. Shares trade between 1¢ and 99¢ based "
            "on what the market believes."
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
                "body": "Shares cost between 1¢ and 99¢. If you\u2019re right, each share resolves to $1. If you\u2019re wrong, it resolves to zero.",
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
        "copyright": "© 2026 Ketsa. All rights reserved.",
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


def _seed_settings(conn: sqlite3.Connection) -> None:
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )


def init_db() -> None:
    with _lock, get_conn() as conn:
        conn.executescript(SCHEMA)
        # Seed only when the database is empty (fresh install), so re-running
        # init (e.g. multiple app instances or test runs) never duplicates data.
        count = conn.execute("SELECT COUNT(*) AS c FROM markets").fetchone()["c"]
        if count == 0:
            _seed(conn)
        else:
            _seed_settings(conn)


def get_setting(key: str) -> Any:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return DEFAULT_SETTINGS.get(key)
        return json.loads(row["value"])


def set_setting(key: str, value: Any) -> None:
    with _lock, get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )


def get_all_settings() -> dict[str, Any]:
    """Return every setting, merging in defaults for keys not yet stored."""
    out: dict[str, Any] = dict(DEFAULT_SETTINGS)
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    for r in rows:
        try:
            out[r["key"]] = json.loads(r["value"])
        except (json.JSONDecodeError, TypeError):
            out[r["key"]] = r["value"]
    return out
