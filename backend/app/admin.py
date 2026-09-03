"""Protected admin API for managing the Ketsa site content.

Access is gated by a single shared admin password (`KETSA_ADMIN_PASSWORD`).
On login the client receives a server-issued token which must be supplied on
every subsequent request via the `Authorization: Bearer <token>` header.

Tokens are random and held in memory, so restarting the server invalidates
them (a fresh login is required). This is intentional: the admin gate is a
simple, low-overhead safeguard for a marketing site, not a multi-user RBAC
system.
"""

import hashlib
import json
import os
import secrets
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from . import store
from .database import get_conn, get_setting, set_setting

router = APIRouter(prefix="/api/admin", tags=["admin"])

# token -> expiry (unix seconds). Tokens last 12h.
_tokens: dict[str, float] = {}
TOKEN_TTL = 12 * 3600


def _get_admin_password() -> str:
    return os.getenv("KETSA_ADMIN_PASSWORD") or "ketsa-admin"


def _hash_token(token: str) -> str:
    # Store only a HMAC-style hash of the token in memory so a memory dump
    # doesn't leak usable tokens. Token entropy makes this safe enough.
    return hashlib.sha256(("ketsa:" + token).encode()).hexdigest()


def require_admin(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ").strip()
    digest = _hash_token(token)
    now = time.time()
    expiry = _tokens.get(digest)
    if expiry is None or expiry < now:
        # Purge expired digest for hygiene.
        _tokens.pop(digest, None)
        raise HTTPException(status_code=401, detail="Session expired, please log in again")
    _tokens[digest] = now + TOKEN_TTL  # sliding window


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str


class MessageResponse(BaseModel):
    ok: bool = True
    detail: str | None = None


# --- Auth -------------------------------------------------------------------

@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    # Constant-time-ish comparison to reduce trivial timing signal.
    expected = _get_admin_password().encode()
    supplied = body.password.encode()
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid password")
    token = secrets.token_urlsafe(32)
    _tokens[_hash_token(token)] = time.time() + TOKEN_TTL
    return LoginResponse(token=token)


# --- Markets ----------------------------------------------------------------

@router.post("/markets", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_markets_create(m: dict) -> MessageResponse:
    try:
        store.upsert_market(m)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not save market")
    return MessageResponse()


@router.put("/markets", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_markets_update(m: dict) -> MessageResponse:
    try:
        store.upsert_market(m)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not save market")
    return MessageResponse()


@router.delete("/markets/{market_id}", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_markets_delete(market_id: str) -> MessageResponse:
    deleted = store.delete_market(market_id)
    return MessageResponse(ok=True, detail=("deleted" if deleted else "not found"))


# --- Watch ------------------------------------------------------------------

@router.put("/watch", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_watch_replace(items: list[dict]) -> MessageResponse:
    store.replace_watch(items)
    return MessageResponse()


# --- Ticker -----------------------------------------------------------------

@router.put("/ticker", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_ticker_replace(items: list[dict]) -> MessageResponse:
    store.replace_ticker(items)
    return MessageResponse()


# --- Dashboard / stats / proof ---------------------------------------------

@router.put("/dashboard", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_dashboard_save(body: dict) -> MessageResponse:
    store.save_dashboard(body)
    return MessageResponse()


@router.put("/stats", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_stats_save(body: dict) -> MessageResponse:
    store.save_stats(body)
    return MessageResponse()


@router.put("/proof", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_proof_save(body: dict) -> MessageResponse:
    store.save_proof(body)
    return MessageResponse()


# --- Settings (hero, CTA, steps, footer, section copy) ----------------------

@router.get("/settings", dependencies=[Depends(require_admin)])
async def admin_settings_get() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: json.loads(r["value"]) for r in rows}


@router.put("/settings", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_settings_put(body: dict) -> MessageResponse:
    for key, value in body.items():
        set_setting(key, value)
    return MessageResponse()


@router.put("/settings/{section}", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def admin_settings_section(section: str, body: dict) -> MessageResponse:
    set_setting(section, body)
    return MessageResponse()
