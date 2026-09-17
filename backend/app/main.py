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
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import payments as wande
from . import store
from .admin import MessageResponse, require_admin, router as admin_router
from .auth import resolve_optional_user, router as auth_router
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


def _public_settings() -> dict:
    return get_all_settings()


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
    manager = ConnectionManager()

    async def _tick_loop() -> None:
        # Simulated liquidity-provider repricing keeps the feed alive between
        # user trades so the order books feel genuinely live.
        while True:
            await asyncio.sleep(12)
            engine.random_tick()
            await _pump_events(manager)

    @asynccontextmanager
    async def _lifespan(_: FastAPI):
        task = asyncio.create_task(_tick_loop())
        try:
            yield
        finally:
            task.cancel()

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
        client = request.client.host if request.client else "unknown"
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
    async def connect_wallet(body: WalletConnectRequest) -> Wallet:
        return Wallet(**engine.connect_wallet(body.id, body.name))

    @app.get("/api/wallet/{wallet_id}", response_model=Wallet)
    async def get_wallet(wallet_id: str) -> Wallet:
        w = engine.wallet_view(wallet_id)
        if w is None:
            raise HTTPException(status_code=404, detail="Wallet not found")
        return Wallet(**w)

    # --- Real-money payments (wandePay — MWK) -------------------------------

    _TERMINAL_FAIL = ("FAILED", "DECLINED", "REVERSED", "CANCELLED", "ERROR")
    _money_lock = asyncio.Lock()

    def _require_payments() -> None:
        if not wande.configured():
            raise HTTPException(status_code=503, detail="Payments are not configured on this server")

    def _require_wallet(wallet_id: str) -> None:
        if engine.wallet_view(wallet_id) is None:
            raise HTTPException(status_code=404, detail="Wallet not found")

    def _gate_wallet_owner(authorization: str | None, wallet_id: str) -> None:
        """Account-owned wallets require the owning user's bearer token.

        Guests (no Authorization header) keep the simulated-wallet flow as-is.
        A supplied but invalid token raises 401; a token for a different
        account raises 403 so account wallets can't be drained by anyone who
        guesses/leaks the wallet id.
        """
        user = resolve_optional_user(authorization)
        if user is not None and user["wallet_id"] != wallet_id:
            raise HTTPException(status_code=403, detail="This wallet belongs to another account")

    def _payment_payload(rec: dict) -> dict:
        return Payment(**rec).model_dump()

    @app.post("/api/payments/deposits", response_model=Payment)
    async def create_deposit(
        body: DepositRequest, authorization: str | None = Header(default=None)
    ) -> Payment:
        _require_payments()
        _require_wallet(body.wallet_id)
        _gate_wallet_owner(authorization, body.wallet_id)
        try:
            number = wande.normalize_number(body.number)
        except wande.WandeError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if body.correspondent not in wande.CORRESPONDENTS:
            raise HTTPException(status_code=400, detail="Unknown correspondent")
        if body.amount < wande.MIN_AMOUNT_MWK:
            raise HTTPException(status_code=400, detail=f"Minimum deposit is {int(wande.MIN_AMOUNT_MWK)} MWK")
        try:
            payload = await asyncio.to_thread(
                wande.create_deposit, body.amount, number, body.correspondent
            )
        except wande.WandeError as e:
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
    async def list_payments(wallet_id: str | None = None) -> list[Payment]:
        return [_payment_payload(p) for p in store.list_payments(wallet_id)]

    @app.get("/api/payments/{payment_id}", response_model=Payment)
    async def payment_status(payment_id: str) -> Payment:
        _require_payments()
        rec = store.get_payment(payment_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="Payment not found")

        async with _money_lock:
            rec = store.get_payment(payment_id)  # re-read inside lock
            if rec["status"] != "pending":
                return _payment_payload(rec)

            if rec["kind"] == "deposit":
                try:
                    payload = await asyncio.to_thread(wande.deposit_status, rec["wande_id"])
                except wande.WandeError as e:
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
                    payload = await asyncio.to_thread(wande.withdrawal_status, rec["wande_id"])
                except wande.WandeError as e:
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
        body: WithdrawalRequest, authorization: str | None = Header(default=None)
    ) -> Payment:
        _require_payments()
        _require_wallet(body.wallet_id)
        _gate_wallet_owner(authorization, body.wallet_id)
        try:
            number = wande.normalize_number(body.number)
        except wande.WandeError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if body.correspondent not in wande.CORRESPONDENTS:
            raise HTTPException(status_code=400, detail="Unknown correspondent")
        if body.amount < wande.MIN_AMOUNT_MWK:
            raise HTTPException(status_code=400, detail=f"Minimum withdrawal is {int(wande.MIN_AMOUNT_MWK)} MWK")
        try:
            engine.debit_balance(body.wallet_id, body.amount)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        try:
            payload = await asyncio.to_thread(
                wande.create_withdrawal, body.amount, number, body.correspondent
            )
        except wande.WandeError as e:
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
    async def place_trade(
        body: TradeRequest, authorization: str | None = Header(default=None)
    ) -> TradeResponse:
        _gate_wallet_owner(authorization, body.wallet_id)
        try:
            result = engine.place_trade(
                body.wallet_id,
                body.market_id,
                body.outcome,
                body.side,
                amount=body.amount,
                shares=body.shares,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        await _pump_events(manager)
        return TradeResponse(**result)

    @app.post(
        "/api/admin/markets/{market_id}/resolve",
        response_model=MessageResponse,
        dependencies=[Depends(require_admin)],
    )
    async def admin_markets_resolve(
        market_id: str, body: ResolveMarketRequest
    ) -> MessageResponse:
        try:
            summary = engine.resolve_market(market_id, body.outcome)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        await _pump_events(manager)
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
    async def wallet_notifications(wallet_id: str, limit: int = 25) -> list[Notification]:
        if engine.wallet_view(wallet_id) is None:
            raise HTTPException(status_code=404, detail="Wallet not found")
        items = store.list_notifications(wallet_id, max(1, min(limit, 100)))
        return [Notification(**n) for n in items]

    @app.post("/api/wallet/{wallet_id}/notifications/read", response_model=dict)
    async def wallet_notifications_read(wallet_id: str, body: MarkReadRequest) -> dict:
        if engine.wallet_view(wallet_id) is None:
            raise HTTPException(status_code=404, detail="Wallet not found")
        marked = store.mark_notifications_read(wallet_id, body.ids or None)
        return {"ok": True, "marked": marked}

    @app.websocket("/api/ws")
    async def market_ws(websocket: WebSocket) -> None:
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
                if wallet_id:
                    manager.subscribe(websocket, wallet_id)
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
