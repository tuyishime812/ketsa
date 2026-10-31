"""Single-replica safety guard for the money-moving runtime.

Why this exists
---------------
The matching engine keeps order books, the trade tape and every wallet in
process memory, and it serializes balance mutations with an ``asyncio.Lock``
(``main.py``: ``_engine_lock``). That is correct **within one process only**.
Run ``uvicorn --workers N`` (or two replicas behind a load balancer) and each
process gets its own divergent books and its own view of the *same* persisted
balance — the classic double-spend: two workers can each read "balance 100",
each debit 100, and both persist, minting money the house never received.

Until wallet mutations are serialized in the database itself (``SELECT ... FOR
UPDATE`` inside one transaction — see ``dblock.py``), the only safe posture is
**exactly one** backend process while real money is in play. This module makes
that a fail-closed invariant instead of a documented hope: if it can detect a
multi-process configuration at boot it refuses to start.

Detection is best-effort (a platform that gives no worker hint cannot be
caught), so it is a guard rail, not a proof. It reads the well-known worker
hints that Gunicorn/Uvicorn/Railway/Render/Heroku set, plus an explicit
``KETSA_REPLICAS`` for platforms that expose nothing.

Override
--------
Set ``KETSA_ALLOW_MULTI_WORKER=1`` to acknowledge the risk and start anyway.
Do that only after the database row-locking path (``dblock.py``) is active and
the engine reads wallets through it — otherwise concurrent writers can corrupt
balances.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("ketsa.replica")

# Env vars that hold an integer worker/concurrency count on common platforms.
_WORKER_HINTS = (
    "WEB_CONCURRENCY",       # Gunicorn / Heroku / Render / Railway
    "UVICORN_WORKERS",       # explicit uvicorn workers
    "GUNICORN_WORKERS",      # gunicorn --workers
    "KETSA_WORKERS",         # our own alias
    "KETSA_REPLICAS",        # platform-independent replica count
)


class MultiWorkerError(RuntimeError):
    """Raised at boot when a multi-process config would risk double-spend."""


def _int_env(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def worker_count() -> int:
    """Best-effort count of concurrent backend processes, or 1 if unknown.

    Returns the **maximum** of every worker hint present, so setting any one
    of them to 2 is enough to trip the guard. Unknown hints are ignored; no
    hint at all yields 1 (the safe default assumption of a single process).
    """
    found = [_int_env(name) for name in _WORKER_HINTS]
    counts = [n for n in found if n is not None]
    if not counts:
        return 1
    return max(counts)


def allow_multi_worker() -> bool:
    return os.getenv("KETSA_ALLOW_MULTI_WORKER", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def check_single_replica(*, locked: bool) -> None:
    """Enforce the single-replica invariant at startup.

    Call once from the app lifespan. Raises :class:`MultiWorkerError` when a
    multi-process configuration is detected and the database row-locking path
    is **not** active and no explicit override is set.

    ``locked`` is True when wallet mutations are serialized in the database
    (``dblock`` active). In that case any worker count is fine and the guard
    stands down. Otherwise only one process is safe.
    """
    count = worker_count()
    if count <= 1:
        logger.info("replica guard: single process (workers=%d) — OK", count)
        return
    if locked:
        logger.info(
            "replica guard: workers=%d but DB row locking is active — OK", count
        )
        return
    if allow_multi_worker():
        logger.warning(
            "replica guard: workers=%d with NO DB row locking — started anyway "
            "because KETSA_ALLOW_MULTI_WORKER is set. Concurrent wallet mutations "
            "can double-spend. Only do this if wallet writes are serialized "
            "elsewhere.",
            count,
        )
        return
    raise MultiWorkerError(
        f"Detected {count} concurrent backend processes but wallet mutations are "
        "still serialized in-process (asyncio.Lock), so running more than one "
        "process can double-spend real money. Run exactly one worker/replica, "
        "enable the database row-locking path (dblock), or, to acknowledge the "
        "risk, set KETSA_ALLOW_MULTI_WORKER=1. See backend/app/replica.py."
    )
