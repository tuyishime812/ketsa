"""Pydantic response models for the Ketsa prediction-market API.

These models are the single source of truth for the wire format that the
Next.js frontend consumes. Keep field names/types in sync with
`frontend/lib/types.ts`.
"""

from typing import List, Literal, Tuple

from pydantic import BaseModel

Category = Literal['politics', 'crypto', 'sports', 'culture', 'tech', 'climate']
Trend = Literal['up', 'down']


class Market(BaseModel):
    id: str
    cat: Category
    tag: str
    q: str
    yes: int  # YES price in cents / probability
    no: int
    meta: Tuple[str, str]
    trend: Trend
    pts: List[int]


class WatchItem(BaseModel):
    name: str
    cat: Category
    price: int
    pts: List[int]


class TickerItem(BaseModel):
    t: str
    v: str
    d: Trend


class Position(BaseModel):
    name: str
    avg: int
    cur: int
    pts: List[int]


class DashboardSeries(BaseModel):
    pts: List[int]
    balance: int
    change: float


class DashboardData(BaseModel):
    ranges: dict[str, DashboardSeries]
    positions: List[Position]


class PortfolioStats(BaseModel):
    pnl: int
    open_positions: int
    win_rate: int


class MarketsByCategory(BaseModel):
    politics: List[Market]
    crypto: List[Market]
    sports: List[Market]
    culture: List[Market]
    tech: List[Market]
    climate: List[Market]


class MarketsGroup(BaseModel):
    all: List[Market]
    by_category: MarketsByCategory


class Proof(BaseModel):
    traders_k: int
    live_markets: int
    total_volume_m: float


class HomeData(BaseModel):
    markets: MarketsGroup
    watch: List[WatchItem]
    ticker: List[TickerItem]
    dashboard: DashboardData
    stats: PortfolioStats
    proof: Proof
