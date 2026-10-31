"""Ketsa backend — FastAPI application.

Serves the prediction-market data consumed by the Next.js frontend.

All public read endpoints source their data from the active storage backend
(see `store.py` / `storage.py`), which is seeded from the original static data
on first run. Edits made through the protected admin API (see `admin.py`) are
reflected immediately on the public endpoints.

Security posture:
  * CORS is restricted to an explicit allowlist (no wildcards of origin).
  * Write operations live exclusively behind `/api/admin` and require a
    server-issued bearer token obtained via the admin password.
  * CSP / other browser security headers are set on every response.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import authstate
from . import audit
from . import dblock
from . import mailer
from . import netutil
from . import replica
from . import payments as paychangu
from . import siteconfig
from . import staff
from . import store
from .admin import MessageResponse, require_admin, router as admin_router
from .auth import require_user, resolve_optional_user, router as auth_router
from .config import load_env_file
from .engine import engine
from .storage import get_all_settings, init_db
from .models import (
    DashboardData,
    DashboardSeries,
    DepositRequest,
    HomeData,
    LeaderboardEntry,
    Market,
    MarketsByCategory,
    MarketsGroup,
    MarkReadRequest,
    Notification,
    OrderBook,
    Payment,
    PortfolioStats,
    Position,
    Proof,
    ResolveMarketRequest,
    StaffPublic,
    TickerItem,
    Trade,
    TradeRequest,
    TradeResponse,
    Wallet,
    WalletConnectRequest,
    WatchItem,
    WithdrawalRequest,
)

CATEGORIES = ['politics', 'crypto', 'sports', 'culture', 'tech', 'climate']

logger = logging.getLogger("ketsa.main")


def _market_due(market: dict | None) -> bool:
    """True when a market has no end date, or its end date has already passed.

    Used by the optional resolution guard (Settings → Market resolution): when
    enabled, a market may only be resolved once it is actually due, so an
    operator can't settle a question ahead of its published close time.
    """
    end_date = (market or {}).get("end_date")
    if not end_date:
        return True
    try:
        due = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
    except ValueError:
        return True  # unparseable date — don't block; treat as due
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= due


class ConnectionManager:
    """Fan-out of live market data to connected WebSocket clients.

    Clients may (optionally) subscribe to a wallet to receive that wallet's
    private notices (fill/payment/system notifications) on the same socket.
    Public events — market ticks, trades, resolutions, leaderboard changes —
    are always broadcast to every connection.
    """

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._subs: dict[WebSocket, str | None] = {}

    @property
    def connected(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)
        self._subs[websocket] = None

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)
        self._subs.pop(websocket, None)

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def subscribe(self, websocket: WebSocket, wallet_id: str) -> None:
        self._subs[websocket] = wallet_id

    async def broadcast(self, message: str) -> None:
        dead: list[WebSocket] = []
        try:
            payload = json.loads(message)
        except (ValueError, TypeError):
            payload = None
        for ws in list(self._connections):
            # Wallet-scoped notifications go only to the subscribed wallet.
            if isinstance(payload, dict) and payload.get("type") == "notification":
                owner = (payload.get("notification") or {}).get("wallet_id")
                if self._subs.get(ws) is None or self._subs.get(ws) != owner:
                    continue
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


async def _pump_events(manager: ConnectionManager) -> None:
    """Flush engine events to connected WebSocket clients."""
    for payload in engine.flush_events():
        asyncio.create_task(manager.broadcast(json.dumps(payload, default=str)))


class _RateLimiter:
    """Small in-memory fixed-window rate limiter keyed by client identifier.

    Not a substitute for a distributed limiter (e.g. Redis) at scale; the Ketsa
    API is a read-only, seed-data service where a simple per-instance guard is
    sufficient. Behind a load balancer each instance tracks its own window.
    """

    def __init__(self, limit_per_min: int) -> None:
        self.limit_per_min = limit_per_min
        # client -> (count, window_start)
        self._buckets: dict[str, tuple[int, float]] = {}

    def allow(self, client: str) -> bool:
        if self.limit_per_min <= 0:
            return True
        now = time.monotonic()
        window = 60.0
        count, start = self._buckets.get(client, (0, now))
        if now - start >= window:
            count, start = 0, now
        count += 1
        self._buckets[client] = (count, start)
        return count <= self.limit_per_min


def _markets_group() -> MarketsGroup:
    markets = engine.list_markets()
    by = {c: [m for m in markets if m["cat"] == c] for c in CATEGORIES}
    return MarketsGroup(
        all=[Market(**m) for m in markets],
        by_category=MarketsByCategory(**by),
    )


# Only these content sections are ever exposed by the public API. Operational
# config (payments/security/staff roles/resolution) lives in the same settings
# store under `config:*` keys, and must never leak into /api/home.
_PUBLIC_SETTING_KEYS = (
    "hero",
    "cta",
    "steps",
    "footer",
    "markets_section",
    "dashboard_section",
)


def _public_settings() -> dict:
    all_settings = get_all_settings()
    return {k: all_settings[k] for k in _PUBLIC_SETTING_KEYS if k in all_settings}


def _leaderboard(limit: int = 20) -> list[dict]:
    """Rank wallets by equity (balance + live position value).

    Wallets held in the live engine are valued accurately; wallets only present
    in storage (restored) are valued from their cash balance + realized P&L so
    the board never misses funded accounts.
    """
    rows = []
    for w in store.list_wallets():
        wallet_id = w["id"]
        name = (w.get("name") or "").strip() or (wallet_id[:8] if wallet_id else "Trader")
        live = engine.wallet_view(wallet_id)
        if live is not None:
            rows.append({
                "wallet_id": wallet_id,
                "name": name,
                "equity": live["equity"],
                "realized_pnl": live["realized_pnl"],
                "positions": len(live["positions"]),
            })
        else:
            balance = float(w.get("balance") or 0.0)
            realized = float(w.get("realized") or 0.0)
            rows.append({
                "wallet_id": wallet_id,
                "name": name,
                "equity": round(balance + realized, 2),
                "realized_pnl": round(realized, 2),
                "positions": 0,
            })
    rows.sort(key=lambda r: r["equity"], reverse=True)
    return rows[:limit]


def create_app() -> "FastAPI":
    # Load backend/.env (gitignored) so local secrets resolve before the
    # storage backend is selected; real env vars always take precedence.
    load_env_file()

    # Ensure the active storage backend is initialised and seeded before
    # serving requests.
    init_db()

    allowed_origins = (
        os.getenv("KETSA_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
        .split(",")
    )

    expose_docs = os.getenv("KETSA_EXPOSE_DOCS", "0").lower() in ("1", "true", "yes")
    rate_limit_per_min = int(os.getenv("KETSA_RATE_LIMIT_PER_MIN", "120"))
    limiter = _RateLimiter(rate_limit_per_min)
    # Write endpoints (wallet mints, trades, payments) get a much stricter
    # per-IP budget on top of the global limiter (F-07 hardening).
    write_rate_limit_per_min = int(os.getenv("KETSA_WRITE_RATE_LIMIT_PER_MIN", "30"))
    write_limiter = _RateLimiter(write_rate_limit_per_min)
    # Money-movement caps (MWK) and deposit/withdrawal enables are now
    # admin-configurable (Settings → Payments). They are read per request via
    # siteconfig so an admin change takes effect without a restart; the env vars
    # (KETSA_MAX_*_MWK) remain the defaults.
    # Hard ceiling on concurrent WebSocket clients, so the live feed can't be
    # used to exhaust process memory (CWE-770).
    ws_max_connections = int(os.getenv("KETSA_WS_MAX_CONNECTIONS", "2000"))
    manager = ConnectionManager()

    # --- Real-time push -----------------------------------------------------
    # The engine fires `_signal_events` after every queued event. We hop back
    # onto the loop and wake `_event_pump`, which broadcasts within a loop
    # iteration. Without this, an admin-side change (staff upload/remove, but
    # also payments) would sit in the queue until the next 12s `_tick_loop`
    # flush — visible lag, not "real time".
    pump_signal = asyncio.Event()
    _loop_ref: dict[str, asyncio.AbstractEventLoop | None] = {"loop": None}

    def _signal_events() -> None:
        # May run on the loop thread (normal) or a worker thread; call_soon_
        # threadsafe is correct and cheap either way.
        loop = _loop_ref["loop"]
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(pump_signal.set)
        except RuntimeError:  # pragma: no cover - loop closed during shutdown
            pass

    async def _event_pump() -> None:
        while True:
            await pump_signal.wait()
            pump_signal.clear()
            await _pump_events(manager)

    async def _tick_loop() -> None:
        # Simulated liquidity-provider repricing keeps the feed alive between
        # user trades so the order books feel genuinely live.
        while True:
            await asyncio.sleep(12)
            engine.random_tick()
            await _pump_events(manager)

    @asynccontextmanager
    async def _lifespan(_: FastAPI):
        # Refuse to start a multi-process configuration while wallet mutations
        # are still serialized only in-process: two workers can double-spend.
        # Stands down when the DB row-locking path (dblock) is active. See
        # replica.py for the rationale and the override.
        replica.check_single_replica(locked=dblock.configured())

        # State the active storage backend up front: flipping KETSA_DB_BACKEND
        # silently redirects every write (accounts, staff, content) to a
        # different place. The plain fact goes to info; an *ephemeral* backend
        # is a warning, because `memory` loses all of it on the next restart.
        backend_name = type(store.get_backend()).__name__
        logger.info("storage backend=%s", backend_name)
        if dblock.configured():
            logger.info(
                "wallet row locking=ON (KETSA_DB_URL set) — multi-process safe"
            )
        else:
            logger.info(
                "wallet row locking=OFF — run a SINGLE process (see replica.py)"
            )
        if backend_name == "MemoryBackend":
            logger.warning(
                "Storage backend is IN-MEMORY — accounts, staff and content are "
                "not persisted and are lost on restart. Point KETSA_DB_BACKEND at "
                "supabase (with db/schema.sql applied) for durable storage."
            )

        # Tell the operator, once, whether transactional email can actually
        # reach users. Signup/reset depend on it, so a silent log-only or
        # sandbox misconfiguration is the difference between "account creation
        # works" and a field of 502s.
        status = mailer.email_status()
        logger.info(
            "email delivery=%s from=%s api_key_set=%s",
            status["delivery"],
            status["from"],
            status["api_key_set"],
        )
        if status["delivery"] == "log":
            logger.warning(
                "Email is in LOG mode — verification and reset codes are written "
                "to this log and NOT sent. Set KETSA_RESEND_API_KEY (and a verified "
                "KETSA_RESEND_FROM domain) or KETSA_EMAIL_DELIVERY=resend for real "
                "delivery."
            )
        elif status["sandbox_sender"]:
            logger.warning(
                "Email sender %s is Resend's sandbox — only the account owner's own "
                "inbox receives mail, so other users cannot complete signup. Verify "
                "a sending domain and set KETSA_RESEND_FROM.",
                status["from"],
            )

        # Sessions, OTPs and throttles live in the storage backend, so a
        # Supabase deployment needs the `ketsa_auth` table from db/schema.sql.
        # Without it every login/signup/reset raises an opaque 500 at request
        # time; surface it once, clearly, at boot instead.
        try:
            store.get_backend().auth_count(authstate.NS_OTP)
        except Exception as exc:  # startup diagnostic — never fatal
            logger.error(
                "Auth state store is unavailable — logins, signups and password "
                "resets will fail with 500 until it exists. On Supabase, run "
                "backend/db/schema.sql (creates public.ketsa_auth). Cause: %s",
                exc,
            )

        task = asyncio.create_task(_tick_loop())
        _loop_ref["loop"] = asyncio.get_running_loop()
        engine.set_emit_hook(_signal_events)
        pump_task = asyncio.create_task(_event_pump())
        try:
            yield
        finally:
            task.cancel()
            pump_task.cancel()
            engine.set_emit_hook(None)
            _loop_ref["loop"] = None

    app = FastAPI(
        title="Ketsa API",
        description="Real-time market data for the Ketsa prediction market.",
        version="1.1.0",
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        # Admin panel needs writes; public read endpoints remain GET-only.
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers_and_ratelimit(request: Request, call_next):
        client = netutil.client_ip(request)
        if not limiter.allow(client):
            response = JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
            )
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        return response

    app.include_router(admin_router)
    app.include_router(auth_router)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(request: Request, exc: RequestValidationError):
        """Sanitized 422s: never echo raw input values back.

        Raw echo is how NaN/Infinity (or hostile strings) leak into error
        responses — Python's JSON encoder refuses NaN, so a rejection of
        ``{"amount": NaN}`` would otherwise crash the error path itself.
        """
        if not (request.url.path.endswith("/payments/deposits")
                or request.url.path.endswith("/payments/withdrawals")
                or request.url.path.endswith("/trade")):
            # Default FastAPI validation errors everywhere else.
            return JSONResponse(status_code=422, content={"detail": exc.errors()})
        messages = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
            messages.append(f"{loc}: {err.get('msg', 'invalid')}" if loc else str(err.get("msg", "invalid")))
        return JSONResponse(status_code=422, content={"detail": messages})

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/markets", response_model=MarketsGroup)
    async def markets() -> MarketsGroup:
        return _markets_group()

    @app.get("/api/markets/{market_id}", response_model=Market)
    async def market(market_id: str) -> Market:
        m = engine.snapshot_market(market_id)
        if m is None:
            raise HTTPException(status_code=404, detail="Market not found")
        return Market(**m)

    @app.get("/api/markets/{market_id}/book", response_model=OrderBook)
    async def market_book(market_id: str) -> OrderBook:
        book = engine.book_view(market_id)
        if book is None:
            raise HTTPException(status_code=404, detail="Market not found")
        return OrderBook(**book)

    @app.get("/api/markets/{market_id}/trades", response_model=list[Trade])
    async def market_trades(market_id: str, limit: int = 20) -> list[Trade]:
        limit = max(1, min(limit, 100))
        trades = engine.recent_trades(market_id, limit)
        if trades is None:
            raise HTTPException(status_code=404, detail="Market not found")
        return [Trade(**t) for t in trades]

    # --- Simulated wallet / trading --------------------------------------

    @app.post("/api/wallet", response_model=Wallet)
    async def connect_wallet(
        body: WalletConnectRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> Wallet:
        _require_write_capacity(request)
        w = engine.connect_wallet(body.id, body.name)
        # Restoring an existing wallet by id is account-gated (F-02): an
        # account-owned wallet can only be re-connected by its owner.
        _gate_wallet(authorization, w["id"])
        return Wallet(**w)

    @app.get("/api/wallet/{wallet_id}", response_model=Wallet)
    async def get_wallet(
        wallet_id: str, authorization: str | None = Header(default=None)
    ) -> Wallet:
        _gate_wallet(authorization, wallet_id)
        w = engine.wallet_view(wallet_id)
        if w is None:
            raise HTTPException(status_code=404, detail="Wallet not found")
        return Wallet(**w)

    # --- Real-money payments (wandePay — MWK) -------------------------------

    _TERMINAL_FAIL = ("FAILED", "DECLINED", "REVERSED", "CANCELLED", "ERROR")
    # Serializes every balance-mutating operation (trades, deposits, credits,
    # withdrawal debits/refunds, resolution settlements) so concurrent requests
    # can never double-credit, double-claim or race a refund against a spend.
    _engine_lock = asyncio.Lock()

    def _require_payments() -> None:
        if not paychangu.configured():
            raise HTTPException(status_code=503, detail="Payments are not configured on this server")

    def _require_wallet(wallet_id: str) -> None:
        if engine.wallet_view(wallet_id) is None:
            raise HTTPException(status_code=404, detail="Wallet not found")

    def _require_write_capacity(request: Request) -> None:
        client = netutil.client_ip(request)
        if not write_limiter.allow(client):
            raise HTTPException(status_code=429, detail="Too many requests. Please slow down.")

    def _wallet_access(authorization: str | None, wallet_id: str) -> tuple[int, str] | None:
        """Resolve whether a caller may use a wallet. ``None`` = allowed.

        Account-owned wallets are usable only by their owner. Guests (no
        Authorization header) may keep using *unclaimed* simulated wallets —
        ids are server-minted and unguessable, and with the zero seed they
        hold no real funds. An invalid token is 401; a valid token for a
        different account is 403, so account wallets can't be dumped, traded
        or drained by anyone who guesses/leaks an id.

        Returns ``(status_code, detail)`` when access is denied. This is the
        single source of truth for wallet ownership — the HTTP routes raise on
        it and the WebSocket subscription path (which cannot raise) reads it
        directly, so the two can't drift apart.

        ``authorization`` accepts either a full `Bearer <token>` header value
        (the HTTP routes) or a bare token (the WebSocket sub frame), and an
        invalid/expired token is converted to a denial rather than raised, so a
        bad token can't tear down the socket.
        """
        if not wallet_id:
            return (400, "Missing wallet id")
        raw = (authorization or "").strip()
        if raw and not raw.startswith("Bearer "):
            raw = f"Bearer {raw}"
        try:
            user = resolve_optional_user(raw or None)
        except HTTPException as e:
            return (e.status_code, str(e.detail))
        owner = store.get_user_by_wallet_id(wallet_id)
        if owner is None:
            return None  # unclaimed sim wallet — open to whoever holds its id
        if user is None:
            return (401, "This wallet belongs to an account. Please log in.")
        if user["wallet_id"] != wallet_id:
            return (403, "This wallet belongs to another account")
        return None

    def _gate_wallet(authorization: str | None, wallet_id: str) -> None:
        """HTTP wrapper around :func:`_wallet_access` that raises on denial."""
        denied = _wallet_access(authorization, wallet_id)
        if denied is not None:
            raise HTTPException(status_code=denied[0], detail=denied[1])

    def _require_own_wallet(user: dict, wallet_id: str) -> None:
        """Money endpoints require an authenticated account and its wallet."""
        if user["wallet_id"] != wallet_id:
            raise HTTPException(status_code=403, detail="This wallet belongs to another account")

    def _payment_payload(rec: dict) -> dict:
        return Payment(**rec).model_dump()

    @app.post("/api/payments/deposits", response_model=Payment)
    async def create_deposit(
        body: DepositRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> Payment:
        _require_payments()
        cfg = siteconfig.payments()
        if not cfg["deposits_enabled"]:
            raise HTTPException(status_code=503, detail="Deposits are temporarily disabled")
        _require_write_capacity(request)
        user = require_user(authorization)
        _require_wallet(body.wallet_id)
        _require_own_wallet(user, body.wallet_id)
        try:
            number = paychangu.normalize_number(body.number)
        except paychangu.PayChanguError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if body.correspondent not in paychangu.CORRESPONDENTS:
            raise HTTPException(status_code=400, detail="Unknown correspondent")
        if body.amount < paychangu.MIN_AMOUNT_MWK:
            raise HTTPException(status_code=400, detail=f"Minimum deposit is {int(paychangu.MIN_AMOUNT_MWK)} MWK")
        if not round(float(body.amount), 2) == float(body.amount):
            raise HTTPException(status_code=400, detail="Amount must have at most 2 decimal places")
        if body.amount > cfg["max_deposit_mwk"]:
            raise HTTPException(
                status_code=400,
                detail=f"Deposits are capped at {cfg['max_deposit_mwk']:g} MWK per transaction",
            )
        try:
            payload = await asyncio.to_thread(
                paychangu.create_deposit, body.amount, number, body.correspondent
            )
        except paychangu.PayChanguError as e:
            raise HTTPException(status_code=502, detail=str(e))
        tx = (payload.get("data") or {}).get("transaction") or {}
        wande_id = tx.get("id")
        if not wande_id:
            raise HTTPException(status_code=502, detail="wandePay did not return a deposit id")
        now = time.time()
        record = {
            "id": uuid.uuid4().hex,
            "wallet_id": body.wallet_id,
            "kind": "deposit",
            "amount": round(float(body.amount), 2),
            "number": number,
            "correspondent": body.correspondent,
            "status": "pending",
            "credited": False,
            "wande_id": str(wande_id),
            "message": None,
            "created": now,
            "updated": now,
        }
        store.upsert_payment(record)
        return _payment_payload(record)

    @app.get("/api/payments", response_model=list[Payment])
    async def list_payments(
        wallet_id: str | None = None,
        authorization: str | None = Header(default=None),
    ) -> list[Payment]:
        # A user can only ever see their own wallet's money movement — the
        # unauthenticated cross-wallet ledger dump is closed (F-02).
        user = require_user(authorization)
        own = user["wallet_id"]
        if wallet_id is not None and wallet_id != own:
            raise HTTPException(status_code=403, detail="This wallet belongs to another account")
        return [_payment_payload(p) for p in store.list_payments(own)]

    @app.get("/api/payments/{payment_id}", response_model=Payment)
    async def payment_status(
        payment_id: str, authorization: str | None = Header(default=None)
    ) -> Payment:
        _require_payments()
        user = require_user(authorization)
        rec = store.get_payment(payment_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="Payment not found")
        if rec["wallet_id"] != user["wallet_id"]:
            raise HTTPException(status_code=403, detail="This payment belongs to another account")

        async with _engine_lock:
            rec = store.get_payment(payment_id)  # re-read inside lock
            if rec["status"] != "pending":
                return _payment_payload(rec)

            if rec["kind"] == "deposit":
                try:
                    payload = await asyncio.to_thread(paychangu.deposit_status, rec["wande_id"])
                except paychangu.PayChanguError as e:
                    raise HTTPException(status_code=502, detail=str(e))
                ts = payload.get("transaction_status", "").upper()
                if payload.get("status") != "success":
                    rec["status"] = "failed"
                    rec["message"] = str(payload.get("message") or "Deposit check failed")
                elif ts == "COMPLETED":
                    if not rec["credited"]:
                        engine.credit_balance(rec["wallet_id"], rec["amount"])
                        rec["credited"] = True
                        engine.emit({"type": "leaderboard"})
                    rec["status"] = "completed"
                    engine.notify(
                        rec["wallet_id"],
                        "deposit",
                        "Deposit received",
                        f"{rec['amount']:.2f} {rec['correspondent']} credited to your balance.",
                    )
                elif ts in _TERMINAL_FAIL:
                    rec["status"] = "failed"
                    rec["message"] = payload.get("message") or ts
            else:  # withdrawal
                try:
                    payload = await asyncio.to_thread(paychangu.withdrawal_status, rec["wande_id"])
                except paychangu.PayChanguError as e:
                    raise HTTPException(status_code=502, detail=str(e))
                ts = payload.get("withdrawal_status", "").upper()
                if payload.get("status") != "success":
                    rec["status"] = "failed"
                    rec["message"] = str(payload.get("message") or "Withdrawal check failed")
                elif ts == "COMPLETED":
                    rec["status"] = "completed"
                    engine.notify(
                        rec["wallet_id"],
                        "withdraw",
                        "Withdrawal paid out",
                        f"{rec['amount']:.2f} sent to {rec['number']}.",
                    )
                elif ts in _TERMINAL_FAIL:
                    rec["status"] = "failed"
                    rec["message"] = payload.get("message") or ts
                if rec["status"] == "failed" and not rec["rolled_back"]:
                    engine.credit_balance(rec["wallet_id"], rec["amount"])
                    rec["rolled_back"] = True
                    engine.emit({"type": "leaderboard"})
                    engine.notify(
                        rec["wallet_id"],
                        "withdraw",
                        "Withdrawal refunded",
                        f"Your {rec['amount']:.2f} withdrawal failed and was refunded.",
                    )

            now = time.time()
            rec["updated"] = now
            store.upsert_payment(rec)
            await _pump_events(manager)
            return _payment_payload(rec)

    @app.post("/api/payments/withdrawals", response_model=Payment)
    async def create_withdrawal(
        body: WithdrawalRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> Payment:
        _require_payments()
        cfg = siteconfig.payments()
        if not cfg["withdrawals_enabled"]:
            raise HTTPException(status_code=503, detail="Withdrawals are temporarily disabled")
        _require_write_capacity(request)
        user = require_user(authorization)  # guests can no longer move money out (F-03)
        _require_wallet(body.wallet_id)
        _require_own_wallet(user, body.wallet_id)
        try:
            number = paychangu.normalize_number(body.number)
        except paychangu.PayChanguError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if body.correspondent not in paychangu.CORRESPONDENTS:
            raise HTTPException(status_code=400, detail="Unknown correspondent")
        if body.amount < paychangu.MIN_AMOUNT_MWK:
            raise HTTPException(status_code=400, detail=f"Minimum withdrawal is {int(paychangu.MIN_AMOUNT_MWK)} MWK")
        if body.amount > cfg["max_withdrawal_mwk"]:
            raise HTTPException(
                status_code=400,
                detail=f"Withdrawals are capped at {cfg['max_withdrawal_mwk']:g} MWK per transaction",
            )
        if not round(float(body.amount), 2) == float(body.amount):
            raise HTTPException(status_code=400, detail="Amount must have at most 2 decimal places")
        recent = sum(
            p["amount"]
            for p in store.list_payments(body.wallet_id)
            if p["kind"] == "withdraw" and p["created"] >= time.time() - 86400
        )
        if recent + body.amount > cfg["daily_withdrawal_limit_mwk"]:
            raise HTTPException(
                status_code=400,
                detail="Daily withdrawal limit reached for this wallet",
            )
        async with _engine_lock:
            try:
                engine.debit_balance(body.wallet_id, body.amount)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            try:
                payload = await asyncio.to_thread(
                    paychangu.create_withdrawal, body.amount, number, body.correspondent
                )
            except paychangu.PayChanguError as e:
                engine.credit_balance(body.wallet_id, body.amount)
                raise HTTPException(status_code=502, detail=str(e))
            payout = (payload.get("data") or {})
            payout_id = payout.get("payoutId")
            if not payout_id:
                engine.credit_balance(body.wallet_id, body.amount)
                raise HTTPException(status_code=502, detail="wandePay did not return a payout id")
            now = time.time()
            record = {
                "id": uuid.uuid4().hex,
                "wallet_id": body.wallet_id,
                "kind": "withdraw",
                "amount": round(float(body.amount), 2),
                "number": number,
                "correspondent": body.correspondent,
                "status": "pending",
                "credited": False,
                "rolled_back": False,
                "wande_id": str(payout_id),
                "message": payload.get("message"),
                "created": now,
                "updated": now,
            }
            store.upsert_payment(record)
            engine.notify(
                record["wallet_id"],
                "withdraw",
                "Withdrawal initiated",
                f"{record['amount']:.2f} MWK is being sent to {number}.",
            )
            return _payment_payload(record)

    @app.post("/api/trade", response_model=TradeResponse)
    @app.post("/api/trades", response_model=TradeResponse)
    @app.post("/api/bet", response_model=TradeResponse)
    @app.post("/api/bets", response_model=TradeResponse)
    @app.post("/api/slip", response_model=TradeResponse)
    @app.post("/api/trade/multi", response_model=TradeResponse)
    @app.post("/api/trades/multi", response_model=TradeResponse)
    async def place_trade(
        body: TradeRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> TradeResponse:
        _require_write_capacity(request)
        _gate_wallet(authorization, body.wallet_id)
        async with _engine_lock:
            try:
                legs = body.legs or body.slip or body.bets or getattr(body, 'selections', None)
                result = engine.place_trade(
                    body.wallet_id,
                    body.market_id,
                    body.outcome,
                    body.side,
                    amount=body.amount,
                    shares=body.shares,
                    legs=legs,
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
        await _pump_events(manager)
        try:
            return TradeResponse(**result)
        except Exception:
            return TradeResponse(**result)

    @app.post(
        "/api/admin/markets/{market_id}/resolve",
        response_model=MessageResponse,
    )
    async def admin_markets_resolve(
        market_id: str,
        body: ResolveMarketRequest,
        request: Request,
        actor: str = Depends(require_admin),
    ) -> MessageResponse:
        cfg = siteconfig.resolution()
        if not cfg["resolution_enabled"]:
            raise HTTPException(
                status_code=503, detail="Market resolution is temporarily disabled"
            )
        if cfg["require_end_date"] and not _market_due(store.get_market(market_id)):
            raise HTTPException(
                status_code=400,
                detail="This market has not reached its end date yet",
            )
        async with _engine_lock:
            try:
                summary = engine.resolve_market(market_id, body.outcome)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
        await _pump_events(manager)
        # Settlement pays out real money: record exactly who resolved which
        # market, to what outcome, and how much was paid.
        audit.record(
            audit.Actions.MARKET_RESOLVED,
            actor_type="admin",
            actor_id=actor,
            ip=netutil.client_ip(request),
            target_type="market",
            target_id=market_id,
            metadata={
                "outcome": body.outcome,
                "resolved_price": summary["resolved_price"],
                "wallets_settled": summary["wallets_settled"],
                "total_payout": summary["total_payout"],
            },
        )
        detail = (
            f"Resolved {market_id} → {body.outcome.upper()} at "
            f"{summary['resolved_price']}¢ · {summary['wallets_settled']} wallets"
            f" settled · ${summary['total_payout']:.2f} paid out"
        )
        return MessageResponse(detail=detail)

    @app.get("/api/leaderboard", response_model=list[LeaderboardEntry])
    async def leaderboard(limit: int = 25) -> list[LeaderboardEntry]:
        rows = _leaderboard(max(1, min(limit, 100)))
        return [
            LeaderboardEntry(rank=i + 1, currency="MWK", **row)
            for i, row in enumerate(rows)
        ]

    # --- In-app notifications ---------------------------------------------

    @app.get("/api/wallet/{wallet_id}/notifications", response_model=list[Notification])
    async def wallet_notifications(
        wallet_id: str,
        limit: int = 25,
        authorization: str | None = Header(default=None),
    ) -> list[Notification]:
        _gate_wallet(authorization, wallet_id)
        if engine.wallet_view(wallet_id) is None:
            raise HTTPException(status_code=404, detail="Wallet not found")
        items = store.list_notifications(wallet_id, max(1, min(limit, 100)))
        return [Notification(**n) for n in items]

    @app.post("/api/wallet/{wallet_id}/notifications/read", response_model=dict)
    async def wallet_notifications_read(
        wallet_id: str,
        body: MarkReadRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        _gate_wallet(authorization, wallet_id)
        if engine.wallet_view(wallet_id) is None:
            raise HTTPException(status_code=404, detail="Wallet not found")
        marked = store.mark_notifications_read(wallet_id, body.ids or None)
        return {"ok": True, "marked": marked}

    @app.websocket("/api/ws")
    async def market_ws(websocket: WebSocket) -> None:
        # Cap concurrent sockets so a single client can't exhaust memory
        # (CWE-770). The public market feed is fine; over the cap we refuse.
        if manager.connection_count >= ws_max_connections:
            await websocket.close(code=1013)
            return
        await manager.connect(websocket)
        try:
            # First message may be a wallet subscription. Everything after is
            # ignored: we push the feed/count and only read to wait, detect
            # disconnect, and satisfy proxies' ping/pong.
            first: object | None = None
            try:
                first = json.loads(await websocket.receive_text())
            except Exception:
                pass
            if isinstance(first, dict) and str(first.get("type")) == "sub":
                wallet_id = str(first.get("wallet_id") or "").strip()
                # Subscribing a wallet is a read of that wallet's private
                # notification stream (deposits, withdrawals, mobile-money
                # numbers, fills, settlement payouts), so it is authorized
                # exactly like the HTTP notification endpoints. Without this
                # the socket was a straight bypass of the F-02 ownership gate:
                # anyone who learned a wallet id received its live money feed.
                token = str(first.get("token") or "").strip() or None
                denied = _wallet_access(token, wallet_id) if wallet_id else (400, "Missing wallet id")
                if denied is None:
                    manager.subscribe(websocket, wallet_id)
                else:
                    await websocket.send_text(
                        json.dumps(
                            {"type": "sub_error", "status": denied[0], "detail": denied[1]}
                        )
                    )
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception:
            manager.disconnect(websocket)

    @app.get("/api/watch", response_model=list[WatchItem])
    async def watch() -> list[WatchItem]:
        return [WatchItem(**w) for w in store.list_watch()]

    @app.get("/api/ticker", response_model=list[TickerItem])
    async def ticker() -> list[TickerItem]:
        return [TickerItem(**t) for t in store.list_ticker()]

    @app.get("/api/dashboard", response_model=DashboardData)
    async def dashboard() -> DashboardData:
        d = store.get_dashboard()
        return DashboardData(
            ranges={k: DashboardSeries(**v) for k, v in d["ranges"].items()},
            positions=[Position(**p) for p in d["positions"]],
        )

    @app.get("/api/stats", response_model=PortfolioStats)
    async def stats() -> PortfolioStats:
        return PortfolioStats(**store.get_stats())

    @app.get("/api/proof", response_model=Proof)
    async def proof() -> Proof:
        return Proof(**store.get_proof())

    @app.get("/api/staff", response_model=list[StaffPublic])
    async def public_staff() -> list[StaffPublic]:
        # Public team directory: active staff only, reduced to name + role.
        # Email/phone are PII and never leave the admin API (CWE-200).
        return [StaffPublic(**s) for s in staff.list_public()]

    @app.get("/api/home", response_model=HomeData)
    async def home() -> HomeData:
        d = store.get_dashboard()
        return HomeData(
            markets=_markets_group(),
            watch=[WatchItem(**w) for w in store.list_watch()],
            ticker=[TickerItem(**t) for t in store.list_ticker()],
            dashboard=DashboardData(
                ranges={k: DashboardSeries(**v) for k, v in d["ranges"].items()},
                positions=[Position(**p) for p in d["positions"]],
            ),
            stats=PortfolioStats(**store.get_stats()),
            proof=Proof(**store.get_proof()),
            settings=_public_settings(),
        )

    return app


app = create_app()
