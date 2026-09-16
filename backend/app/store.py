"""Read/write helpers over the active storage backend.

The public read API and the protected admin API both funnel through these
functions so there is a single source of truth (the storage backend) and no
drift between what the admin edits and what visitors see.

The backend (memory or Supabase) is chosen via ``KETSA_DB_BACKEND`` — see
`app/storage.py`.
"""

from .storage import get_backend

# --- Markets ----------------------------------------------------------------

def list_markets() -> list[dict]:
    return get_backend().list_markets()


def get_market(market_id: str) -> dict | None:
    return get_backend().get_market(market_id)


def upsert_market(m: dict) -> None:
    get_backend().upsert_market(m)


def delete_market(market_id: str) -> bool:
    return get_backend().delete_market(market_id)


# --- Watch ------------------------------------------------------------------

def list_watch() -> list[dict]:
    return get_backend().list_watch()


def replace_watch(items: list[dict]) -> None:
    get_backend().replace_watch(items)


# --- Ticker -----------------------------------------------------------------

def list_ticker() -> list[dict]:
    return get_backend().list_ticker()


def replace_ticker(items: list[dict]) -> None:
    get_backend().replace_ticker(items)


# --- Dashboard --------------------------------------------------------------

def get_dashboard() -> dict:
    return get_backend().get_dashboard()


def save_dashboard(data: dict) -> None:
    get_backend().save_dashboard(data)


# --- Stats / proof ----------------------------------------------------------

def get_stats() -> dict:
    return get_backend().get_stats()


def save_stats(s: dict) -> None:
    get_backend().save_stats(s)


def get_proof() -> dict:
    return get_backend().get_proof()


def save_proof(p: dict) -> None:
    get_backend().save_proof(p)


# --- Wallets ----------------------------------------------------------------

def get_wallet(wallet_id: str) -> dict | None:
    return get_backend().get_wallet(wallet_id)


def upsert_wallet(wallet: dict) -> None:
    get_backend().upsert_wallet(wallet)


def list_wallets() -> list[dict]:
    return get_backend().list_wallets()


# --- Users ------------------------------------------------------------------

def get_user(user_id: str) -> dict | None:
    return get_backend().get_user(user_id)


def get_user_by_email(email: str) -> dict | None:
    return get_backend().get_user_by_email(email)


def upsert_user(user: dict) -> None:
    get_backend().upsert_user(user)


def list_users() -> list[dict]:
    return get_backend().list_users()


def delete_user(user_id: str) -> bool:
    return get_backend().delete_user(user_id)


# --- Notifications -----------------------------------------------------------

def upsert_notification(notification: dict) -> None:
    get_backend().upsert_notification(notification)


def list_notifications(wallet_id: str | None = None, limit: int = 50) -> list[dict]:
    return get_backend().list_notifications(wallet_id, limit)


def mark_notifications_read(wallet_id: str, ids: list[str] | None = None) -> int:
    return get_backend().mark_notifications_read(wallet_id, ids)


# --- Payments ---------------------------------------------------------------

def upsert_payment(payment: dict) -> None:
    get_backend().upsert_payment(payment)


def get_payment(payment_id: str) -> dict | None:
    return get_backend().get_payment(payment_id)


def list_payments(wallet_id: str | None = None) -> list[dict]:
    return get_backend().list_payments(wallet_id)
