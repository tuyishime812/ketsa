"""Ketsa backend — FastAPI application.

Serves the prediction-market data consumed by the Next.js frontend.

Security posture:
  * CORS is restricted to an explicit allowlist (no wildcards of origin).
  * All responses are read-only GET endpoints returning static seed data.
  * CSP / other browser security headers are set on every response.
"""

import os
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .data import (
    DASHBOARD,
    MARKETS,
    PROOF,
    STATS,
    TICKER,
    WATCH,
    markets_by_category,
)
from .models import (
    DashboardData,
    HomeData,
    Market,
    MarketsGroup,
    PortfolioStats,
    Proof,
    TickerItem,
    WatchItem,
)


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


def create_app() -> "FastAPI":
    # Configuration is read at app-creation time (not import time) so the app
    # factory is deterministic and easily testable with different environments.
    #
    # Origin allowlist. In production set KETSA_ALLOWED_ORIGINS to your hosted
    # frontend origin (comma-separated). Never use "*" with credentials.
    allowed_origins = (
        os.getenv("KETSA_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
        .split(",")
    )

    # Expose generated OpenAPI docs (/docs, /redoc, /openapi.json) only when
    # explicitly enabled. Default off to avoid leaking the schema of a public
    # read-only API to unauthenticated callers.
    expose_docs = os.getenv("KETSA_EXPOSE_DOCS", "0").lower() in ("1", "true", "yes")

    # Simple in-memory fixed-window rate limit. 0 disables the limiter
    # (e.g. trusted internal proxies / testing).
    rate_limit_per_min = int(os.getenv("KETSA_RATE_LIMIT_PER_MIN", "120"))
    limiter = _RateLimiter(rate_limit_per_min)

    app = FastAPI(
        title="Ketsa API",
        description="Real-time market data for the Ketsa prediction market.",
        version="1.0.0",
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET"],
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
        # Defence-in-depth browser security headers. The API is JSON-only, so a
        # strict CSP with no allowances is appropriate.
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        return response

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/markets", response_model=MarketsGroup)
    async def markets() -> MarketsGroup:
        return MarketsGroup(all=MARKETS, by_category=markets_by_category())

    @app.get("/api/markets/{market_id}", response_model=Market)
    async def market(market_id: str) -> Market:
        for m in MARKETS:
            if m.id == market_id:
                return m
        raise HTTPException(status_code=404, detail="Market not found")

    @app.get("/api/watch", response_model=list[WatchItem])
    async def watch() -> list[WatchItem]:
        return WATCH

    @app.get("/api/ticker", response_model=list[TickerItem])
    async def ticker() -> list[TickerItem]:
        return TICKER

    @app.get("/api/dashboard", response_model=DashboardData)
    async def dashboard() -> DashboardData:
        return DASHBOARD

    @app.get("/api/stats", response_model=PortfolioStats)
    async def stats() -> PortfolioStats:
        return STATS

    @app.get("/api/proof", response_model=Proof)
    async def proof() -> Proof:
        return PROOF

    @app.get("/api/home", response_model=HomeData)
    async def home() -> HomeData:
        return HomeData(
            markets=MarketsGroup(all=MARKETS, by_category=markets_by_category()),
            watch=WATCH,
            ticker=TICKER,
            dashboard=DASHBOARD,
            stats=STATS,
            proof=PROOF,
        )

    return app


app = create_app()
