"""Ketsa backend — FastAPI application.

Serves the prediction-market data consumed by the Next.js frontend.

All public read endpoints source their data from the SQLite database (see
`database.py` / `store.py`), which is seeded from the original static data on
first run. Edits made through the protected admin API (see `admin.py`) are
reflected immediately on the public endpoints.

Security posture:
  * CORS is restricted to an explicit allowlist (no wildcards of origin).
  * Write operations live exclusively behind `/api/admin` and require a
    server-issued bearer token obtained via the admin password.
  * CSP / other browser security headers are set on every response.
"""

import os
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import store
from .admin import router as admin_router
from .database import get_all_settings, init_db
from .models import (
    DashboardData,
    DashboardSeries,
    HomeData,
    Market,
    MarketsByCategory,
    MarketsGroup,
    PortfolioStats,
    Position,
    Proof,
    TickerItem,
    WatchItem,
)

CATEGORIES = ['politics', 'crypto', 'sports', 'culture', 'tech', 'climate']


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
    markets = store.list_markets()
    by = {c: [m for m in markets if m["cat"] == c] for c in CATEGORIES}
    return MarketsGroup(
        all=[Market(**m) for m in markets],
        by_category=MarketsByCategory(**by),
    )


def _public_settings() -> dict:
    return get_all_settings()


def create_app() -> "FastAPI":
    # Ensure the database is initialised and seeded before serving requests.
    init_db()

    allowed_origins = (
        os.getenv("KETSA_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
        .split(",")
    )

    expose_docs = os.getenv("KETSA_EXPOSE_DOCS", "0").lower() in ("1", "true", "yes")
    rate_limit_per_min = int(os.getenv("KETSA_RATE_LIMIT_PER_MIN", "120"))
    limiter = _RateLimiter(rate_limit_per_min)

    app = FastAPI(
        title="Ketsa API",
        description="Real-time market data for the Ketsa prediction market.",
        version="1.1.0",
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
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
        m = store.get_market(market_id)
        if m is None:
            raise HTTPException(status_code=404, detail="Market not found")
        return Market(**m)

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
