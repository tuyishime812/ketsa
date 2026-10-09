"""Pydantic response models for the Ketsa prediction-market API.

These models are the single source of truth for the wire format that the
Next.js frontend consumes. Keep field names/types in sync with
`frontend/lib/types.ts`.
"""

import math
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, field_validator

Category = Literal['politics', 'crypto', 'sports', 'culture', 'tech', 'climate']
Trend = Literal['up', 'down']
Outcome = Literal['yes', 'no']
Side = Literal['buy', 'sell']
MarketStatus = Literal['open', 'closed', 'resolved']


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
    # Marketplace / detail fields (edited+served by the trading engine).
    description: str = ''
    end_date: Optional[str] = None  # ISO-8601 resolution time
    created: Optional[str] = None   # ISO-8601 market listing time
    volume: float = 0.0             # total traded notional, dollars
    liquidity: float = 0.0          # resting book value, dollars
    status: MarketStatus = 'open'
    last_price: Optional[int] = None  # most recent YES fill price in cents
    resolved_outcome: Optional[Outcome] = None  # winning outcome ('yes'/'no')
    resolved_price: Optional[int] = None        # final price of the winning outcome
    resolved_ts: Optional[float] = None         # unix time of resolution


class ResolveMarketRequest(BaseModel):
    outcome: Outcome
    reason: Optional[str] = None


class OrderLevel(BaseModel):
    price: int
    size: float


class OrderBook(BaseModel):
    yes: int             # current YES price
    no: int
    bids: List[OrderLevel]      # YES bids (buy YES), descending
    asks: List[OrderLevel]      # YES asks (sell YES), ascending
    no_bids: List[OrderLevel]   # NO bids, descending
    no_asks: List[OrderLevel]   # NO asks, ascending
    spread: int
    last: Optional[int] = None


class Trade(BaseModel):
    ts: float
    market_id: str
    question: str = ''
    outcome: Outcome
    side: Side
    price: int   # cents for the traded outcome (YES or NO)
    qty: float   # shares of the traded outcome
    notional: float  # dollars
    kind: Literal['trade', 'resolution'] = 'trade'  # 'resolution' = payout entry


class PositionLot(BaseModel):
    """One individual buy, so a stacked position can be listed per bet."""
    id: str
    shares: float
    price: int      # cents paid for this lot
    notional: float  # dollars committed to this lot
    ts: float


class WalletPosition(BaseModel):
    market_id: str
    question: str
    outcome: Outcome
    shares: float
    avg_price: int
    current_price: int
    value: float
    pnl_value: float
    # Individual fills behind this position, oldest first. Empty for wallets
    # persisted before lots were tracked; the aggregate fields above remain
    # authoritative for cost basis and P&L.
    lots: List[PositionLot] = []


class Wallet(BaseModel):
    id: str
    name: str
    balance: float
    # Real money paid in via wandePay — the ceiling on a withdrawal. Absent on
    # wallets persisted before the field existed, so default to 0.0 (a legacy
    # free seed stays play money and is never cashable).
    withdrawable: float = 0.0
    currency: str = "MWK"
    equity: float
    realized_pnl: float
    positions: List[WalletPosition]
    history: List[Trade]
    created: float


class WalletConnectRequest(BaseModel):
    id: Optional[str] = None
    name: str = 'Trader'


class User(BaseModel):
    id: str
    email: str
    phone: Optional[str] = None
    name: str
    wallet_id: str
    created: float


class ChangePasswordRequest(BaseModel):
    current: str
    new: str


class AdminUserView(BaseModel):
    """A user record enriched with live wallet stats for the admin panel."""
    id: str
    email: str
    phone: Optional[str] = None
    name: str
    wallet_id: str
    created: float
    wallet_equity: Optional[float] = None
    wallet_balance: Optional[float] = None
    positions: int = 0
    trades: int = 0
    last_seen: Optional[float] = None


class LeaderboardEntry(BaseModel):
    rank: int
    wallet_id: str
    name: str
    equity: float
    realized_pnl: float
    positions: int
    currency: str = "MWK"


class Notification(BaseModel):
    id: str
    wallet_id: str
    type: str  # fill | deposit | withdraw | system
    title: str
    message: str
    ts: float
    read: bool = False


class MarkReadRequest(BaseModel):
    ids: list[str] = []


class TradeRequest(BaseModel):
    wallet_id: str
    market_id: str
    outcome: Outcome
    side: Side
    amount: Optional[float] = None  # dollars — required for buys
    shares: Optional[float] = None  # shares — required for sells

    @field_validator("amount", "shares")
    @classmethod
    def _finite_positive(cls, v: Optional[float], info) -> Optional[float]:
        # JSON parsers accept NaN/Infinity literals; money math must never
        # receive them (false balance checks, poisoned ledgers).
        if v is not None and (not math.isfinite(v) or v <= 0):
            raise ValueError(f"{info.field_name} must be a finite, positive number")
        return v


class TradeResponse(BaseModel):
    wallet: Wallet
    market: Market
    book: OrderBook
    trade: Trade


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
    settings: dict[str, object] = {}  # editable site content (hero, cta, steps, footer, ...)


class DepositRequest(BaseModel):
    wallet_id: str
    amount: float
    number: str
    correspondent: str  # AIRTEL_MWI | TNM_MWI

    @field_validator("amount")
    @classmethod
    def _finite_positive(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError("amount must be a finite, positive number")
        return v


class WithdrawalRequest(BaseModel):
    wallet_id: str
    amount: float
    number: str
    correspondent: str  # AIRTEL_MWI | TNM_MWI

    @field_validator("amount")
    @classmethod
    def _finite_positive(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError("amount must be a finite, positive number")
        return v


class Payment(BaseModel):
    id: str
    wallet_id: str
    kind: str  # deposit | withdraw
    amount: float
    number: str
    correspondent: str
    status: str  # pending | completed | failed
    credited: bool = False  # deposits only — idempotency guard
    rolled_back: bool = False  # withdrawals only — refund guard if the payout fails
    wande_id: str | None = None
    message: str | None = None
    created: float
    updated: float
