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
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import store
from .admin import router as admin_router
from .engine import engine
from .storage import get_all_settings, init_db
from .models import (
    DashboardData,
    DashboardSeries,
    HomeData,
    Market,
    MarketsByCategory,
    MarketsGroup,
    OrderBook,
    PortfolioStats,
    Position,
    Proof,
    TickerItem,
    Trade,
    TradeRequest,
    TradeResponse,
    Wallet,
    WalletConnectRequest,
    WatchItem,
)

CATEGORIES = ['politics', 'crypto', 'sports', 'culture', 'tech', 'climate']


class ConnectionManager:
    """Fan-out of live market data to connected WebSocket clients."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    @property
    def connected(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, message: str) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections):
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


def create_app() -> "FastAPI":
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

    @app.post("/api/trade", response_model=TradeResponse)
    async def place_trade(body: TradeRequest) -> TradeResponse:
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

    @app.websocket("/api/ws")
    async def market_ws(websocket: WebSocket) -> None:
        await manager.connect(websocket)
        try:
            # The connection is receive-mostly: we push the global feed and only
            # read to wait, detect disconnect, and satisfy proxies' ping/pong.
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
