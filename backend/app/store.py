"""Read/write helpers over the SQLite database.

The public read API and the protected admin API both funnel through these
functions so there is a single source of truth (the database) and no drift
between what the admin edits and what visitors see.
"""

import json
import sqlite3

from .database import get_conn


# --- Markets ----------------------------------------------------------------

def list_markets() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM markets ORDER BY rowid"
        ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "cat": r["cat"],
            "tag": r["tag"],
            "q": r["q"],
            "yes": r["yes"],
            "no": r["no"],
            "meta": [r["meta0"], r["meta1"]],
            "trend": r["trend"],
            "pts": json.loads(r["pts"]),
        })
    return out


def get_market(market_id: str) -> dict | None:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
    if r is None:
        return None
    return {
        "id": r["id"],
        "cat": r["cat"],
        "tag": r["tag"],
        "q": r["q"],
        "yes": r["yes"],
        "no": r["no"],
        "meta": [r["meta0"], r["meta1"]],
        "trend": r["trend"],
        "pts": json.loads(r["pts"]),
    }


def upsert_market(m: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO markets "
            "(id, cat, tag, q, yes, no, meta0, meta1, trend, pts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                m["id"], m["cat"], m["tag"], m["q"], m["yes"], m["no"],
                m["meta"][0], m["meta"][1], m["trend"], json.dumps(m["pts"]),
            ),
        )


def delete_market(market_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM markets WHERE id = ?", (market_id,))
        return cur.rowcount > 0


# --- Watch ------------------------------------------------------------------

def list_watch() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM watch ORDER BY id").fetchall()
    return [
        {
            "name": r["name"],
            "cat": r["cat"],
            "price": r["price"],
            "pts": json.loads(r["pts"]),
        }
        for r in rows
    ]


def replace_watch(items: list[dict]) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM watch")
        for it in items:
            conn.execute(
                "INSERT INTO watch (name, cat, price, pts) VALUES (?, ?, ?, ?)",
                (it["name"], it["cat"], it["price"], json.dumps(it.get("pts", []))),
            )


# --- Ticker -----------------------------------------------------------------

def list_ticker() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM ticker ORDER BY sort_order, id").fetchall()
    return [{"t": r["t"], "v": r["v"], "d": r["d"]} for r in rows]


def replace_ticker(items: list[dict]) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM ticker")
        for i, it in enumerate(items):
            conn.execute(
                "INSERT INTO ticker (t, v, d, sort_order) VALUES (?, ?, ?, ?)",
                (it["t"], it["v"], it["d"], i),
            )


# --- Dashboard --------------------------------------------------------------

def get_dashboard() -> dict:
    with get_conn() as conn:
        ranges_rows = conn.execute("SELECT * FROM dashboard_ranges").fetchall()
        positions_rows = conn.execute("SELECT * FROM positions ORDER BY id").fetchall()
    ranges = {
        r["range_key"]: {
            "pts": json.loads(r["pts"]),
            "balance": r["balance"],
            "change": r["change"],
        }
        for r in ranges_rows
    }
    positions = [
        {
            "name": r["name"],
            "avg": r["avg"],
            "cur": r["cur"],
            "pts": json.loads(r["pts"]),
        }
        for r in positions_rows
    ]
    return {"ranges": ranges, "positions": positions}


def save_dashboard(data: dict) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM dashboard_ranges")
        for key, series in data.get("ranges", {}).items():
            conn.execute(
                "INSERT INTO dashboard_ranges (range_key, pts, balance, change) "
                "VALUES (?, ?, ?, ?)",
                (key, json.dumps(series["pts"]), series["balance"], series["change"]),
            )
        conn.execute("DELETE FROM positions")
        for p in data.get("positions", []):
            conn.execute(
                "INSERT INTO positions (name, avg, cur, pts) VALUES (?, ?, ?, ?)",
                (p["name"], p["avg"], p["cur"], json.dumps(p["pts"])),
            )


def get_stats() -> dict:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM stats WHERE id = 1").fetchone()
    return {
        "pnl": r["pnl"],
        "open_positions": r["open_positions"],
        "win_rate": r["win_rate"],
    }


def save_stats(s: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE stats SET pnl = ?, open_positions = ?, win_rate = ? WHERE id = 1",
            (s["pnl"], s["open_positions"], s["win_rate"]),
        )


# --- Proof ------------------------------------------------------------------

def get_proof() -> dict:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM proof WHERE id = 1").fetchone()
    return {
        "traders_k": r["traders_k"],
        "live_markets": r["live_markets"],
        "total_volume_m": r["total_volume_m"],
    }


def save_proof(p: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE proof SET traders_k = ?, live_markets = ?, total_volume_m = ? "
            "WHERE id = 1",
            (p["traders_k"], p["live_markets"], p["total_volume_m"]),
        )
