"""Database row locking for wallet mutations (the multi-process fix).

Why this exists
---------------
The matching engine serializes balance mutations with an ``asyncio.Lock``
inside one process. That is invisible to a second process/replica, so two
workers can each read the same persisted balance, each spend it, and both
write — double-spending real money. ``replica.py`` refuses to *start* such a
configuration until this module is active.

What this does
--------------
When a Postgres connection string is configured (``KETSA_DB_URL``), wallet
mutations run inside a real database transaction that takes a row lock::

    BEGIN;
    SELECT value FROM ketsa_wallets WHERE id = %s FOR UPDATE;
    -- caller mutates the dict in place
    UPDATE ketsa_wallets SET value = %s WHERE id = %s;
    COMMIT;

``SELECT ... FOR UPDATE`` now serializes writers **across every process**,
because the lock lives in Postgres, not in one worker's event loop. Two workers
that touch the same wallet are queued by the database; different wallets do not
block each other.

Opt-in by design
----------------
Without ``KETSA_DB_URL`` (local dev, the test suite, and any deployment that
still runs a single process) the module reports ``configured() == False`` and
the engine keeps its in-memory path. Supabase's PostgREST API cannot run a
multi-statement interactive transaction, which is precisely why this path uses
a direct ``psycopg`` connection instead of the REST client.

``psycopg`` is an optional dependency: it is imported lazily so the backend
still runs (single-process) when it is not installed. Install it from
``requirements.txt`` (the ``psycopg[binary]`` extra) to enable this path.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger("ketsa.dblock")

WALLETS_TABLE = "ketsa_wallets"


def db_url() -> str | None:
    """The Postgres connection string, or None when row locking is disabled."""
    raw = os.getenv("KETSA_DB_URL", "").strip()
    return raw or None


def configured() -> bool:
    """True when a DB URL is set *and* a psycopg driver is importable.

    A URL without a driver is a misconfiguration, not a silent downgrade: we
    log once and report False so the replica guard still protects the process.
    """
    if db_url() is None:
        return False
    if _load_driver() is None:
        logger.error(
            "KETSA_DB_URL is set but no psycopg driver is installed — wallet row "
            "locking is OFF. Install 'psycopg[binary]' (see requirements.txt) or "
            "unset KETSA_DB_URL. Running multi-process now risks double-spend."
        )
        return False
    return True


# --- lazy driver loading -----------------------------------------------------

_driver = None
_driver_loaded = False
_driver_lock = threading.Lock()


def _load_driver():
    """Import psycopg (3) or psycopg2, once. None when neither is available."""
    global _driver, _driver_loaded
    if _driver_loaded:
        return _driver
    with _driver_lock:
        if _driver_loaded:
            return _driver
        try:
            import psycopg  # type: ignore

            _driver = ("psycopg3", psycopg)
        except ImportError:
            try:
                import psycopg2  # type: ignore

                _driver = ("psycopg2", psycopg2)
            except ImportError:
                _driver = None
        _driver_loaded = True
    return _driver


# --- connections -------------------------------------------------------------

def _connect():
    """Open a fresh autocommit-OFF connection to the configured database."""
    driver = _load_driver()
    if driver is None:
        raise RuntimeError("No psycopg driver installed")
    _name, module = driver
    # connect_timeout keeps a bad host from hanging a request thread forever.
    return module.connect(db_url(), connect_timeout=10)


@contextmanager
def wallet_txn(wallet_id: str) -> Iterator[dict]:
    """Yield a wallet dict under a ``SELECT ... FOR UPDATE`` row lock.

    The caller mutates the dict in place. On a clean exit the row is written
    back and committed; on any exception the transaction is rolled back and the
    lock released. An unknown wallet raises ``KeyError`` (the engine treats a
    missing wallet as an error, never as a zero balance).

    This is a **synchronous, blocking** context manager: the row lock is held
    for the duration. Callers must keep the critical section short (mutate +
    persist only, no network calls) so a stuck holder does not block other
    writers of the same wallet. main.py runs it via ``asyncio.to_thread`` so the
    event loop is never blocked.
    """
    conn = _connect()
    try:
        # A transaction is implicit from the first statement (autocommit off).
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT value FROM {WALLETS_TABLE} WHERE id = %s FOR UPDATE",
                (wallet_id,),
            )
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                raise KeyError(wallet_id)
            value = row[0]
            wallet = _decode(value)
            yield wallet
            cur.execute(
                f"UPDATE {WALLETS_TABLE} SET value = %s WHERE id = %s",
                (_encode(wallet), wallet_id),
            )
        conn.commit()
    except BaseException:
        # Roll back on *any* exit that is not a clean commit (including the
        # KeyError above), then re-raise so the caller sees the real error.
        try:
            conn.rollback()
        except Exception:  # pragma: no cover - best effort
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover
            pass


def load_wallet(wallet_id: str) -> dict | None:
    """Read a wallet without locking (a consistent snapshot, no row lock)."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT value FROM {WALLETS_TABLE} WHERE id = %s", (wallet_id,))
            row = cur.fetchone()
        return _decode(row[0]) if row is not None else None
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover
            pass


def save_wallet(wallet: dict) -> None:
    """Upsert a whole wallet row without taking a lock first.

    Used for *creating* a wallet (no concurrent writer can exist yet) and for
    settlement, where every wallet is processed under its own lock. Existing
    rows should be mutated through :func:`wallet_txn`, not here.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {WALLETS_TABLE} (id, value) VALUES (%s, %s)
                ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value
                """,
                (wallet["id"], _encode(wallet)),
            )
        conn.commit()
    except BaseException:
        try:
            conn.rollback()
        except Exception:  # pragma: no cover
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover
            pass


def list_wallet_ids() -> list[str]:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id FROM {WALLETS_TABLE}")
            return [r[0] for r in cur.fetchall()]
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover
            pass


# --- (de)serialization -------------------------------------------------------

def _decode(value) -> dict:
    # psycopg returns jsonb either already parsed (psycopg3 with adapters) or as
    # a str depending on config; accept both, and a JSON string from psycopg2.
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    raise TypeError(f"Unexpected wallet column type: {type(value)!r}")


def _encode(wallet: dict):
    # Pass a JSON string; Postgres casts it to jsonb on write, which both
    # drivers accept without needing a registered adapter.
    return json.dumps(wallet)
